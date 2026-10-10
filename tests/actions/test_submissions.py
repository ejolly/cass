"""Tests for excuse and clear-late planning, target fetching and applying."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

import httpx
import msgspec
import pytest

from cass.actions.submissions import (
    SubmissionApplyError,
    SubmissionChange,
    SubmissionPlan,
    SubmissionTarget,
    apply_submission_changes,
    change_counts,
    change_rows,
    due_before_enrollment,
    pick_students,
    plan_clear_late,
    plan_excuse,
    plan_submission_command,
    submission_rows,
    targets_enrolled_after,
    targets_for_students,
)
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.dry_run import format_plan
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasEnrollment,
    CanvasStudentResponse,
    CanvasSubmissionResponse,
)


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
    policy_zero = target(score=0.0, grade="0", missing=True, grader_id=None)
    (change,) = plan_excuse([policy_zero])
    assert change.action == "excuse"


def test_teacher_partial_credit_on_missing_is_protected():
    partial = target(score=4.0, grade="4", missing=True, grader_id=99)
    (change,) = plan_excuse([partial])
    assert change.action == "skip"
    assert change.reason.startswith("graded (4)")
    (forced,) = plan_excuse([partial], include_graded=True)
    assert forced.action == "excuse"


def test_teacher_zero_is_protected():
    (change,) = plan_excuse([target(score=0.0, grade="0", missing=False, grader_id=99)])
    assert change.action == "skip"
    assert change.reason.startswith("graded (0)")


def test_include_graded_still_skips_excused():
    (change,) = plan_excuse([target(excused=True, score=None)], include_graded=True)
    assert (change.action, change.reason) == ("skip", "already excused")


def test_clear_late_plans_late_only():
    late, on_time = plan_clear_late([target(late=True), target(late=False)])
    assert late.action == "clear-late"
    assert (on_time.action, on_time.reason) == ("skip", "not late")


@pytest.mark.parametrize("status", ["none", "missing"])
def test_clear_late_skips_non_late_status(status):
    (change,) = plan_clear_late([target(late=False, late_policy_status=status)])
    assert (change.action, change.reason) == ("skip", "not late")


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


def test_pick_students_drops_repeated_ids():
    subs = [submission(user_id=5), submission(user_id=9)]
    assert [s.user_id for s in pick_students(subs, [9, 5, 9], "HW1")] == [9, 5]


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


def test_change_rows_without_due_date_or_enrollment():
    no_due = SubmissionChange("excuse", target())
    due_only = SubmissionChange(
        "excuse", target(cached_due_date="2026-09-30T06:59:00Z")
    )
    assert change_rows([no_due, due_only], "UTC") == [
        ("excuse", "HW1", "Ann (5)", ""),
        ("excuse", "HW1", "Ann (5)", "due 2026-09-30 06:59"),
    ]


def test_change_rows_show_submitted_date_and_points_restored():
    excuse = SubmissionChange(
        "excuse", target(cached_due_date=None, submitted_at="2026-10-03T17:00:00Z")
    )
    clear = SubmissionChange(
        "clear-late",
        target(cached_due_date="2026-09-30T06:59:00Z", late=True, points_deducted=2.5),
    )
    no_penalty = SubmissionChange("clear-late", target(late=True, points_deducted=0))
    resubmitted = SubmissionChange(
        "clear-late",
        target(
            cached_due_date=None,
            late=True,
            points_deducted=2.5,
            grade_matches_current_submission=False,
        ),
    )
    rows = change_rows([excuse, clear, no_penalty, resubmitted], LA)
    assert [row[3] for row in rows] == [
        "submitted 2026-10-03 10:00",
        "due 2026-09-29 23:59, 2.5 pts restored",
        "",
        "2.5 pts deducted, kept until regraded",
    ]


def test_change_counts():
    changes = plan_excuse([target(), target(excused=True), target()])
    assert change_counts(changes) == {"excuse": 2, "skip": 1}


def test_clear_late_skips_group_graded():
    group = make_assignment(id=8, name="HW2", group_category_id=3)
    (change,) = plan_clear_late([target(assignment=group, late=True, excused=True)])
    assert (change.action, change.reason) == (
        "skip",
        "graded as a group: Canvas would change every group member",
    )

    individual = make_assignment(
        name="HW2", group_category_id=3, grade_group_students_individually=True
    )
    (solo,) = plan_clear_late([target(assignment=individual, late=True)])
    assert solo.action == "clear-late"


def test_excuse_on_group_assignment_is_per_student():
    group = make_assignment(id=8, name="HW2", group_category_id=3)
    (change,) = plan_excuse([target(assignment=group)])
    assert change.action == "excuse"


# --- fetching targets ---------------------------------------------------------

LA = "America/Los_Angeles"


def student(user_id: int, name: str, sortable: str = "") -> CanvasStudentResponse:
    return CanvasStudentResponse(id=user_id, name=name, sortable_name=sortable)


def enrollment(user_id: int, name: str, created_at: str) -> CanvasEnrollment:
    return CanvasEnrollment(
        id=100 + user_id,
        user_id=user_id,
        type="StudentEnrollment",
        enrollment_state="active",
        created_at=created_at,
        user=student(user_id, name),
    )


def fetch_client(**returns: object) -> MagicMock:
    client = MagicMock()
    client.time_zone = LA
    for method, value in returns.items():
        getattr(client, method).return_value = value
    return client


HW1 = make_assignment(id=7, name="HW1", published=True, due_at="2026-09-30T06:59:00Z")
HW2 = make_assignment(id=8, name="HW2", published=True, due_at="2026-10-09T06:59:00Z")
HW3 = make_assignment(id=9, name="HW3", published=True)
ANN_ENROLLED = "2026-10-02T17:00:00Z"
ANN_SUBS = [
    submission(assignment_id=7, cached_due_date="2026-09-30T06:59:00Z"),
    submission(assignment_id=8, cached_due_date="2026-10-09T06:59:00Z"),
    submission(assignment_id=9, cached_due_date=None),
]
ENROLLMENTS = [
    enrollment(5, "Ann", ANN_ENROLLED),
    enrollment(6, "Ben", "2026-09-01T00:00:00Z"),
]


def test_targets_for_students_uses_included_user_names():
    client = fetch_client(
        list_submissions=[
            submission(user_id=5, user=student(5, "Ann")),
            submission(user_id=6, user=student(6, "Ben")),
        ]
    )
    targets = targets_for_students(client, HW1, [5])
    client.list_submissions.assert_called_once_with(7, include_user=True)
    assert [t.student_name for t in targets] == ["Ann"]


def test_targets_for_students_falls_back_to_id():
    client = fetch_client(
        list_submissions=[
            submission(user_id=5),
            submission(user_id=6, user=student(6, "")),
        ]
    )
    targets = targets_for_students(client, HW1, [5, 6])
    assert [t.student_name for t in targets] == ["5", "6"]


def test_targets_enrolled_after_selects_due_before_enrollment():
    client = fetch_client(
        list_enrollments=ENROLLMENTS,
        list_assignments=[HW1, HW2, HW3],
        list_student_submissions=ANN_SUBS,
    )
    targets = targets_enrolled_after(client, "2026-10-01T00:00:00-07:00")
    client.list_student_submissions.assert_called_once_with([5], assignment_ids=())
    assert [(t.assignment.name, t.student_name, t.enrolled_at) for t in targets] == [
        ("HW1", "Ann", ANN_ENROLLED)
    ]


def test_targets_enrolled_after_skips_unpublished_assignments():
    hidden = make_assignment(id=7, name="HW1", published=False)
    client = fetch_client(
        list_enrollments=ENROLLMENTS,
        list_assignments=[hidden],
        list_student_submissions=ANN_SUBS[:1],
    )
    assert targets_enrolled_after(client, "2026-10-01T00:00:00-07:00") == []


def test_targets_enrolled_after_orders_by_student_due_and_name():
    zed_enrolled = "2026-10-05T00:00:00Z"
    client = fetch_client(
        list_enrollments=[*ENROLLMENTS, enrollment(4, "Zed", zed_enrolled)],
        list_assignments=[HW1, HW2],
        list_student_submissions=[
            submission(user_id=4, assignment_id=8, cached_due_date="2026-10-01T00:00Z"),
            submission(user_id=4, assignment_id=7, cached_due_date="2026-10-01T00:00Z"),
            submission(user_id=5, assignment_id=7, cached_due_date="2026-09-30T06:59Z"),
        ],
    )
    targets = targets_enrolled_after(client, "2026-10-01T00:00:00-07:00")
    assert [(t.student_name, t.assignment.name) for t in targets] == [
        ("Ann", "HW1"),
        ("Zed", "HW1"),
        ("Zed", "HW2"),
    ]


def test_targets_enrolled_after_breaks_name_ties_by_user_id():
    client = fetch_client(
        list_enrollments=[
            enrollment(9, "Ann", ANN_ENROLLED),
            enrollment(5, "Ann", ANN_ENROLLED),
        ],
        list_assignments=[HW1, HW2],
        list_student_submissions=[
            submission(user_id=9, assignment_id=7, cached_due_date="2026-09-30T06:59Z"),
            submission(user_id=5, assignment_id=8, cached_due_date="2026-10-01T00:00Z"),
            submission(user_id=5, assignment_id=7, cached_due_date="2026-09-30T06:59Z"),
        ],
    )
    targets = targets_enrolled_after(client, "2026-10-01T00:00:00-07:00")
    assert [(t.submission.user_id, t.assignment.name) for t in targets] == [
        (5, "HW1"),
        (5, "HW2"),
        (9, "HW1"),
    ]


def test_targets_enrolled_after_with_assignment_narrows():
    client = fetch_client(
        list_enrollments=ENROLLMENTS, list_student_submissions=ANN_SUBS[:1]
    )
    targets = targets_enrolled_after(
        client, "2026-10-01T00:00:00-07:00", assignment=HW1
    )
    client.list_student_submissions.assert_called_once_with([5], assignment_ids=[7])
    client.list_assignments.assert_not_called()
    assert [t.assignment.name for t in targets] == ["HW1"]


def test_targets_enrolled_after_rejects_unpublished_assignment():
    hidden = make_assignment(id=7, name="HW1", published=False)
    client = fetch_client(list_enrollments=ENROLLMENTS)
    with pytest.raises(RuntimeError, match=r"HW1.*unpublished"):
        targets_enrolled_after(client, "2026-10-01T00:00:00-07:00", assignment=hidden)
    assert client.method_calls == []


def test_targets_enrolled_after_without_late_students_stops():
    client = fetch_client(list_enrollments=ENROLLMENTS)
    assert targets_enrolled_after(client, "2026-10-30T00:00:00-07:00") == []
    client.list_assignments.assert_not_called()
    client.list_student_submissions.assert_not_called()


def test_submission_rows_sorts_all_by_sortable_name():
    client = fetch_client(
        list_submissions=[
            submission(user_id=6, user=student(6, "Ben", "Bee, Ben")),
            submission(user_id=5, user=student(5, "Ann", "Aye, Ann")),
        ]
    )
    rows = submission_rows(client, HW1)
    client.list_submissions.assert_called_once_with(7, include_user=True)
    assert [s.user_id for s in rows] == [5, 6]


def test_submission_rows_breaks_sortable_name_ties_by_user_id():
    client = fetch_client(
        list_submissions=[
            submission(user_id=9, user=student(9, "Ann", "Aye, Ann")),
            submission(user_id=5, user=student(5, "Ann", "Aye, Ann")),
        ]
    )
    assert [s.user_id for s in submission_rows(client, HW1)] == [5, 9]


def test_submission_rows_picks_students_in_order():
    client = fetch_client(
        list_submissions=[submission(user_id=5), submission(user_id=6)]
    )
    assert [s.user_id for s in submission_rows(client, HW1, student_ids=[6])] == [6]
    with pytest.raises(RuntimeError, match="42"):
        submission_rows(client, HW1, student_ids=[42])


# --- planning a command -------------------------------------------------------


@pytest.mark.parametrize(
    ("assignment", "student_ids", "enrolled_after", "message"),
    [
        (HW1, [], "", "Give --student or --enrolled-after"),
        (HW1, [5], "2026-10-01", "cannot be combined"),
        (None, [5], "", "--student needs an ASSIGNMENT"),
    ],
)
def test_plan_command_rejects_bad_target_options(
    assignment, student_ids, enrolled_after, message
):
    client = fetch_client()
    with pytest.raises(ValueError, match=message):
        plan_submission_command(
            client,
            "excuse",
            assignment=assignment,
            student_ids=student_ids,
            enrolled_after=enrolled_after,
            include_graded=False,
        )
    assert client.method_calls == []


def test_plan_command_rejects_bad_date_before_any_request():
    client = fetch_client()
    with pytest.raises(RuntimeError, match="Unrecognized time"):
        plan_submission_command(
            client,
            "excuse",
            assignment=None,
            student_ids=[],
            enrolled_after="next tuesday",
            include_graded=False,
        )
    assert client.method_calls == []


def test_plan_command_excuse_students():
    due = "2026-09-30T06:59:00Z"
    client = fetch_client(
        list_submissions=[
            submission(user_id=5, user=student(5, "Ann"), cached_due_date=due),
            submission(
                user_id=6, user=student(6, "Ben"), excused=True, cached_due_date=due
            ),
        ]
    )
    plan = plan_submission_command(
        client,
        "excuse",
        assignment=HW1,
        student_ids=[5, 6],
        enrolled_after="",
        include_graded=False,
    )
    assert [c.action for c in plan.changes] == ["excuse", "skip"]
    assert plan.counts == {"excuse": 1, "skip": 1}
    assert plan.rows[0][:3] == ("excuse", "HW1", "Ann (5)")
    assert plan.warnings == []


def test_plan_command_include_graded():
    client = fetch_client(
        list_submissions=[submission(user_id=6, score=8.0, grade="8", grader_id=1)]
    )

    def plan(include_graded: bool) -> SubmissionPlan:
        return plan_submission_command(
            client,
            "excuse",
            assignment=HW1,
            student_ids=[6],
            enrolled_after="",
            include_graded=include_graded,
        )

    skipped, forced = plan(False), plan(True)
    assert [c.action for c in skipped.changes] == ["skip"]
    assert [c.action for c in forced.changes] == ["excuse"]


def test_plan_command_warns_on_explicit_unpublished_undated_assignment():
    draft = make_assignment(id=7, name="HW1", published=False, due_at=None)
    client = fetch_client(list_submissions=[submission(user_id=5)])
    plan = plan_submission_command(
        client,
        "excuse",
        assignment=draft,
        student_ids=[5],
        enrolled_after="",
        include_graded=False,
    )
    assert [c.action for c in plan.changes] == ["excuse"]
    assert len(plan.warnings) == 2
    assert "unpublished" in plan.warnings[0]
    assert plan.warnings[1] == "Assignment 'HW1' has no due date for: 5 (5)"


def test_plan_command_no_due_date_warning_uses_student_due_dates():
    # Dated only through an override: due_at is null, the student's date is not.
    dated_by_override = make_assignment(id=7, name="HW1", published=True)
    client = fetch_client(
        list_submissions=[submission(user_id=5, cached_due_date="2026-09-30T06:59Z")]
    )
    plan = plan_submission_command(
        client,
        "excuse",
        assignment=dated_by_override,
        student_ids=[5],
        enrolled_after="",
        include_graded=False,
    )
    assert plan.warnings == []


def test_plan_command_clear_late_skips_group_assignment():
    group = make_assignment(
        id=8,
        name="HW2",
        published=True,
        due_at="2026-10-09T06:59:00Z",
        group_category_id=3,
    )
    client = fetch_client(
        list_submissions=[
            submission(user_id=7, late=True, cached_due_date="2026-10-09T06:59:00Z")
        ]
    )
    plan = plan_submission_command(
        client,
        "clear-late",
        assignment=group,
        student_ids=[7],
        enrolled_after="",
        include_graded=False,
    )
    assert [c.action for c in plan.changes] == ["skip"]
    assert plan.rows[0][3] == (
        "graded as a group: Canvas would change every group member"
    )
    assert plan.warnings == []


def test_plan_command_enrolled_after_parses_date_in_course_time_zone():
    client = fetch_client(
        list_enrollments=[enrollment(5, "Ann", "2026-10-01T06:59:00Z")],
        list_assignments=[HW1],
        list_student_submissions=ANN_SUBS[:1],
    )
    # Midnight Oct 1 in Los Angeles is 07:00Z, so a 06:59Z enrollment is before it.
    plan = plan_submission_command(
        client,
        "excuse",
        assignment=None,
        student_ids=[],
        enrolled_after="2026-10-01",
        include_graded=False,
    )
    assert plan.changes == []
    client.list_student_submissions.assert_not_called()


def test_plan_command_enrolled_after():
    client = fetch_client(
        list_enrollments=ENROLLMENTS,
        list_assignments=[HW1, HW2, HW3],
        list_student_submissions=ANN_SUBS,
    )
    plan = plan_submission_command(
        client,
        "excuse",
        assignment=None,
        student_ids=[],
        enrolled_after="2026-10-01",
        include_graded=False,
    )
    assert [(c.action, c.target.assignment.name) for c in plan.changes] == [
        ("excuse", "HW1")
    ]
    assert "enrolled 2026-10-02 10:00" in plan.rows[0][3]
    assert plan.warnings == []


# --- applying -----------------------------------------------------------------


def apply_client(handler, log: list, *, dry_run: bool = False) -> CanvasClient:
    """A real CanvasClient whose requests go to *handler* and into *log*."""

    def logged(request: httpx.Request) -> httpx.Response:
        log.append((request.method, request.url.path, request.content.decode()))
        return handler(request)

    return CanvasClient(
        "https://canvas.example.com",
        token="test-token",
        course_id=1,
        transport=httpx.MockTransport(logged),
        time_zone=LA,
        dry_run=dry_run,
    )


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"user_id": 5, "assignment_id": 7})


def change(action: str, assignment_id: int, user_id: int) -> SubmissionChange:
    names = {7: "HW1", 8: "HW2"}
    item = SubmissionTarget(
        assignment=make_assignment(id=assignment_id, name=names[assignment_id]),
        submission=submission(user_id=user_id, assignment_id=assignment_id),
        student_name={5: "Ann", 6: "Ben"}[user_id],
    )
    return SubmissionChange(action, item, "graded" if action == "skip" else "")


def test_apply_sends_one_put_per_change():
    log: list = []
    client = apply_client(ok, log)
    applied = apply_submission_changes(
        client,
        [change("excuse", 7, 5), change("skip", 7, 6), change("clear-late", 8, 5)],
    )
    assert log == [
        (
            "PUT",
            "/api/v1/courses/1/assignments/7/submissions/5",
            "submission%5Bexcuse%5D=true",
        ),
        (
            "PUT",
            "/api/v1/courses/1/assignments/8/submissions/5",
            "submission%5Blate_policy_status%5D=none",
        ),
    ]
    assert applied == ["excuse HW1: Ann", "clear-late HW2: Ann"]


def test_apply_all_skips_sends_nothing():
    log: list = []
    client = apply_client(ok, log)
    assert apply_submission_changes(client, [change("skip", 7, 6)]) == []
    assert log == []


def test_apply_failure_lists_sent_changes():
    log: list = []

    def fail_second(request: httpx.Request) -> httpx.Response:
        if len(log) == 2:
            return httpx.Response(500, json={"message": "boom"})
        return ok(request)

    client = apply_client(fail_second, log)
    with pytest.raises(SubmissionApplyError) as caught:
        apply_submission_changes(
            client,
            [change("excuse", 7, 5), change("excuse", 7, 6), change("excuse", 8, 5)],
        )
    assert caught.value.applied == ["excuse HW1: Ann"]
    assert "Stopped; already sent:\n  excuse HW1: Ann" in str(caught.value)
    assert caught.value.__cause__ is not None
    assert len(log) == 2


def test_apply_auth_failure_lists_sent_changes(monkeypatch):
    # A session that expires mid-run still reports what was already sent
    from cass.apis.canvas.auth import CanvasAuthError

    client = apply_client(ok, [])
    calls: list[int] = []

    def update(assignment_id, user_id, **fields):
        calls.append(user_id)
        if len(calls) == 2:
            raise CanvasAuthError("session expired")

    monkeypatch.setattr(client, "update_submission", update)
    with pytest.raises(SubmissionApplyError) as caught:
        apply_submission_changes(
            client, [change("excuse", 7, 5), change("excuse", 7, 6)]
        )
    assert caught.value.applied == ["excuse HW1: Ann"]


def test_apply_failure_before_any_change():
    log: list = []
    client = apply_client(lambda request: httpx.Response(500, json={}), log)
    with pytest.raises(SubmissionApplyError, match="Stopped before any change"):
        apply_submission_changes(
            client, [change("excuse", 7, 5), change("excuse", 7, 6)]
        )
    assert len(log) == 1


def test_apply_unreadable_response_is_not_reported_as_unsent():
    # The PUT went through; only decoding its response failed.
    log: list = []
    client = apply_client(lambda request: httpx.Response(200, json=[]), log)
    with pytest.raises(msgspec.ValidationError):
        apply_submission_changes(client, [change("excuse", 7, 5)])
    assert len(log) == 1


def test_dry_run_plan_lines_for_submission_updates():
    client = apply_client(ok, [], dry_run=True)
    apply_submission_changes(
        client, [change("excuse", 7, 5), change("clear-late", 8, 5)]
    )
    assert format_plan(client.planned_requests) == [
        "PUT /courses/1/assignments/7/submissions/5  excuse=true",
        "PUT /courses/1/assignments/8/submissions/5  late_policy_status=none",
    ]


def test_apply_dry_run_records_without_sending():
    log: list = []

    def current(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"user_id": 5, "assignment_id": 7})
        return httpx.Response(500, json={"message": "unexpected write"})

    client = apply_client(current, log, dry_run=True)
    apply_submission_changes(client, [change("excuse", 7, 5)])
    assert [method for method, _, _ in log if method != "GET"] == []
    assert [(r.method, r.path) for r in client.planned_requests] == [
        ("PUT", "/courses/1/assignments/7/submissions/5")
    ]
