"""Question planning — compare a quiz file's questions with a live quiz.

``plan_quiz_questions`` matches each file question to a live question (by id,
then unique name, then relative order) and records what must change. It does
no I/O; applying the plan is a separate step.
"""

from __future__ import annotations

__docformat__ = "google"

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .quizzes import (
    GroupSpec,
    QuestionSpec,
    QuizSpec,
    QuizState,
    canvas_layout,
    default_question_points,
    file_layout,
    group_members,
    is_default_question_name,
    strip_html,
)

if TYPE_CHECKING:
    from ..apis.canvas.schema import CanvasQuizGroup, CanvasQuizQuestion

QUESTION_FIELDS = ("text", "name", "type", "points", "answers", "group")
GROUP_FIELDS = ("pick_count", "points_per_item")

ANSWERS_REPLACED_NOTE = (
    "(answers replaced: existing responses may lose their answer link)"
)
EXTRA_NOTE = "(not in file; kept — --prune deletes it)"
SNIPPET_LENGTH = 60


@dataclass
class QuestionChange:
    """What happens to one question.

    ``action`` is "add", "update", "delete", "keep" or "extra" (on Canvas, not
    in the file, left alone).
    """

    action: str
    spec: QuestionSpec | None  # None for delete / extra
    live: CanvasQuizQuestion | None  # None for add
    group: str = ""  # desired group (current group for delete / extra)
    changed: list[str] = field(default_factory=list)  # QUESTION_FIELDS order


@dataclass
class GroupChange:
    """What happens to one question group (same actions as questions)."""

    action: str
    spec: GroupSpec | None  # None for delete / extra
    live: CanvasQuizGroup | None  # None for add
    changed: list[str] = field(default_factory=list)  # GROUP_FIELDS order

    @property
    def name(self) -> str:
        """The group's name, from the file when it has one."""
        if self.spec is not None:
            return self.spec.name
        assert self.live is not None
        return self.live.name


@dataclass
class QuestionPlan:
    """Every question and group change needed to make a quiz match its file.

    ``questions`` lists file questions first (``questions[i]`` is
    ``spec.questions[i]``), then deletes and extras in quiz order. ``order`` is
    the desired top-level layout: ``("question", index into questions)`` or
    ``("group", name)``, extras last.
    """

    quiz_id: int
    quiz_type: str
    questions: list[QuestionChange]
    groups: list[GroupChange]
    order: list[tuple[str, int | str]]
    group_members: dict[str, list[int]]  # name -> indices into questions
    order_changed: bool
    reordered_groups: list[str]  # membership or order changes, plus new groups
    student_attempts: int = 0

    @property
    def has_changes(self) -> bool:
        """True when applying the plan would send anything to Canvas."""
        changes = [*self.questions, *self.groups]
        if any(change.action not in ("keep", "extra") for change in changes):
            return True
        return self.order_changed or bool(self.reordered_groups)


# --- Matching ---


def _match_name(name: str) -> str:
    """The name used for matching: Canvas default names count as empty."""
    return "" if is_default_question_name(name) else name


def _match_questions(spec: QuizSpec, state: QuizState) -> dict[int, CanvasQuizQuestion]:
    """Pair file question indices with live questions: by id, name, then order.

    Raises:
        RuntimeError: A file question's id is not on the quiz.
    """
    by_id = {q.id: q for q in state.questions}
    pairs: dict[int, CanvasQuizQuestion] = {}

    # Pass 1: by id
    for index, question in enumerate(spec.questions):
        if question.id is None:
            continue
        if question.id not in by_id:
            raise RuntimeError(
                f"Question {index + 1} has id {question.id}, which is not a "
                f"question on quiz {state.quiz.title!r}."
            )
        pairs[index] = by_id[question.id]

    # Pass 2: by name, when the name is unique among unmatched questions on both sides
    unmatched_file = _unmatched_file(spec, pairs)
    unmatched_live = _unmatched_live(state, pairs)
    file_names = Counter(_match_name(q.name) for _, q in unmatched_file)
    live_names = Counter(_match_name(q.question_name) for q in unmatched_live)
    for index, question in unmatched_file:
        name = _match_name(question.name)
        if name and file_names[name] == 1 and live_names[name] == 1:
            pairs[index] = next(
                q for q in unmatched_live if _match_name(q.question_name) == name
            )

    # Pass 3: by relative order
    unmatched_file = _unmatched_file(spec, pairs)
    unmatched_live = _unmatched_live(state, pairs)
    for (index, _), live in zip(unmatched_file, unmatched_live, strict=False):
        pairs[index] = live
    return pairs


def _unmatched_file(
    spec: QuizSpec, pairs: dict[int, CanvasQuizQuestion]
) -> list[tuple[int, QuestionSpec]]:
    return [(i, q) for i, q in enumerate(spec.questions) if i not in pairs]


def _unmatched_live(
    state: QuizState, pairs: dict[int, CanvasQuizQuestion]
) -> list[CanvasQuizQuestion]:
    matched_ids = {q.id for q in pairs.values()}
    return [q for q in state.questions if q.id not in matched_ids]


def _question_changes(
    question: QuestionSpec,
    live: CanvasQuizQuestion,
    current_group: str,
    quiz_type: str,
) -> list[str]:
    """Fields (in QUESTION_FIELDS order) where the file differs from Canvas."""
    desired_points = (
        question.points
        if question.points is not None
        else default_question_points(quiz_type)
    )
    desired_answers = [(a.text, a.correct) for a in question.answers]
    live_answers = [(a.text, a.weight > 0) for a in live.answers]
    differs = {
        "text": question.text != live.question_text,
        # An empty file name keeps whatever name Canvas has.
        "name": bool(question.name) and question.name != live.question_name,
        "type": question.type != live.question_type,
        "points": desired_points != (live.points_possible or 0.0),
        "answers": desired_answers != live_answers,
        "group": question.group != current_group,
    }
    return [name for name in QUESTION_FIELDS if differs[name]]


def _group_changes(
    group: GroupSpec, live: CanvasQuizGroup, quiz_type: str
) -> list[str]:
    """Fields (in GROUP_FIELDS order) where the file group differs from Canvas."""
    default_points = default_question_points(quiz_type)
    desired_points = (
        group.points_per_item if group.points_per_item is not None else default_points
    )
    live_points = (
        live.question_points if live.question_points is not None else default_points
    )
    differs = {
        "pick_count": group.pick_count != live.pick_count,
        "points_per_item": desired_points != live_points,
    }
    return [name for name in GROUP_FIELDS if differs[name]]


def _live_groups_by_name(state: QuizState) -> dict[str, CanvasQuizGroup]:
    """Live groups keyed by name.

    Raises:
        RuntimeError: Two live groups share a name.
    """
    by_name: dict[str, CanvasQuizGroup] = {}
    for group in state.groups:
        if group.name in by_name:
            raise RuntimeError(
                f"Quiz {state.quiz.title!r} has two question groups named "
                f"{group.name!r}; rename one in Canvas first."
            )
        by_name[group.name] = group
    return by_name


# --- Planning ---


def plan_quiz_questions(
    spec: QuizSpec, state: QuizState, *, prune: bool
) -> QuestionPlan:
    """Plan the question and group changes that make *state* match *spec*.

    Args:
        spec: Desired quiz, from a quiz file.
        state: The quiz as it is on Canvas.
        prune: Delete live questions and emptied groups the file leaves out;
            otherwise they are kept as extras.

    Raises:
        RuntimeError: A file id is not on the quiz, or two live groups share a
            name.
    """
    quiz_type = state.quiz.quiz_type
    live_groups = _live_groups_by_name(state)
    group_name_by_id = {g.id: g.name for g in state.groups}

    def current_group(question: CanvasQuizQuestion) -> str:
        return group_name_by_id.get(question.quiz_group_id or 0, "")

    # Questions: file questions first, then live leftovers in quiz order
    pairs = _match_questions(spec, state)
    questions: list[QuestionChange] = []
    for index, question in enumerate(spec.questions):
        live = pairs.get(index)
        if live is None:
            questions.append(QuestionChange("add", question, None, question.group))
            continue
        changed = _question_changes(question, live, current_group(live), quiz_type)
        action = "update" if changed else "keep"
        questions.append(
            QuestionChange(action, question, live, question.group, changed)
        )
    leftover_action = "delete" if prune else "extra"
    for live in _unmatched_live(state, pairs):
        questions.append(
            QuestionChange(leftover_action, None, live, current_group(live))
        )

    # Groups: file groups in file order, then unmatched live groups
    groups: list[GroupChange] = []
    for group in spec.groups:
        live_group = live_groups.get(group.name)
        if live_group is None:
            groups.append(GroupChange("add", group, None))
            continue
        changed = _group_changes(group, live_group, quiz_type)
        groups.append(
            GroupChange("update" if changed else "keep", group, live_group, changed)
        )
    file_group_names = {g.name for g in spec.groups}
    for live_group in state.groups:
        if live_group.name in file_group_names:
            continue
        still_holds_questions = any(
            change.live is not None
            and change.live.quiz_group_id == live_group.id
            and change.action != "delete"
            and change.group == live_group.name
            for change in questions
        )
        action = "delete" if prune and not still_holds_questions else "extra"
        groups.append(GroupChange(action, None, live_group))

    # Desired layout: the file's layout, then extras in their current order
    extra_indices = [i for i, c in enumerate(questions) if c.action == "extra"]
    extra_group_names = {g.name for g in groups if g.action == "extra"}
    order = file_layout(spec)
    index_by_live_id = {
        change.live.id: i
        for i, change in enumerate(questions)
        if change.live is not None
    }
    for kind, entry_id in canvas_layout(state.questions, state.groups):
        if kind == "question":
            index = index_by_live_id[entry_id]
            if index in extra_indices:
                order.append(("question", index))
        elif group_name_by_id[entry_id] in extra_group_names:
            order.append(("group", group_name_by_id[entry_id]))

    members = group_members(spec)
    for index in extra_indices:
        group_name = questions[index].group
        if group_name:
            members.setdefault(group_name, []).append(index)

    return QuestionPlan(
        quiz_id=state.quiz.id,
        quiz_type=quiz_type,
        questions=questions,
        groups=groups,
        order=order,
        group_members=members,
        order_changed=_order_changed(order, questions, groups, state),
        reordered_groups=_reordered_groups(members, questions, groups, state),
        student_attempts=state.student_attempts,
    )


def _live_id(change: QuestionChange | GroupChange) -> int | None:
    return change.live.id if change.live is not None else None


def _order_changed(
    order: list[tuple[str, int | str]],
    questions: list[QuestionChange],
    groups: list[GroupChange],
    state: QuizState,
) -> bool:
    """True when the desired top-level layout differs from Canvas's."""
    group_by_name = {g.name: g for g in groups}
    desired: list[tuple[str, int | None]] = []
    for kind, entry in order:
        if kind == "question":
            assert isinstance(entry, int)
            desired.append(("question", _live_id(questions[entry])))
        else:
            assert isinstance(entry, str)
            desired.append(("group", _live_id(group_by_name[entry])))
    if any(entry_id is None for _, entry_id in desired):
        return True
    deleted = {
        (kind, _live_id(change))
        for kind, changes in (("question", questions), ("group", groups))
        for change in changes
        if change.action == "delete"
    }
    current = [
        entry
        for entry in canvas_layout(state.questions, state.groups)
        if entry not in deleted
    ]
    return desired != current


def _reordered_groups(
    members: dict[str, list[int]],
    questions: list[QuestionChange],
    groups: list[GroupChange],
    state: QuizState,
) -> list[str]:
    """Groups whose members or member order change, plus every new group."""
    deleted_ids = {
        change.live.id
        for change in questions
        if change.action == "delete" and change.live is not None
    }
    reordered: list[str] = []
    for group in groups:
        if group.action == "delete":
            continue
        if group.action == "add" or group.live is None:
            reordered.append(group.name)
            continue
        live_group_id = group.live.id
        desired = [_live_id(questions[i]) for i in members.get(group.name, [])]
        current = [
            q.id
            for q in state.questions
            if q.quiz_group_id == live_group_id and q.id not in deleted_ids
        ]
        if desired != current:
            reordered.append(group.name)
    return reordered


# --- Rendering ---


def _question_line(change: QuestionChange, student_attempts: int) -> str:
    if change.spec is not None:
        text = change.spec.text
    else:
        assert change.live is not None
        text = change.live.question_text
    question_id = change.live.id if change.live is not None else ""
    snippet = strip_html(text)[:SNIPPET_LENGTH]
    line = f"{change.action:<7}question {question_id:<8}{snippet}"
    if change.action == "update":
        line += f"  ({', '.join(change.changed)})"
    moves_into_group = change.action == "update" and "group" in change.changed
    if change.group and (change.action == "add" or moves_into_group):
        line += f"  [group {change.group!r}]"
    if change.action == "extra":
        line += f"  {EXTRA_NOTE}"
    if student_attempts > 0 and "answers" in change.changed:
        line += f"  {ANSWERS_REPLACED_NOTE}"
    return line


def _group_line(change: GroupChange, quiz_type: str) -> str:
    default_points = default_question_points(quiz_type)
    if change.spec is not None:
        pick_count = change.spec.pick_count
        points = change.spec.points_per_item
    else:
        assert change.live is not None
        pick_count = change.live.pick_count
        points = change.live.question_points
    if points is None:
        points = default_points
    line = (
        f"{change.action:<7}group    {change.name!r}  "
        f"(pick {pick_count}, {points:g} pts each)"
    )
    if change.action == "update":
        line += f"  ({', '.join(change.changed)})"
    return line


def format_question_plan(plan: QuestionPlan) -> list[str]:
    """One line per question and group, each starting with its action.

    A final ``reorder  questions`` line appears when the layout changes.
    """
    lines = [_question_line(c, plan.student_attempts) for c in plan.questions]
    lines += [_group_line(g, plan.quiz_type) for g in plan.groups]
    if plan.order_changed or plan.reordered_groups:
        lines.append("reorder  questions")
    return lines


def question_plan_warning(plan: QuestionPlan) -> str | None:
    """A warning when students have finished attempts, else None."""
    if plan.student_attempts <= 0:
        return None
    return (
        f"Warning: {plan.student_attempts} finished student attempt(s) on this "
        "quiz. Canvas keeps earlier attempts on the old version of each question."
    )


def plan_summary(plan: QuestionPlan) -> str:
    """Question counts by action.

    For example ``"1 added, 1 updated, 0 deleted, 3 kept, 0 extra"``.
    """
    counts = Counter(change.action for change in plan.questions)
    return (
        f"{counts['add']} added, {counts['update']} updated, "
        f"{counts['delete']} deleted, {counts['keep']} kept, {counts['extra']} extra"
    )
