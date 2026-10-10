"""Question planning — compare a quiz file's questions with a live quiz.

``plan_quiz_questions`` matches each file question to a live question (by id,
then unique name, then relative order) and records what must change. It does
no I/O. ``apply_question_plan`` then sends the plan to Canvas, the only
function here that calls the client.
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
    answer_form_fields,
    canvas_layout,
    default_question_points,
    file_layout,
    group_form_fields,
    group_members,
    group_name_of,
    groups_by_name,
    is_default_question_name,
    question_form_fields,
    strip_html,
)

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import (
        CanvasQuizAnswer,
        CanvasQuizGroup,
        CanvasQuizQuestion,
    )

QUESTION_FIELDS = ("text", "name", "type", "points", "answers", "group")
GROUP_FIELDS = ("pick_count", "points_per_item")
GROUP_CANVAS_FIELDS = {"pick_count": "pick_count", "points_per_item": "question_points"}

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
        # An empty or Canvas-default file name keeps whatever name Canvas has.
        "name": bool(_match_name(question.name))
        and question.name != live.question_name,
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
    live_groups = groups_by_name(state.groups, state.quiz.title)
    group_name_by_id = {g.id: g.name for g in state.groups}

    def current_group(question: CanvasQuizQuestion) -> str:
        return group_name_of(question, state.groups)

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
        # Only matters without prune: extras left in the group keep it alive.
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
    """True when the layout differs from Canvas's or a question changes group.

    Canvas ignores ``quiz_group_id: null`` on update; only the quiz-level
    reorder takes a question out of a group, so any group change forces it.
    """
    if any("group" in change.changed for change in questions):
        return True
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
        desired = [_live_id(questions[i]) for i in members.get(group.name, [])]
        if not desired:
            continue  # nothing to reorder in a group left empty
        live_group_id = group.live.id
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
    """Question counts by action, plus group changes when there are any.

    For example ``"1 added, 1 updated, 0 deleted, 3 kept, 0 extra"`` or
    ``"0 added, 0 updated, 0 deleted, 3 kept, 0 extra; groups: 1 updated"``.
    """
    counts = Counter(change.action for change in plan.questions)
    summary = (
        f"{counts['add']} added, {counts['update']} updated, "
        f"{counts['delete']} deleted, {counts['keep']} kept, {counts['extra']} extra"
    )
    group_counts = Counter(change.action for change in plan.groups)
    group_parts = [
        f"{group_counts[action]} {label}"
        for action, label in (
            ("add", "added"),
            ("update", "updated"),
            ("delete", "deleted"),
        )
        if group_counts[action]
    ]
    if group_parts:
        summary += f"; groups: {', '.join(group_parts)}"
    return summary


# --- Applying ---


class QuestionApplyError(RuntimeError):
    """A plan stopped part-way; ``applied`` lists the steps that succeeded."""

    def __init__(self, cause: object, applied: list[str]):
        if applied:
            steps = "\n".join(f"  {step}" for step in applied)
            message = f"{cause}\nStopped; applied before the failure:\n{steps}"
        else:
            message = f"{cause}\nStopped before any change was applied."
        super().__init__(message)
        self.applied = applied


def question_update_fields(
    change: QuestionChange, quiz_type: str, group_id: int | None
) -> dict[str, object]:
    """Canvas fields to send for an "update" change: the whole question.

    Canvas fills every field an update leaves out from a copy of the question
    saved when it was created, so a partial update would undo earlier edits.
    Each update therefore sends text, name, type, points and answers.

    Answers keep their Canvas ids: unchanged answers go back as the live
    answers; changed ones are the file's answers, each reusing the id of a
    live answer with the same text.

    Args:
        change: An update change; its spec holds the desired values.
        quiz_type: Canvas quiz type, which decides default points.
        group_id: Canvas id of the desired group, or None for no group. Sent
            only when the question moves into a group; Canvas ignores
            ``quiz_group_id: null``, so the quiz-level reorder in
            ``apply_question_plan`` takes a question out of its group.
    """
    assert change.spec is not None
    assert change.live is not None
    form = question_form_fields(change.spec, quiz_type)
    name = change.spec.name if _match_name(change.spec.name) else ""
    fields: dict[str, object] = {
        "question_text": form["question_text"],
        "question_name": name or change.live.question_name,
        "question_type": form["question_type"],
        "points_possible": form["points_possible"],
    }
    if "answers" in change.changed:
        file_answers = answer_form_fields(change.spec.answers)
        fields["answers"] = _answers_with_live_ids(file_answers, change.live)
    else:
        fields["answers"] = [_live_answer_fields(a) for a in change.live.answers]
    if "group" in change.changed and group_id is not None:
        fields["quiz_group_id"] = group_id
    return fields


def _live_answer_fields(answer: CanvasQuizAnswer) -> dict[str, object]:
    """A live answer as Canvas update fields, so resending it changes nothing."""
    fields: dict[str, object] = {
        "id": answer.id,
        "answer_text": answer.text,
        "answer_weight": answer.weight,
    }
    if answer.html:
        fields["answer_html"] = answer.html
    if answer.comments:
        fields["answer_comment"] = answer.comments
    if answer.comments_html:
        fields["answer_comment_html"] = answer.comments_html
    return fields


def _answers_with_live_ids(
    file_answers: list[dict[str, object]], live: CanvasQuizQuestion
) -> list[dict[str, object]]:
    """*file_answers*, each with the id of an unused live answer of the same text."""
    unused_ids: dict[str, list[int]] = {}
    for answer in live.answers:
        unused_ids.setdefault(answer.text, []).append(answer.id)
    with_ids: list[dict[str, object]] = []
    for answer in file_answers:
        ids = unused_ids.get(str(answer["answer_text"]))
        with_ids.append({"id": ids.pop(0), **answer} if ids else answer)
    return with_ids


def apply_question_plan(
    client: CanvasClient, quiz_id: int, plan: QuestionPlan
) -> list[str]:
    """Send *plan* to Canvas in a fixed order and re-save the quiz.

    Order:

    1. Create groups.
    2. Add, update and delete questions.
    3. Update groups.
    4. Reorder the quiz, whenever the plan changes anything. This keeps
       top-level positions contiguous, which ``canvas_layout`` relies on, and
       takes questions out of groups, since Canvas ignores
       ``quiz_group_id: null`` on update.
    5. Reorder groups.
    6. Delete groups. Canvas deletes a group's questions with the group, so
       the questions the file keeps must already be out of it.
    7. Re-save the quiz (only if anything was sent).

    Returns:
        A description of each step applied.

    Raises:
        QuestionApplyError: A request failed. Nothing after it was sent; the
            error lists the steps that had already succeeded.
    """
    applied: list[str] = []
    try:
        _apply_steps(client, quiz_id, plan, applied)
        if applied:
            client.resave_quiz(quiz_id)
            applied.append("re-save quiz")
    except Exception as error:
        raise QuestionApplyError(error, applied) from error
    return applied


def _apply_steps(
    client: CanvasClient, quiz_id: int, plan: QuestionPlan, applied: list[str]
) -> None:
    """Steps 1-6 of ``apply_question_plan``; records each finished step."""
    # 1. New groups (start the name -> id map from groups already on Canvas)
    group_ids = {
        g.name: g.live.id
        for g in plan.groups
        if g.live is not None and g.action != "delete"
    }
    for group in plan.groups:
        if group.action == "add":
            assert group.spec is not None
            fields = group_form_fields(group.spec, plan.quiz_type)
            group_ids[group.name] = client.create_question_group(quiz_id, fields).id
            applied.append(f"create group {group.name!r}")

    # 2. Questions, in plan order
    question_ids: dict[int, int] = {}
    for index, change in enumerate(plan.questions):
        if change.live is not None:
            question_ids[index] = change.live.id
        if change.action == "add":
            assert change.spec is not None
            created = client.create_quiz_question(
                quiz_id,
                change.spec,
                position=index + 1,
                quiz_type=plan.quiz_type,
                quiz_group_id=_group_id(group_ids, change.group),
            )
            question_ids[index] = created.id
            applied.append(f"create question {index + 1}")
        elif change.action == "update":
            assert change.live is not None
            fields = question_update_fields(
                change, plan.quiz_type, _group_id(group_ids, change.group)
            )
            client.update_quiz_question(quiz_id, change.live.id, fields)
            applied.append(
                f"update question {change.live.id} ({', '.join(change.changed)})"
            )
        elif change.action == "delete":
            assert change.live is not None
            client.delete_quiz_question(quiz_id, change.live.id)
            applied.append(f"delete question {change.live.id}")

    # 3. Group settings
    for group in plan.groups:
        if group.action == "update":
            assert group.spec is not None
            assert group.live is not None
            form = group_form_fields(group.spec, plan.quiz_type)
            canvas_names = [GROUP_CANVAS_FIELDS[name] for name in group.changed]
            fields = {name: form[name] for name in canvas_names}
            client.update_question_group(quiz_id, group.live.id, fields)
            applied.append(f"update group {group.name!r}")

    # 4. Top-level order (also takes questions out of groups)
    # Sent on every apply, not only when the layout changes: Canvas reports no
    # question positions, and contiguous positions keep canvas_layout exact.
    if plan.has_changes:
        items: list[tuple[str, int]] = []
        for kind, entry in plan.order:
            if kind == "question":
                assert isinstance(entry, int)
                items.append(("question", question_ids[entry]))
            else:
                assert isinstance(entry, str)
                items.append(("group", group_ids[entry]))
        client.reorder_quiz(quiz_id, items)
        applied.append("reorder quiz")

    # 5. Order inside groups
    for name in plan.reordered_groups:
        members = [question_ids[i] for i in plan.group_members[name]]
        client.reorder_question_group(quiz_id, group_ids[name], members)
        applied.append(f"reorder group {name!r}")

    # 6. Group deletes, last: Canvas deletes a group's questions with it
    for group in plan.groups:
        if group.action == "delete":
            assert group.live is not None
            client.delete_question_group(quiz_id, group.live.id)
            applied.append(f"delete group {group.name!r}")


def _group_id(group_ids: dict[str, int], name: str) -> int | None:
    """Canvas id of group *name*; None for no group.

    Raises:
        RuntimeError: The group has no Canvas id.
    """
    if not name:
        return None
    if name not in group_ids:
        raise RuntimeError(f"Question group {name!r} has no Canvas id.")
    return group_ids[name]
