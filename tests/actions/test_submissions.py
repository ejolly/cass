"""Tests for the pure excuse and clear-late planners."""

from __future__ import annotations

__docformat__ = "google"

import pytest

from cass.actions.submissions import (
    SubmissionChange,
    SubmissionTarget,
    change_counts,
    change_rows,
    due_before_enrollment,
    group_late_warning,
    pick_students,
    plan_clear_late,
    plan_excuse,
)
from cass.apis.canvas.schema import CanvasAssignmentResponse, CanvasSubmissionResponse


def make_assignment(**fields: object) -> CanvasAssignmentResponse:
    fields.setdefault("id", 7)
    fields.setdefault("name", "HW1")
    return CanvasAssignmentResponse(**fields)  # ty: ignore[invalid-argument-type]


def submission(**fields: object) -> CanvasSubmissionResponse:
    fields.setdefault("user_id", 5)
    return CanvasSubmissionResponse(**fields)  # ty: ignore[invalid-argument-type]


def target(
    *, assignment: CanvasAssignmentResponse | None = None, **sub_fields: object
) -> SubmissionTarget:
    return SubmissionTarget(
        assignment=assignment or make_assignment(),
        submission=submission(**sub_fields),
        student_name="Ann",
    )


def test_excuse_plans_unexcused():
    (change,) = plan_excuse([target()])
    assert change.action == "excuse"


def test_excuse_skips_already_excused():
    (change,) = plan_excuse([target(excused=True)])
    assert (change.action, change.reason) == ("skip", "already excused")


def test_excuse_skips_graded():
    graded = target(score=8.0, grade="8", missing=False)
    (change,) = plan_excuse([graded])
    assert change.action == "skip"
    assert change.reason.startswith("graded (8)")
    (forced,) = plan_excuse([graded], include_graded=True)
    assert forced.action == "excuse"


def test_missing_policy_score_is_not_protected():
    (change,) = plan_excuse([target(score=0.0, grade="0", missing=True)])
    assert change.action == "excuse"


def test_clear_late_plans_late_only():
    late, on_time = plan_clear_late([target(late=True), target(late=False)])
    assert late.action == "clear-late"
    assert (on_time.action, on_time.reason) == ("skip", "not late")


def test_clear_late_skips_excused():
    (change,) = plan_clear_late(
        [target(late=False, excused=True, late_policy_status=None)]
    )
    assert change.reason == "excused; clearing late would un-excuse it"


def test_due_before_enrollment():
    enrolled = "2026-10-02T17:00:00Z"
    assert due_before_enrollment(
        submission(cached_due_date="2026-09-30T06:59:00Z"), enrolled
    )
    assert not due_before_enrollment(submission(cached_due_date=enrolled), enrolled)
    assert not due_before_enrollment(submission(cached_due_date=None), enrolled)
    assert not due_before_enrollment(
        submission(cached_due_date="2026-09-30T23:59:00-07:00"), "2026-10-01T06:59:00Z"
    )


def test_pick_students_errors_on_unknown_ids():
    subs = [submission(user_id=5), submission(user_id=9)]
    assert [s.user_id for s in pick_students(subs, [9, 5], "HW1")] == [9, 5]
    with pytest.raises(RuntimeError, match="42, 43"):
        pick_students(subs, [5, 42, 43], "HW1")


def test_change_rows():
    change = SubmissionChange(
        "excuse",
        SubmissionTarget(
            assignment=make_assignment(),
            submission=submission(cached_due_date="2026-09-30T06:59:00Z"),
            student_name="Ann",
            enrolled_at="2026-10-02T17:00:00Z",
        ),
    )
    skip = SubmissionChange("skip", target(), "already excused")
    assert change_rows([change, skip], "America/Los_Angeles") == [
        ("excuse", "HW1", "Ann (5)", "due 2026-09-29 23:59, enrolled 2026-10-02 10:00"),
        ("skip", "HW1", "Ann (5)", "already excused"),
    ]


def test_change_counts():
    changes = plan_excuse([target(), target(excused=True), target()])
    assert change_counts(changes) == {"excuse": 2, "skip": 1}


def test_group_late_warning():
    group = make_assignment(id=8, name="HW2", group_category_id=3)
    (late,) = plan_clear_late([target(assignment=group, late=True)])
    warning = group_late_warning([late])
    assert warning is not None
    assert "whole group" in warning
    assert "HW2" in warning

    individual = make_assignment(
        name="HW2", group_category_id=3, grade_group_students_individually=True
    )
    (solo,) = plan_clear_late([target(assignment=individual, late=True)])
    assert group_late_warning([solo]) is None

    (skipped,) = plan_clear_late([target(assignment=group, late=False)])
    assert group_late_warning([skipped]) is None
