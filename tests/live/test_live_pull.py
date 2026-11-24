"""Live test: a grade survives pull, edit, push, and clear exactly as entered."""

from __future__ import annotations

__docformat__ = "google"

import time
from uuid import uuid4

import pytest
import sqlite_utils
from live_course import get_test_student_id
from rich.console import Console

from cass import db
from cass.actions.config import get_config
from cass.actions.pull import pull_assignments, pull_students, pull_submissions
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.schema import CanvasStudentResponse, CanvasSubmissionResponse


def _submission(
    client: CanvasClient, assignment_id: int, user_id: int, timeout: float = 30
) -> CanvasSubmissionResponse:
    """The user's submission, once Canvas has created it for a new assignment."""
    deadline = time.monotonic() + timeout
    while True:
        for submission in client.list_submissions(assignment_id):
            if submission.user_id == user_id:
                return submission
        assert time.monotonic() < deadline, f"no submission row after {timeout}s"
        time.sleep(2)


def _pull(assignment_id: int) -> None:
    """Pull the roster and assignments, then submissions for one assignment."""
    cfg = get_config()
    console = Console(quiet=True)
    pull_students(cfg, console)
    pull_assignments(cfg, console)
    db.get_db().table("canvas_assignments").delete_where(
        "canvas_id != ?", [assignment_id]
    )
    pull_submissions(cfg, console)


def _push_pending(conn: sqlite_utils.Database) -> list[dict[str, object]]:
    """Push every pending change, clears included; returns the preview rows."""
    pending = db.get_pending_changes(conn)
    preview = db.canvas_preview(conn, pending)
    to_push, held = db.hold_back_unapproved(pending, preview, allow_clears=True)
    assert held == []
    assert db.canvas_apply(conn, to_push)["ok"]
    assert db.get_pending_changes(conn) == {}
    return preview["changes"]  # ty: ignore[invalid-return-type]


def _same_client(practice: CanvasClient, **kwargs: object) -> CanvasClient:
    """A practice-course client for core code that opens its own."""
    assert kwargs.get("course_id", practice.course_id) == practice.course_id
    return CanvasClient(
        get_config().canvas_base_url,
        course_id=practice.course_id,
        auth=practice.auth,
        time_zone=practice.time_zone,
    )


def test_pull_edit_push_round_trip(
    practice: CanvasClient,
    db_conn: sqlite_utils.Database,
    monkeypatch: pytest.MonkeyPatch,
):
    student_id = get_test_student_id(practice)
    monkeypatch.setattr(
        CanvasClient,
        "list_students",
        lambda self: [CanvasStudentResponse(id=student_id, name="Test Student")],
    )
    for target in (
        "cass.apis.canvas.matching.CanvasClient",
        "cass.apis.canvas.client.CanvasClient",
    ):
        monkeypatch.setattr(target, lambda **kw: _same_client(practice, **kw))

    assignment = practice.create_assignment(
        f"cass-live pull {uuid4().hex[:8]}", points_possible=10, published=True
    )
    try:
        ungraded = _submission(practice, assignment.id, student_id)
        assert ungraded.entered_grade is None
        _pull(assignment.id)
        (grade,) = db.load_canvas_grades(assignment.id)
        assert grade.posted_grade == ""
        assert db.get_pending_changes(db_conn) == {}

        db.upsert_canvas_grade(db_conn, student_id, assignment.id, "8")
        (row,) = _push_pending(db_conn)
        assert (row["baseline"], row["conflict"]) == ("", False)
        graded = _submission(practice, assignment.id, student_id)
        assert graded.entered_grade == "8"

        _pull(assignment.id)
        (grade,) = db.load_canvas_grades(assignment.id)
        assert (grade.posted_grade, grade.score) == ("8", 8.0)
        assert db.get_pending_changes(db_conn) == {}

        db.upsert_canvas_grade(db_conn, student_id, assignment.id, "")
        (row,) = _push_pending(db_conn)
        assert (row["clears"], row["conflict"]) == (True, False)
        cleared = _submission(practice, assignment.id, student_id)
        assert cleared.entered_grade is None
    finally:
        practice.delete_assignment(assignment.id)


def test_roster_matches_enrollments(real_course: CanvasClient):
    roster_ids = {student.id for student in real_course.list_students()}
    enrollment_ids = {
        enrollment.user_id
        for enrollment in real_course.list_enrollments(
            states=("active", "invited"), include_scores=False
        )
    }
    assert roster_ids == enrollment_ids
