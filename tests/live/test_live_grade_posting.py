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
from cass.actions.assignments import push_new_assignment
from cass.actions.config import get_config
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.schema import CanvasAssignmentResponse
from cass.apis.canvas.sync import get_scheme, push_grades, shows_pushed_grade

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
    db.mark_synced_grades(conn, {(user_id, assignment_id): old})
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

    # Released before: the change is visible without another release.
    to_push, preview = edit_grade(db_conn, student_id, assignment.id, "9", "7")
    assert db.count_postable(to_push, preview) == 0
    assert "1 changed grade(s) are already released" in str(
        db.release_notices(to_push, preview)
    )
    result = db.canvas_apply(db_conn, to_push, post_grades=True, preview=preview)
    assert result["ok"]
    assert db.push_notices(result) == []
    assert posting_requests == [[student_id]]
    assert live() == ("7", posted_at)


def test_grade_on_a_new_assignment_is_not_a_conflict(
    practice: CanvasClient,
    db_conn: sqlite_utils.Database,
    student_id: int,
    posting_requests: list[list[int]],
):
    """A grade typed before or after creation is compared with a blank."""
    db.save_canvas_students([db.CanvasStudent(canvas_id=student_id, name="Test")])
    for typed_first in (False, True):
        local_id = db.create_local_assignment(
            db_conn,
            name=f"cass-live posting {uuid4().hex[:8]}",
            points_possible=10,
            published=True,
        )
        if typed_first:
            db.upsert_canvas_grade(db_conn, student_id, local_id, "8")
        result = push_new_assignment(db_conn, local_id, practice)
        assert result["ok"], result
        assignment_id = int(str(result["canvas_id"]))
        try:
            set_post_manually(practice, assignment_id, True)
            grade_and_posted_at(practice, assignment_id, student_id)
            db.upsert_canvas_grade(db_conn, student_id, assignment_id, "8")
            pending = db.get_pending_changes(db_conn)
            preview = db.canvas_preview(db_conn, pending)
            (row,) = preview["changes"]  # ty: ignore[not-iterable]
            assert (row["baseline"], row["live"], row["conflict"]) == ("", None, False)
            to_push, held = db.hold_back_unapproved(pending, preview)
            assert held == []
            assert db.canvas_apply(db_conn, to_push, preview=preview)["ok"]
            assert grade_and_posted_at(practice, assignment_id, student_id) == (
                "8",
                None,
            )
            assert db.get_pending_changes(db_conn) == {}
        finally:
            practice.delete_assignment(assignment_id)


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


def test_grade_canvas_ignores_is_not_released(
    practice: CanvasClient, db_conn: sqlite_utils.Database, student_id: int
):
    """Without points, Canvas keeps ``complete`` when ``incomplete`` is pushed."""
    created = practice.create_assignment(
        f"cass-live posting {uuid4().hex[:8]}",
        points_possible=0,
        grading_type="pass_fail",
        published=True,
    )
    try:
        set_post_manually(practice, created.id, True)
        grade_and_posted_at(practice, created.id, student_id)
        for sent, releases in (("complete", False), ("incomplete", True)):
            results = push_grades(
                practice,
                db_conn,
                {created.id: {student_id: sent}},
                post_grades=releases,
            )
            assert results[0]["ok"]
        assert "does not show the pushed grade" in str(results[-1]["error"])
        assert results[-1]["unconfirmed_ids"] == [student_id]
        assert grade_and_posted_at(practice, created.id, student_id) == (
            "complete",
            None,
        )
    finally:
        practice.delete_assignment(created.id)


@pytest.mark.parametrize(
    ("grading_type", "forms"),
    [
        (
            "points",
            {
                "8.50": "8.5",
                "+3": "3",
                ".5": "0.5",
                "95%": "6.65",
                "33.333%": "2.33331",
            },
        ),
        ("percent", {"95.50%": "95.5%", "33.333%": "33.33%", "33.335%": "33.34%"}),
        ("letter_grade", {"95%": "A", "33.333%": "F"}),
        ("gpa_scale", {"95%": "A"}),
        ("pass_fail", {"pass": "complete", "fail": "incomplete"}),
    ],
)
def test_normalized_grades_match(
    practice: CanvasClient, student_id: int, grading_type: str, forms: dict[str, str]
):
    """The practice course shows no letter scheme, so letters match by score."""
    created = practice.create_assignment(
        f"cass-live posting {uuid4().hex[:8]}",
        points_possible=7,
        grading_type=grading_type,
        published=True,
    )
    try:
        set_post_manually(practice, created.id, True)
        grade_and_posted_at(practice, created.id, student_id)
        scheme = get_scheme(practice, practice.get_assignment(created.id))
        for sent, shown in forms.items():
            progress = practice.bulk_push_grades(created.id, {student_id: sent})
            practice.wait_for_progress(progress.id)
            (submission,) = [
                s
                for s in practice.list_submissions(created.id)
                if s.user_id == student_id
            ]
            assert submission.entered_grade == shown
            assert submission.posted_at is None
            for pushed in forms:
                assert shows_pushed_grade(
                    pushed, submission, grading_type, 7, scheme
                ) is (pushed == sent), (pushed, shown)
    finally:
        practice.delete_assignment(created.id)
