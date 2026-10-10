"""Quiz authoring — quiz files, specs, and Canvas settings diffs.

A quiz file is TOML: settings at the top level, questions as ``[[questions]]``.
``load_quiz_file`` validates it into a ``QuizSpec``; ``dump_quiz_file`` writes
one back so ``export`` and ``create --from`` round-trip.
"""

from __future__ import annotations

__docformat__ = "google"

import difflib
import html
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..apis.canvas.times import format_when, parse_when, same_instant
from .config import format_toml_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasQuiz, CanvasQuizGroup, CanvasQuizQuestion

QUIZ_TYPES = ("practice_quiz", "assignment", "graded_survey", "survey")
SURVEY_TYPES = ("survey", "graded_survey")
HIDE_RESULTS = ("", "always", "until_after_last_attempt")
SCORING_POLICIES = ("keep_highest", "keep_latest")
TIME_FIELDS = ("unlock_at", "due_at", "lock_at")

QUESTION_TYPE_ALIASES = {
    "essay": "essay_question",
    "multiple_choice": "multiple_choice_question",
    "multiple_answers": "multiple_answers_question",
    "true_false": "true_false_question",
    "short_answer": "short_answer_question",
    "numerical": "numerical_question",
    "text_only": "text_only_question",
}
_CANVAS_TO_ALIAS = {v: k for k, v in QUESTION_TYPE_ALIASES.items()}


def question_type_alias(canvas_type: str) -> str:
    """Short quiz-file name for a Canvas question type, or the type unchanged."""
    return _CANVAS_TO_ALIAS.get(canvas_type, canvas_type)


ANSWER_TYPES = (
    "multiple_choice_question",
    "multiple_answers_question",
    "true_false_question",
)

_QUIZ_KEYS = (
    "title",
    "type",
    "group",
    "points",
    "description",
    "unlock_at",
    "due_at",
    "lock_at",
    "attempts",
    "time_limit",
    "hide_results",
    "scoring_policy",
    "shuffle_answers",
    "one_question_at_a_time",
    "published",
    "groups",
    "questions",
)
_GROUP_KEYS = ("name", "pick_count", "points_per_item")
_QUESTION_KEYS = ("id", "type", "text", "name", "points", "answers", "group")
DEFAULT_QUESTION_NAME_RE = re.compile(r"^Question( \d+)?$")
_ANSWER_KEYS = ("text", "correct")


@dataclass
class AnswerSpec:
    """One answer on a question; ``correct`` becomes Canvas weight 100."""

    text: str
    correct: bool = False


@dataclass
class GroupSpec:
    """A question group: Canvas draws ``pick_count`` of its questions per attempt."""

    name: str
    pick_count: int = 1
    points_per_item: float | None = None  # None = default_question_points(quiz_type)


@dataclass
class QuestionSpec:
    """One question in a quiz file."""

    text: str
    type: str = "essay_question"  # Canvas question_type after alias expansion
    name: str = ""
    points: float | None = None  # None = type default
    answers: list[AnswerSpec] = field(default_factory=list)
    group: str = ""  # question-group name, not the assignment group
    id: int | None = None  # Canvas question id, set by export


@dataclass
class QuizSpec:
    """Desired settings and questions for a Canvas Classic quiz."""

    title: str
    quiz_type: str
    group: str = ""
    points: float | None = None
    description: str = ""
    unlock_at: str = ""
    due_at: str = ""
    lock_at: str = ""
    attempts: int = 1
    time_limit: int = 0
    hide_results: str = ""
    scoring_policy: str = "keep_highest"
    shuffle_answers: bool = False
    one_question_at_a_time: bool = False
    published: bool = False
    groups: list[GroupSpec] = field(default_factory=list)
    questions: list[QuestionSpec] = field(default_factory=list)


def default_question_points(quiz_type: str) -> float:
    """Points a question gets when the file leaves them out."""
    return 0.0 if quiz_type in SURVEY_TYPES else 1.0


def is_default_question_name(name: str) -> bool:
    """True for Canvas's default question names ("Question", "Question 3") and ""."""
    return name == "" or DEFAULT_QUESTION_NAME_RE.match(name) is not None


def file_layout(spec: QuizSpec) -> list[tuple[str, int | str]]:
    """Top-level quiz entries in file order.

    ``("question", i)`` is an ungrouped question at ``spec.questions[i]``;
    ``("group", name)`` appears once, at its first question's place.
    """
    layout: list[tuple[str, int | str]] = []
    seen: set[str] = set()
    for index, question in enumerate(spec.questions):
        if not question.group:
            layout.append(("question", index))
        elif question.group not in seen:
            seen.add(question.group)
            layout.append(("group", question.group))
    return layout


def group_members(spec: QuizSpec) -> dict[str, list[int]]:
    """Group name → indices into ``spec.questions``, in file order."""
    members: dict[str, list[int]] = {}
    for index, question in enumerate(spec.questions):
        if question.group:
            members.setdefault(question.group, []).append(index)
    return members


def question_form_fields(question: QuestionSpec, quiz_type: str) -> dict[str, object]:
    """Canvas question fields for *question* (``answers`` only when it has any)."""
    points = (
        question.points
        if question.points is not None
        else default_question_points(quiz_type)
    )
    fields: dict[str, object] = {
        "question_name": question.name or "Question",
        "question_text": question.text,
        "question_type": question.type,
        "points_possible": _number(points),
    }
    if question.answers:
        fields["answers"] = answer_form_fields(question.answers)
    return fields


def answer_form_fields(answers: list[AnswerSpec]) -> list[dict[str, object]]:
    """Canvas answer fields for *answers*; a correct answer gets weight 100."""
    return [
        {"answer_text": a.text, "answer_weight": 100 if a.correct else 0}
        for a in answers
    ]


def group_form_fields(group: GroupSpec, quiz_type: str) -> dict[str, object]:
    """Canvas body for creating *group* (points per item default by quiz type)."""
    points = (
        group.points_per_item
        if group.points_per_item is not None
        else default_question_points(quiz_type)
    )
    return {
        "name": group.name,
        "pick_count": group.pick_count,
        "question_points": _number(points),
    }


# --- Quiz files ---


def _fail(path: Path, message: str) -> None:
    raise SystemExit(f"{path}: {message}")


def _check_keys(
    path: Path, table: dict[str, Any], allowed: tuple[str, ...], where: str
) -> None:
    for key in table:
        if key in allowed:
            continue
        hint = difflib.get_close_matches(key, allowed, n=1)
        suggestion = f" (did you mean '{hint[0]}'?)" if hint else ""
        _fail(path, f"unknown key '{key}'{suggestion}{where}")


def load_quiz_file(path: Path) -> QuizSpec:
    """Read and validate a quiz TOML file.

    Raises:
        SystemExit: Naming the file and offending key for any problem.
    """
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"{path}: {exc}") from None

    _check_keys(path, raw, _QUIZ_KEYS, "")
    for key in ("title", "type"):
        if key not in raw:
            _fail(path, f"missing required key '{key}'")
    quiz_type = raw["type"]
    if quiz_type not in QUIZ_TYPES:
        _fail(path, f"type must be one of {', '.join(QUIZ_TYPES)}, not '{quiz_type}'")
    if raw.get("hide_results", "") not in HIDE_RESULTS:
        allowed = ", ".join(repr(v) for v in HIDE_RESULTS)
        _fail(path, f"hide_results must be one of {allowed}")
    if raw.get("scoring_policy", "keep_highest") not in SCORING_POLICIES:
        _fail(path, f"scoring_policy must be one of {', '.join(SCORING_POLICIES)}")
    if "points" in raw and quiz_type != "graded_survey":
        _fail(path, 'points is only valid for type = "graded_survey"')

    groups: list[GroupSpec] = []
    for number, g in enumerate(raw.get("groups", []), 1):
        where = f" in group {number}"
        _check_keys(path, g, _GROUP_KEYS, where)
        if "name" not in g:
            _fail(path, f"missing required key 'name'{where}")
        if any(existing.name == g["name"] for existing in groups):
            _fail(path, f"two [[groups]] are named '{g['name']}'")
        per_item = g.get("points_per_item")
        groups.append(
            GroupSpec(
                name=g["name"],
                pick_count=int(g.get("pick_count", 1)),
                points_per_item=float(per_item) if per_item is not None else None,
            )
        )
    group_names = {g.name for g in groups}

    questions: list[QuestionSpec] = []
    seen_ids: set[int] = set()
    closed_groups: set[str] = set()
    previous_group = ""
    for index, q in enumerate(raw.get("questions", []), 1):
        where = f" in question {index}"
        _check_keys(path, q, _QUESTION_KEYS, where)
        if "text" not in q:
            _fail(path, f"missing required key 'text'{where}")
        short_type = q.get("type", "essay")
        qtype = QUESTION_TYPE_ALIASES.get(short_type, short_type)
        answers = [_load_answer(path, a, where) for a in q.get("answers", [])]
        if qtype in ANSWER_TYPES and not answers:
            _fail(path, f"answers are required for type '{short_type}'{where}")
        if qtype == "multiple_choice_question" and sum(a.correct for a in answers) > 1:
            _fail(path, f"multiple_choice allows only one correct answer{where}")
        points = q.get("points")
        group = q.get("group", "")
        if group and group not in group_names:
            _fail(
                path,
                f"group '{group}' in question {index} is not declared in [[groups]]",
            )
        if group and group in closed_groups:
            _fail(
                path,
                f"questions in group '{group}' must be contiguous (question {index})",
            )
        if previous_group and group != previous_group:
            closed_groups.add(previous_group)
        previous_group = group
        question_id = q.get("id")
        if question_id is not None:
            if question_id in seen_ids:
                _fail(
                    path,
                    f"id {question_id} appears on two questions (question {index})",
                )
            seen_ids.add(question_id)
        name = q.get("name", "")
        questions.append(
            QuestionSpec(
                text=q["text"],
                type=qtype,
                name="" if is_default_question_name(name) else name,
                points=float(points) if points is not None else None,
                answers=answers,
                group=group,
                id=question_id,
            )
        )
    for g in groups:
        if not any(q.group == g.name for q in questions):
            _fail(path, f"group '{g.name}' has no questions")

    points = raw.get("points")
    return QuizSpec(
        title=raw["title"],
        quiz_type=quiz_type,
        group=raw.get("group", ""),
        points=float(points) if points is not None else None,
        description=raw.get("description", ""),
        unlock_at=raw.get("unlock_at", ""),
        due_at=raw.get("due_at", ""),
        lock_at=raw.get("lock_at", ""),
        attempts=int(raw.get("attempts", 1)),
        time_limit=int(raw.get("time_limit", 0)),
        hide_results=raw.get("hide_results", ""),
        scoring_policy=raw.get("scoring_policy", "keep_highest"),
        shuffle_answers=bool(raw.get("shuffle_answers", False)),
        one_question_at_a_time=bool(raw.get("one_question_at_a_time", False)),
        published=bool(raw.get("published", False)),
        groups=groups,
        questions=questions,
    )


def _load_answer(path: Path, raw: dict[str, Any], where: str) -> AnswerSpec:
    _check_keys(path, raw, _ANSWER_KEYS, where)
    if "text" not in raw:
        _fail(path, f"missing required key 'text' in an answer{where}")
    return AnswerSpec(text=raw["text"], correct=bool(raw.get("correct", False)))


def _number(value: float) -> int | float:
    """Write whole numbers without a trailing ``.0``."""
    return int(value) if float(value).is_integer() else value


def dump_quiz_file(spec: QuizSpec, path: Path | None) -> str:
    """Render *spec* as quiz-file TOML, writing it to *path* when given."""
    lines = [
        f"title = {format_toml_value(spec.title)}",
        f"type = {format_toml_value(spec.quiz_type)}",
        f"group = {format_toml_value(spec.group)}",
    ]
    if spec.points is not None:
        lines.append(f"points = {format_toml_value(_number(spec.points))}")
    lines += [
        f"description = {format_toml_value(spec.description)}",
        f"unlock_at = {format_toml_value(spec.unlock_at)}",
        f"due_at = {format_toml_value(spec.due_at)}",
        f"lock_at = {format_toml_value(spec.lock_at)}",
        f"attempts = {spec.attempts}",
        f"time_limit = {spec.time_limit}",
        f"hide_results = {format_toml_value(spec.hide_results)}",
        f"scoring_policy = {format_toml_value(spec.scoring_policy)}",
        f"shuffle_answers = {format_toml_value(spec.shuffle_answers)}",
        f"one_question_at_a_time = {format_toml_value(spec.one_question_at_a_time)}",
        f"published = {format_toml_value(spec.published)}",
    ]
    for g in spec.groups:
        lines += ["", "[[groups]]", f"name = {format_toml_value(g.name)}"]
        lines.append(f"pick_count = {g.pick_count}")
        if g.points_per_item is not None:
            lines.append(
                f"points_per_item = {format_toml_value(_number(g.points_per_item))}"
            )
    for q in spec.questions:
        lines += ["", "[[questions]]"]
        if q.id is not None:
            lines.append(f"id = {q.id}")
        lines.append(
            f"type = {format_toml_value(_CANVAS_TO_ALIAS.get(q.type, q.type))}"
        )
        if q.group:
            lines.append(f"group = {format_toml_value(q.group)}")
        if q.name:
            lines.append(f"name = {format_toml_value(q.name)}")
        lines.append(f"text = {format_toml_value(q.text)}")
        if q.points is not None:
            lines.append(f"points = {format_toml_value(_number(q.points))}")
        if q.answers:
            items = []
            for a in q.answers:
                entry = f"text = {format_toml_value(a.text)}"
                if a.correct:
                    entry += ", correct = true"
                items.append("{ " + entry + " }")
            lines.append("answers = [" + ", ".join(items) + "]")
    text = "\n".join(lines) + "\n"
    if path is not None:
        path.write_text(text)
    return text


# --- Canvas mapping ---


def canvas_layout(
    questions: list[CanvasQuizQuestion], groups: list[CanvasQuizGroup]
) -> list[tuple[str, int]]:
    """Top-level quiz entries in Canvas order.

    The questions API reports every question's ``position`` as null, so the
    order is rebuilt from what Canvas does report: *questions* in API list
    order, and each group's ``position`` from the group endpoint.

    With n top-level entries (ungrouped questions plus groups), each group
    takes its position clamped to 1..n, in (position, id) order; a group whose
    slot is taken moves to the next free one. Groups with a null position go
    last. Ungrouped questions fill the remaining slots in list order. The
    result is exact when top-level positions run 1..n, which every cass apply
    leaves.

    Args:
        questions: Questions in the order the questions API lists them.
        groups: The quiz's question groups.
    """
    ungrouped = [q.id for q in questions if q.quiz_group_id is None]
    slot_count = len(ungrouped) + len(groups)
    slots: list[tuple[str, int] | None] = [None] * slot_count

    # Every group in `positioned` has a position; the `or` fallbacks only
    # satisfy the type checker.
    positioned = sorted(
        (g for g in groups if g.position is not None),
        key=lambda g: (g.position or 0, g.id),
    )
    for group in positioned:
        wanted = min(max(group.position or 1, 1), slot_count) - 1
        slots[_free_slot(slots, wanted)] = ("group", group.id)

    unpositioned = sorted((g for g in groups if g.position is None), key=lambda g: g.id)
    if unpositioned:
        free = [i for i, entry in enumerate(slots) if entry is None]
        for group, slot in zip(unpositioned, free[-len(unpositioned) :], strict=True):
            slots[slot] = ("group", group.id)

    remaining = iter(ungrouped)
    return [
        entry if entry is not None else ("question", next(remaining)) for entry in slots
    ]


def _free_slot(slots: list[tuple[str, int] | None], wanted: int) -> int:
    """First free index at or after *wanted*, else the last free one before it."""
    for index in range(wanted, len(slots)):
        if slots[index] is None:
            return index
    return max(i for i in range(wanted) if slots[i] is None)


def ordered_questions(
    questions: list[CanvasQuizQuestion], groups: list[CanvasQuizGroup]
) -> list[CanvasQuizQuestion]:
    """All questions in quiz order, each group expanded in place.

    Args:
        questions: Questions in the order the questions API lists them; a
            group's members keep that order.
        groups: The quiz's question groups.
    """
    by_id = {q.id: q for q in questions}
    ordered: list[CanvasQuizQuestion] = []
    for kind, entry_id in canvas_layout(questions, groups):
        if kind == "question":
            ordered.append(by_id[entry_id])
            continue
        ordered += [q for q in questions if q.quiz_group_id == entry_id]
    return ordered


def group_name_of(
    question: CanvasQuizQuestion, groups: Sequence[CanvasQuizGroup]
) -> str:
    """Name of the group holding *question*, or "" when it has none."""
    if question.quiz_group_id is None:
        return ""
    for group in groups:
        if group.id == question.quiz_group_id:
            return group.name
    return ""


def groups_by_name(
    groups: Sequence[CanvasQuizGroup], quiz_title: str
) -> dict[str, CanvasQuizGroup]:
    """Live question groups keyed by name.

    Raises:
        RuntimeError: Two groups share a name.
    """
    by_name: dict[str, CanvasQuizGroup] = {}
    for group in groups:
        if group.name in by_name:
            raise RuntimeError(
                f"Quiz {quiz_title!r} has two question groups named "
                f"{group.name!r}; rename one in Canvas first."
            )
        by_name[group.name] = group
    return by_name


@dataclass
class QuizState:
    """A quiz as it is on Canvas: settings, questions in quiz order, groups."""

    quiz: CanvasQuiz
    questions: list[CanvasQuizQuestion]
    groups: list[CanvasQuizGroup]
    from_statistics: bool = False
    student_attempts: int = 0


def fetch_quiz_state(
    client: CanvasClient,
    quiz_id: int,
    *,
    allow_statistics: bool = False,
    include_submissions: bool = False,
) -> QuizState:
    """Read a quiz, its questions in quiz order, and its question groups.

    Args:
        client: Canvas client.
        quiz_id: Canvas quiz ID.
        allow_statistics: Accept questions rebuilt from quiz statistics
            (concluded courses); otherwise that raises.
        include_submissions: Also count finished student attempts.

    Raises:
        RuntimeError: Questions came from statistics and that is not allowed.
    """
    quiz = client.get_quiz(quiz_id)
    questions, from_statistics = client.list_quiz_questions(quiz_id)
    if from_statistics and not allow_statistics:
        raise RuntimeError(
            f"Quiz {quiz.title}: questions came from quiz statistics (concluded "
            "course), which lack names and answer weights; questions cannot be "
            "edited."
        )
    group_ids = sorted(
        {q.quiz_group_id for q in questions if q.quiz_group_id is not None}
    )
    groups = [client.get_question_group(quiz_id, gid) for gid in group_ids]
    groups.sort(key=lambda g: (g.position or 0, g.id))
    student_attempts = 0
    if include_submissions:
        student_ids = {s.id for s in client.list_students()}
        student_attempts = sum(
            1
            for sub in client.list_quiz_submissions(quiz_id)
            if sub.workflow_state in ("complete", "pending_review")
            and sub.user_id in student_ids
        )
    return QuizState(
        quiz=quiz,
        questions=ordered_questions(questions, groups),
        groups=groups,
        from_statistics=from_statistics,
        student_attempts=student_attempts,
    )


def quiz_spec_from_canvas(
    quiz: CanvasQuiz,
    questions: list[CanvasQuizQuestion],
    group_name: str,
    tz: str,
    *,
    groups: Sequence[CanvasQuizGroup] = (),
) -> QuizSpec:
    """Build a spec from a live quiz, with times in the course zone.

    Questions come out in quiz order, carrying their Canvas ids and group names.

    Raises:
        RuntimeError: Two groups share a name.
    """
    groups = list(groups)
    groups_by_name(groups, quiz.title)
    question_specs: list[QuestionSpec] = []
    for q in ordered_questions(questions, groups):
        question_specs.append(
            QuestionSpec(
                id=q.id,
                group=group_name_of(q, groups),
                text=q.question_text,
                type=q.question_type,
                name=""
                if is_default_question_name(q.question_name)
                else q.question_name,
                points=q.points_possible if q.points_possible is not None else 0.0,
                answers=[
                    AnswerSpec(text=a.text, correct=a.weight > 0) for a in q.answers
                ],
            )
        )
    group_specs = [
        GroupSpec(
            name=g.name,
            pick_count=g.pick_count,
            points_per_item=(
                g.question_points
                if g.question_points is not None
                else default_question_points(quiz.quiz_type)
            ),
        )
        for g in groups
    ]
    return QuizSpec(
        title=quiz.title,
        quiz_type=quiz.quiz_type,
        group=group_name,
        points=quiz.points_possible if quiz.quiz_type == "graded_survey" else None,
        description=quiz.description or "",
        unlock_at=format_when(quiz.unlock_at, tz),
        due_at=format_when(quiz.due_at, tz),
        lock_at=format_when(quiz.lock_at, tz),
        attempts=quiz.allowed_attempts,
        time_limit=quiz.time_limit or 0,
        hide_results=quiz.hide_results or "",
        scoring_policy=quiz.scoring_policy or "keep_highest",
        shuffle_answers=quiz.shuffle_answers,
        one_question_at_a_time=quiz.one_question_at_a_time,
        published=quiz.published,
        groups=group_specs,
        questions=question_specs,
    )


def quiz_form_fields(
    spec: QuizSpec, tz: str, *, assignment_group_id: int | None = None
) -> dict[str, object]:
    """Canvas quiz fields for *spec* (Canvas names, without the ``quiz[]`` wrapper).

    Empty strings clear a field on Canvas; ``time_limit`` 0 is sent as "".
    """
    fields: dict[str, object] = {
        "title": spec.title,
        "quiz_type": spec.quiz_type,
        "description": spec.description,
        "allowed_attempts": spec.attempts,
        "time_limit": spec.time_limit or "",
        "hide_results": spec.hide_results,
        "scoring_policy": spec.scoring_policy,
        "shuffle_answers": spec.shuffle_answers,
        "one_question_at_a_time": spec.one_question_at_a_time,
        "unlock_at": parse_when(spec.unlock_at, tz),
        "due_at": parse_when(spec.due_at, tz),
        "lock_at": parse_when(spec.lock_at, tz),
        "published": spec.published,
    }
    if spec.points is not None:
        fields["points_possible"] = _number(spec.points)
    if assignment_group_id is not None:
        fields["assignment_group_id"] = assignment_group_id
    return fields


def quiz_settings_diff(
    spec: QuizSpec, live: CanvasQuiz, tz: str, *, group_id: int | None = None
) -> dict[str, object]:
    """Canvas fields whose live value differs from *spec*.

    Times compare by instant, so an offset-only difference is not a change.
    Questions are never compared.
    """
    desired = quiz_form_fields(spec, tz, assignment_group_id=group_id)
    current: dict[str, object] = {
        "title": live.title,
        "quiz_type": live.quiz_type,
        "description": live.description or "",
        "allowed_attempts": live.allowed_attempts,
        "time_limit": live.time_limit or "",
        "hide_results": live.hide_results or "",
        "scoring_policy": live.scoring_policy,
        "shuffle_answers": live.shuffle_answers,
        "one_question_at_a_time": live.one_question_at_a_time,
        "unlock_at": live.unlock_at or "",
        "due_at": live.due_at or "",
        "lock_at": live.lock_at or "",
        "published": live.published,
        "points_possible": live.points_possible,
        "assignment_group_id": live.assignment_group_id,
    }
    changes: dict[str, object] = {}
    for key, want in desired.items():
        have = current[key]
        if key in TIME_FIELDS:
            equal = same_instant(str(have) or None, str(want) or None)
        else:
            equal = have == want
        if not equal:
            changes[key] = want
    return changes


_BLOCK_END_RE = re.compile(
    r"</?(?:p|div|li|ul|ol|br|h[1-6]|tr|td|th|table)\b[^>]*>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Drop tags, unescape entities, and collapse whitespace.

    Block-level tags become spaces so adjacent paragraphs do not run together;
    inline tags such as ``<b>`` vanish without adding a space.
    """
    spaced = _BLOCK_END_RE.sub(" ", text)
    return " ".join(html.unescape(_TAG_RE.sub("", spaced)).split())


# --- Sync ---


def sync_quizzes(
    client: CanvasClient,
    specs: list[QuizSpec],
    group_ids: dict[str, int],
    tz: str,
    *,
    created: list[CanvasQuiz] | None = None,
) -> list[tuple[str, str, str]]:
    """Reconcile quiz specs against live quizzes, matched by title.

    Questions on an existing quiz are never compared or modified. Writes
    always go through ``client``; dry runs pass a dry-run client.

    Args:
        created: When given, each quiz this call creates is appended to it.

    Returns:
        ``(action, "quiz", name)`` rows: create, update (with the changed
        fields), or skip.
    """
    live_by_title = {q.title.lower(): q for q in client.list_quizzes()}
    rows: list[tuple[str, str, str]] = []
    for spec in specs:
        group_id = group_ids.get(spec.group.lower()) if spec.group else None
        live = live_by_title.get(spec.title.lower())
        if live is None:
            rows.append(("create", "quiz", spec.title))
            new_quiz = client.create_quiz(spec, assignment_group_id=group_id)
            if created is not None:
                created.append(new_quiz)
            continue
        changes = quiz_settings_diff(spec, live, tz, group_id=group_id)
        if not changes:
            rows.append(("skip", "quiz", spec.title))
            continue
        detail = ", ".join(f"{k}: {v}" for k, v in changes.items())
        rows.append(("update", "quiz", f"{spec.title} ({detail})"))
        client.update_quiz(live.id, changes)
    return rows
