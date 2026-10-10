"""Plan and apply ``excuse`` and ``clear-late`` on submissions.

The planners are pure. Only the ``targets_*`` fetchers, ``submission_rows``,
``plan_submission_command`` and ``apply_submission_changes`` talk to Canvas.
"""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..apis.canvas.times import format_when, parse_when
from .enrollments import fetch_all_enrollments, is_after, late_enrollees

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasAssignmentResponse, CanvasSubmissionResponse

SubmissionCommand = Literal["excuse", "clear-late"]


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


# --- fetching targets ---------------------------------------------------------


def _fetch_students(
    client: CanvasClient,
    assignment: CanvasAssignmentResponse,
    student_ids: Sequence[int],
) -> list[CanvasSubmissionResponse]:
    """Submissions on *assignment* (with user names) for *student_ids*, in order.

    No IDs means every submission.
    """
    submissions = client.list_submissions(assignment.id, include_user=True)
    if not student_ids:
        return submissions
    return pick_students(submissions, student_ids, assignment.name)


def _student_name(sub: CanvasSubmissionResponse) -> str:
    return sub.user.name if sub.user else str(sub.user_id)


def submission_rows(
    client: CanvasClient,
    assignment: CanvasAssignmentResponse,
    *,
    student_ids: Sequence[int] = (),
) -> list[CanvasSubmissionResponse]:
    """Submissions on *assignment* for listing.

    With *student_ids*, those students in that order; otherwise everyone,
    sorted by sortable name.

    Raises:
        RuntimeError: If any ID has no submission on the assignment.
    """
    submissions = _fetch_students(client, assignment, student_ids)
    if student_ids:
        return submissions
    return sorted(
        submissions, key=lambda sub: sub.user.sortable_name if sub.user else ""
    )


def targets_for_students(
    client: CanvasClient,
    assignment: CanvasAssignmentResponse,
    student_ids: Sequence[int],
) -> list[SubmissionTarget]:
    """Targets for explicit students on one assignment.

    Raises:
        RuntimeError: If any ID has no submission on the assignment.
    """
    return [
        SubmissionTarget(assignment, sub, _student_name(sub))
        for sub in _fetch_students(client, assignment, student_ids)
    ]


def targets_enrolled_after(
    client: CanvasClient,
    cutoff: str,
    *,
    assignment: CanvasAssignmentResponse | None = None,
) -> list[SubmissionTarget]:
    """Targets for students first enrolled after *cutoff*.

    Keeps each late enrollee's submissions on published assignments whose
    due date (the student's own) fell before they enrolled. Ordered by
    student name, due date, then assignment name.

    Raises:
        RuntimeError: If *assignment* is given and unpublished.
    """
    if assignment is not None and not assignment.published:
        raise RuntimeError(
            f"Assignment {assignment.name!r} is unpublished; "
            "--enrolled-after only changes published assignments."
        )
    late = late_enrollees(fetch_all_enrollments(client), cutoff)
    if not late:
        return []
    if assignment is not None:
        assignments = {assignment.id: assignment}
        assignment_ids: Sequence[int] = [assignment.id]
    else:
        assignments = {a.id: a for a in client.list_assignments() if a.published}
        assignment_ids = ()
    submissions = client.list_student_submissions(
        sorted(late), assignment_ids=assignment_ids
    )
    targets = []
    for sub in submissions:
        student = late.get(sub.user_id)
        known = assignments.get(sub.assignment_id)
        if student is None or known is None:
            continue
        if not due_before_enrollment(sub, student.enrolled_at):
            continue
        targets.append(SubmissionTarget(known, sub, student.name, student.enrolled_at))
    targets.sort(
        key=lambda item: (
            item.student_name,
            item.submission.cached_due_date or "",
            item.assignment.name,
        )
    )
    return targets


# --- planning a command -------------------------------------------------------


@dataclass
class SubmissionPlan:
    """Everything an ``excuse`` or ``clear-late`` command shows and applies."""

    changes: list[SubmissionChange]
    rows: list[tuple[str, str, str, str]]
    counts: dict[str, int]
    warnings: list[str]


def check_target_options(
    *, has_assignment: bool, student_ids: Sequence[int], enrolled_after: str
) -> None:
    """Require exactly one of *student_ids* and *enrolled_after*.

    Raises:
        ValueError: On a missing or conflicting choice, or students without
            an assignment.
    """
    if not student_ids and not enrolled_after:
        raise ValueError("Give --student or --enrolled-after.")
    if student_ids and enrolled_after:
        raise ValueError("--student and --enrolled-after cannot be combined.")
    if student_ids and not has_assignment:
        raise ValueError("--student needs an ASSIGNMENT.")


def _explicit_target_warnings(assignment: CanvasAssignmentResponse) -> list[str]:
    """Warnings for an explicitly targeted assignment outside the usual scope."""
    warnings = []
    if not assignment.published:
        warnings.append(f"Assignment {assignment.name!r} is unpublished.")
    if assignment.due_at is None:
        warnings.append(f"Assignment {assignment.name!r} has no due date.")
    return warnings


def plan_submission_command(
    client: CanvasClient,
    kind: SubmissionCommand,
    *,
    assignment: CanvasAssignmentResponse | None,
    student_ids: Sequence[int],
    enrolled_after: str,
    include_graded: bool,
) -> SubmissionPlan:
    """Select targets and plan an ``excuse`` or ``clear-late`` command.

    Args:
        client: Canvas client.
        kind: The command.
        assignment: The assignment to limit to; required with *student_ids*.
        student_ids: Explicit students (``--student``).
        enrolled_after: A user-entered date or time (``--enrolled-after``),
            read in the course time zone.
        include_graded: Excuse graded submissions too (``excuse`` only).

    Raises:
        ValueError: On a bad combination of target options (before any request).
        RuntimeError: On an unknown student, an unparseable date, or an
            unpublished assignment with ``--enrolled-after``.
    """
    check_target_options(
        has_assignment=assignment is not None,
        student_ids=student_ids,
        enrolled_after=enrolled_after,
    )
    warnings: list[str] = []
    if student_ids and assignment is not None:
        targets = targets_for_students(client, assignment, student_ids)
        warnings.extend(_explicit_target_warnings(assignment))
    else:
        cutoff = parse_when(enrolled_after, client.time_zone)
        targets = targets_enrolled_after(client, cutoff, assignment=assignment)
    if kind == "excuse":
        changes = plan_excuse(targets, include_graded=include_graded)
    else:
        changes = plan_clear_late(targets)
        group_warning = group_late_warning(changes)
        if group_warning:
            warnings.append(group_warning)
    return SubmissionPlan(
        changes=changes,
        rows=change_rows(changes, client.time_zone),
        counts=change_counts(changes),
        warnings=warnings,
    )


# --- applying -----------------------------------------------------------------


class SubmissionApplyError(RuntimeError):
    """A request failed while applying submission changes.

    Attributes:
        applied: Descriptions of the changes sent before the failure.
    """

    def __init__(self, cause: BaseException, applied: list[str]):
        self.applied = list(applied)
        if applied:
            done = "\n".join(f"  {step}" for step in applied)
            message = f"{cause}\nStopped; already sent:\n{done}"
        else:
            message = f"{cause}\nStopped before any change was sent."
        super().__init__(message)


def apply_submission_changes(
    client: CanvasClient, changes: list[SubmissionChange]
) -> list[str]:
    """Send each non-skip change, in order, one request each.

    Returns:
        A description per change sent, such as ``"excuse HW1: Ann"``.

    Raises:
        SubmissionApplyError: When a request fails; it lists the changes sent
            before the failure. Nothing is rolled back.
    """
    applied: list[str] = []
    try:
        for change in changes:
            if change.action == "skip":
                continue
            assignment_id = change.target.assignment.id
            user_id = change.target.submission.user_id
            if change.action == "excuse":
                client.update_submission(assignment_id, user_id, excuse=True)
            else:
                client.update_submission(
                    assignment_id, user_id, late_policy_status="none"
                )
            applied.append(
                f"{change.action} {change.target.assignment.name}: "
                f"{change.target.student_name}"
            )
    except Exception as exc:
        raise SubmissionApplyError(exc, applied) from exc
    return applied
