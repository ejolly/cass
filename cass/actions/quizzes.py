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
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasQuiz, CanvasQuizQuestion

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
    "questions",
)
_QUESTION_KEYS = ("type", "text", "name", "points", "answers")
_ANSWER_KEYS = ("text", "correct")


@dataclass
class AnswerSpec:
    """One answer on a question; ``correct`` becomes Canvas weight 100."""

    text: str
    correct: bool = False


@dataclass
class QuestionSpec:
    """One question in a quiz file."""

    text: str
    type: str = "essay_question"  # Canvas question_type after alias expansion
    name: str = ""
    points: float | None = None  # None = type default
    answers: list[AnswerSpec] = field(default_factory=list)


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
    questions: list[QuestionSpec] = field(default_factory=list)


def default_question_points(quiz_type: str) -> float:
    """Points a question gets when the file leaves them out."""
    return 0.0 if quiz_type in SURVEY_TYPES else 1.0


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

    questions: list[QuestionSpec] = []
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
        questions.append(
            QuestionSpec(
                text=q["text"],
                type=qtype,
                name=q.get("name", ""),
                points=float(points) if points is not None else None,
                answers=answers,
            )
        )

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
    for q in spec.questions:
        lines += ["", "[[questions]]"]
        lines.append(
            f"type = {format_toml_value(_CANVAS_TO_ALIAS.get(q.type, q.type))}"
        )
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


def quiz_spec_from_canvas(
    quiz: CanvasQuiz,
    questions: list[CanvasQuizQuestion],
    group_name: str,
    tz: str,
) -> QuizSpec:
    """Build a spec from a live quiz, with times in the course zone."""
    question_specs: list[QuestionSpec] = []
    for position, q in enumerate(sorted(questions, key=lambda q: q.position or 0), 1):
        default_name = q.question_name in ("", f"Question {position}")
        question_specs.append(
            QuestionSpec(
                text=q.question_text,
                type=q.question_type,
                name="" if default_name else q.question_name,
                points=q.points_possible if q.points_possible is not None else 0.0,
                answers=[
                    AnswerSpec(text=a.text, correct=a.weight > 0) for a in q.answers
                ],
            )
        )
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
    apply: bool,
) -> list[tuple[str, str, str]]:
    """Reconcile quiz specs against live quizzes, matched by title.

    Questions on an existing quiz are never compared or modified.

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
            if apply:
                client.create_quiz(spec, assignment_group_id=group_id)
            continue
        changes = quiz_settings_diff(spec, live, tz, group_id=group_id)
        if not changes:
            rows.append(("skip", "quiz", spec.title))
            continue
        detail = ", ".join(f"{k}: {v}" for k, v in changes.items())
        rows.append(("update", "quiz", f"{spec.title} ({detail})"))
        if apply:
            client.update_quiz(live.id, changes)
    return rows
