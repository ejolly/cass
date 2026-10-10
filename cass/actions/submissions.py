"""Pure planners for ``excuse`` and ``clear-late`` on submissions.

Nothing here talks to Canvas: callers fetch submissions, build
``SubmissionTarget`` lists, and render or apply the resulting changes.
"""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..apis.canvas.times import format_when
from .enrollments import is_after

if TYPE_CHECKING:
    from ..apis.canvas.schema import CanvasAssignmentResponse, CanvasSubmissionResponse


@dataclass
class SubmissionTarget:
    """One student's submission on one assignment, considered for a change."""

    assignment: CanvasAssignmentResponse
    submission: CanvasSubmissionResponse
    student_name: str
    enrolled_at: str | None = None  # set only in --enrolled-after mode


@dataclass
class SubmissionChange:
    """A planned action for a target: ``excuse``, ``clear-late`` or ``skip``."""

    action: str
    target: SubmissionTarget
    reason: str = ""  # skip reason


def is_protected_grade(sub: CanvasSubmissionResponse) -> bool:
    """Whether the submission holds a score a teacher could have entered.

    Canvas's missing-submission policy writes its score with ``missing`` set
    and no ``grader_id``; those are what late enrollees need excused. A
    teacher's grade, including partial credit on a missing submission, has a
    grader and stays protected.
    """
    is_policy_score = sub.missing and sub.grader_id is None
    return sub.score is not None and not is_policy_score


def due_before_enrollment(sub: CanvasSubmissionResponse, enrolled_at: str) -> bool:
    """Whether the student's own due date fell strictly before they enrolled."""
    if sub.cached_due_date is None:
        return False
    return is_after(enrolled_at, sub.cached_due_date)


def pick_students(
    submissions: list[CanvasSubmissionResponse],
    student_ids: Sequence[int],
    assignment_name: str,
) -> list[CanvasSubmissionResponse]:
    """Select submissions for *student_ids*, in that order.

    Raises:
        RuntimeError: If any ID has no submission on the assignment.
    """
    by_user = {sub.user_id: sub for sub in submissions}
    unknown = [student_id for student_id in student_ids if student_id not in by_user]
    if unknown:
        ids = ", ".join(str(student_id) for student_id in unknown)
        raise RuntimeError(
            f"No submission on {assignment_name!r} for student ID(s): {ids}"
        )
    return [by_user[student_id] for student_id in student_ids]


def plan_excuse(
    targets: list[SubmissionTarget], *, include_graded: bool = False
) -> list[SubmissionChange]:
    """Plan excusing each target, skipping excused and (by default) graded ones."""
    changes = []
    for item in targets:
        sub = item.submission
        if sub.excused is True:
            changes.append(SubmissionChange("skip", item, "already excused"))
        elif is_protected_grade(sub) and not include_graded:
            reason = (
                f"graded ({sub.grade}); "
                "--include-graded excuses it and clears the grade"
            )
            changes.append(SubmissionChange("skip", item, reason))
        else:
            changes.append(SubmissionChange("excuse", item))
    return changes


def plan_clear_late(targets: list[SubmissionTarget]) -> list[SubmissionChange]:
    """Plan clearing the late status of late targets.

    Excused submissions are skipped: setting a late status would un-excuse them.
    """
    changes = []
    for item in targets:
        if item.submission.excused is True:
            reason = "excused; clearing late would un-excuse it"
            changes.append(SubmissionChange("skip", item, reason))
        elif not item.submission.late:
            changes.append(SubmissionChange("skip", item, "not late"))
        else:
            changes.append(SubmissionChange("clear-late", item))
    return changes


def change_rows(
    changes: list[SubmissionChange], tz: str
) -> list[tuple[str, str, str, str]]:
    """Table rows of (action, assignment, student, detail) for display."""
    rows = []
    for change in changes:
        item = change.target
        if change.action == "skip":
            detail = change.reason
        else:
            due = item.submission.cached_due_date
            detail = f"due {format_when(due, tz)}" if due else ""
            if due and item.enrolled_at:
                detail += f", enrolled {format_when(item.enrolled_at, tz)}"
        student = f"{item.student_name} ({item.submission.user_id})"
        rows.append((change.action, item.assignment.name, student, detail))
    return rows


def change_counts(changes: list[SubmissionChange]) -> dict[str, int]:
    """Count changes by action, in first-seen order."""
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.action] = counts.get(change.action, 0) + 1
    return counts


def group_late_warning(changes: list[SubmissionChange]) -> str | None:
    """Warn when clear-late hits group assignments graded as a whole group."""
    names = []
    for change in changes:
        assignment = change.target.assignment
        is_group = (
            assignment.group_category_id is not None
            and not assignment.grade_group_students_individually
        )
        if change.action == "clear-late" and is_group and assignment.name not in names:
            names.append(assignment.name)
    if not names:
        return None
    return (
        "Canvas applies clear-late to the whole group on group assignments: "
        + ", ".join(names)
    )
