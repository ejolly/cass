"""Live tests: pushed grades reach students only when released (C5).

Every grade belongs to the Test Student, on a throwaway manual-post assignment.
"""

from __future__ import annotations

__docformat__ = "google"

import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlite_utils
from live_course import get_test_student_id

from cass import db
from cass.actions.config import get_config
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.schema import CanvasAssignmentResponse

_SET_POLICY = """
mutation ($assignmentId: ID!, $postManually: Boolean!) {
  setAssignmentPostPolicy(
    input: {assignmentId: $assignmentId, postManually: $postManually}
  ) {
    postPolicy { postManually }
    errors { attribute message }
  }
}
"""


def set_post_manually(client: CanvasClient, assignment_id: int, value: bool) -> None:
    data = client._graphql(
        _SET_POLICY, {"assignmentId": str(assignment_id), "postManually": value}
    )
    result = data["setAssignmentPostPolicy"]
    assert not result["errors"]
    assert result["postPolicy"]["postManually"] is value
    assert client.get_assignment(assignment_id).post_manually is value


@pytest.fixture
def student_id(practice: CanvasClient) -> int:
    return get_test_student_id(practice)


@pytest.fixture
def assignment(
    practice: CanvasClient, student_id: int
) -> Iterator[CanvasAssignmentResponse]:
    """A published assignment that posts manually, deleted afterwards."""
    created = practice.create_assignment(
        f"cass-live posting {uuid4().hex[:8]}", points_possible=10, published=True
    )
    try:
        set_post_manually(practice, created.id, True)
        yield created
    finally:
        practice.delete_assignment(created.id)


@pytest.fixture
def posting_requests(
    practice: CanvasClient, monkeypatch: pytest.MonkeyPatch
) -> list[list[int]]:
    """Point pushes at the practice course; records each posting's students."""

    def same_client() -> CanvasClient:
        return CanvasClient(
            get_config().canvas_base_url,
            course_id=practice.course_id,
            auth=practice.auth,
            time_zone=practice.time_zone,
        )

    requests: list[list[int]] = []
    post = CanvasClient.post_assignment_grades

    def recording_post(self, assignment_id, *, only_student_ids, **kwargs):
        requests.append(list(only_student_ids))
        return post(self, assignment_id, only_student_ids=only_student_ids, **kwargs)

    monkeypatch.setattr("cass.apis.canvas.client.CanvasClient", same_client)
    monkeypatch.setattr(CanvasClient, "post_assignment_grades", recording_post)
    return requests


def grade_and_posted_at(
    client: CanvasClient, assignment_id: int, user_id: int
) -> tuple[str | None, str | None]:
    """The user's grade as entered and when it was posted, read from raw JSON.

    Waits for Canvas to create the submission for a new assignment.
    """
    path = client.course_path(f"/assignments/{assignment_id}/submissions")
    deadline = time.monotonic() + 30
    while True:
        for submission in client.get_all(path):
            if submission["user_id"] == user_id:
                return submission["entered_grade"], submission["posted_at"]
        assert time.monotonic() < deadline, "no submission row after 30s"
        time.sleep(2)


def edit_grade(
    conn: sqlite_utils.Database, user_id: int, assignment_id: int, old: str, new: str
) -> tuple[db.PendingChanges, dict[str, object]]:
    """Store a grade as pulled, change it, and preview the push."""
    db.upsert_canvas_grade(conn, user_id, assignment_id, old)
    db.mark_synced_grades(conn, [(user_id, assignment_id)])
    db.upsert_canvas_grade(conn, user_id, assignment_id, new)
    pending = db.get_pending_changes(conn)
    preview = db.canvas_preview(conn, pending)
    to_push, held = db.hold_back_unapproved(pending, preview, allow_clears=True)
    assert held == []
    return to_push, preview


def test_posting_needs_approval_and_names_students(
    practice: CanvasClient,
    db_conn: sqlite_utils.Database,
    student_id: int,
    assignment: CanvasAssignmentResponse,
    posting_requests: list[list[int]],
):
    def live() -> tuple[str | None, str | None]:
        return grade_and_posted_at(practice, assignment.id, student_id)

    assert live() == (None, None)

    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "", "8")
    assert db.count_postable(to_push, preview) == 1
    result = db.canvas_apply(db_conn, to_push, preview=preview)
    assert result["ok"]
    assert db.count_unreleased(result) == 1
    assert posting_requests == []
    assert live() == ("8", None)

    other_id = int(practice.request("GET", "/users/self").json()["id"])
    assert other_id != student_id
    progress = practice.post_assignment_grades(
        assignment.id, only_student_ids=[other_id]
    )
    assert progress is not None
    practice.wait_for_progress(progress.id)
    assert live() == ("8", None)
    posting_requests.clear()

    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "8", "9")
    result = db.canvas_apply(db_conn, to_push, post_grades=True, preview=preview)
    assert result["ok"], result
    assert posting_requests == [[student_id]]
    grade, posted_at = live()
    assert grade == "9"
    assert posted_at is not None
    assert db.get_pending_changes(db_conn) == {}


def test_clear_only_push_posts_nothing(
    practice: CanvasClient,
    db_conn: sqlite_utils.Database,
    student_id: int,
    assignment: CanvasAssignmentResponse,
    posting_requests: list[list[int]],
):
    grade_and_posted_at(practice, assignment.id, student_id)
    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "", "8")
    assert db.canvas_apply(db_conn, to_push, preview=preview)["ok"]

    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "8", "")
    assert db.count_postable(to_push, preview) == 0
    assert db.canvas_apply(db_conn, to_push, post_grades=True, preview=preview)["ok"]
    assert posting_requests == []
    assert grade_and_posted_at(practice, assignment.id, student_id) == (None, None)


def test_policy_change_after_preview_stops_unapproved_release(
    practice: CanvasClient,
    db_conn: sqlite_utils.Database,
    student_id: int,
    assignment: CanvasAssignmentResponse,
    posting_requests: list[list[int]],
):
    grade_and_posted_at(practice, assignment.id, student_id)
    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "", "8")
    set_post_manually(practice, assignment.id, False)
    result = db.canvas_apply(db_conn, to_push, preview=preview)
    assert not result["ok"]
    assert "now post automatically" in str(result["results"])
    assert grade_and_posted_at(practice, assignment.id, student_id) == (None, None)

    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "", "8")
    set_post_manually(practice, assignment.id, True)
    result = db.canvas_apply(db_conn, to_push, post_grades=True, preview=preview)
    assert result["ok"]
    assert db.count_unreleased(result) == 1
    assert posting_requests == []
    assert grade_and_posted_at(practice, assignment.id, student_id) == ("8", None)
