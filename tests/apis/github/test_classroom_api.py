"""Tests for classroom.py REST API integration (mocked GitHubClient)."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import AsyncMock

import pytest

from cass.apis.github import classroom
from cass.db import core as db_core
from cass.db.schema import GHAssignment, GHStudent

# ---------------------------------------------------------------------------
# Canned API response data
# ---------------------------------------------------------------------------

ASSIGNMENTS_JSON = [
    {
        "id": 918460,
        "slug": "wk01-lab",
        "title": "Week 01 Lab",
        "deadline": "2025-01-15T23:59:00Z",
        "accepted": 3,
        "submissions": 2,
        "passing": 1,
    },
    {
        "id": 923987,
        "slug": "hw-01",
        "title": "Homework 01",
        "accepted": 2,
        "submissions": 1,
        "passing": 0,
    },
]

GRADES_918460 = [
    {
        "github_username": "alice-gh",
        "roster_identifier": "Alice Smith",
        "student_repository_name": "wk01-lab-alice-gh",
        "student_repository_url": "https://github.com/my-org/wk01-lab-alice-gh",
        "submission_timestamp": "2025-01-07 23:12:11 UTC",
        "points_awarded": "100",
        "points_available": "100",
    },
    {
        "github_username": "bob-gh",
        "roster_identifier": "Bob Jones",
        "student_repository_name": "wk01-lab-bob-gh",
        "student_repository_url": "https://github.com/my-org/wk01-lab-bob-gh",
        "submission_timestamp": "2025-01-08 10:00:00 UTC",
        "points_awarded": "80",
        "points_available": "100",
    },
    {
        "github_username": "charlie-gh",
        "roster_identifier": "",
        "student_repository_name": "wk01-lab-charlie-gh",
        "student_repository_url": "https://github.com/my-org/wk01-lab-charlie-gh",
        "submission_timestamp": "",
        "points_awarded": "",
        "points_available": "100",
    },
]

GRADES_923987 = [
    {
        "github_username": "alice-gh",
        "roster_identifier": "Alice Smith",
        "student_repository_name": "hw-01-alice-gh",
        "student_repository_url": "https://github.com/my-org/hw-01-alice-gh",
        "submission_timestamp": "2025-01-20 12:00:00 UTC",
        "points_awarded": "90",
        "points_available": "100",
    },
]

ACCEPTED_918460 = [
    {
        "id": 1001,
        "students": [{"id": 1, "login": "alice-gh"}],
        "repository": {"id": 5001, "full_name": "my-org/wk01-lab-alice-gh"},
        "commit_count": 5,
        "submitted": True,
        "passing": True,
        "grade": "100",
    },
    {
        "id": 1002,
        "students": [{"id": 2, "login": "bob-gh"}],
        "repository": {"id": 5002, "full_name": "my-org/wk01-lab-bob-gh"},
        "commit_count": 3,
        "submitted": True,
        "passing": False,
        "grade": "80",
    },
    {
        "id": 1003,
        "students": [{"id": 3, "login": "charlie-gh"}],
        "repository": {"id": 5003, "full_name": "my-org/wk01-lab-charlie-gh"},
        "commit_count": 0,
        "submitted": False,
        "passing": False,
        "grade": None,
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _route_get_cached(endpoint: str, **_kwargs: object) -> object:
    """Return canned data based on the endpoint."""
    if "/classrooms/" in endpoint and "/assignments" in endpoint:
        return ASSIGNMENTS_JSON
    if "/assignments/918460/grades" in endpoint:
        return GRADES_918460
    if "/assignments/923987/grades" in endpoint:
        return GRADES_923987
    if "/assignments/918460/accepted_assignments" in endpoint:
        return ACCEPTED_918460
    return []


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.get_cached = AsyncMock(side_effect=_route_get_cached)
    return client


@pytest.fixture
def classroom_config(tmp_path, monkeypatch):
    """Create a minimal cass.toml and monkeypatch get_config in classroom module."""
    from cass.actions.config import Config

    cfg = Config(
        root=tmp_path,
        classroom_url="https://classroom.github.com/classrooms/12345-test",
        classroom_url_id=12345,
        classroom_gh_id=299058,
        classroom_slug="test",
        classroom_title="Test Classroom",
        org="my-org",
    )
    monkeypatch.setattr(classroom, "get_config", lambda: cfg)
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_assignments(mock_client, classroom_config):
    result = await classroom.fetch_assignments(mock_client)
    assert len(result) == 2
    slugs = {a.slug for a in result}
    assert slugs == {"wk01-lab", "hw-01"}
    wk01 = next(a for a in result if a.slug == "wk01-lab")
    assert wk01.id == 918460
    assert wk01.deadline == "2025-01-15T23:59:00Z"
    hw01 = next(a for a in result if a.slug == "hw-01")
    assert hw01.deadline is None


@pytest.mark.asyncio
async def test_fetch_all_students(mock_client, classroom_config):
    students = await classroom.fetch_all_students(mock_client)
    logins = {s.login.lower() for s in students}
    assert "alice-gh" in logins
    assert "bob-gh" in logins
    assert "charlie-gh" in logins
    # Dedup: alice appears in both assignments but should only appear once
    assert len([s for s in students if s.login.lower() == "alice-gh"]) == 1
    # Name populated from roster_identifier
    alice = next(s for s in students if s.login == "alice-gh")
    assert alice.name == "Alice Smith"


@pytest.mark.asyncio
async def test_fetch_submissions_combines_grades_and_accepted(
    mock_client, classroom_config, db_conn
):
    from cass.db.schema import Student

    roster = [
        Student(canvas_id=1, github_username="alice-gh", name="Alice Smith"),
        Student(canvas_id=2, github_username="bob-gh", name="Bob Jones"),
    ]
    subs = await classroom.fetch_submissions(mock_client, "wk01-lab", None, roster)
    assert len(subs) == 2
    alice_sub = next(s for s in subs if s.github_username == "alice-gh")
    assert alice_sub.submitted is True
    assert alice_sub.repo_name == "my-org/wk01-lab-alice-gh"
    assert alice_sub.commit_count == 5
    assert alice_sub.passing is True
    assert alice_sub.gh_autograder_score == "100"

    bob_sub = next(s for s in subs if s.github_username == "bob-gh")
    assert bob_sub.submitted is True
    assert bob_sub.commit_count == 3


@pytest.mark.asyncio
async def test_fetch_submissions_student_not_in_grades(
    mock_client, classroom_config, db_conn
):
    """Student in roster but not in GH grades → submitted=False."""
    from cass.db.schema import Student

    roster = [
        Student(canvas_id=99, github_username="unknown-gh", name="Unknown Student"),
    ]
    subs = await classroom.fetch_submissions(mock_client, "wk01-lab", None, roster)
    assert len(subs) == 1
    assert subs[0].submitted is False


@pytest.mark.asyncio
async def test_resolve_gh_id_not_found(mock_client, classroom_config):
    with pytest.raises(RuntimeError, match="not found"):
        await classroom.resolve_gh_id(mock_client, "nonexistent-assignment")


@pytest.mark.asyncio
async def test_build_repo_map(mock_client, classroom_config):
    repo_map = await classroom.build_repo_map(mock_client, "wk01-lab")
    assert repo_map["alice-gh"] == "my-org/wk01-lab-alice-gh"
    assert repo_map["bob-gh"] == "my-org/wk01-lab-bob-gh"
    assert repo_map["charlie-gh"] == "my-org/wk01-lab-charlie-gh"


@pytest.mark.asyncio
async def test_full_pipeline_save_to_db(mock_client, classroom_config, db_conn):
    """Fetch → save to DB → load back and verify."""
    assignments = await classroom.fetch_assignments(mock_client)
    db_core.save_gh_assignments([GHAssignment.from_api(a) for a in assignments])

    students = await classroom.fetch_all_students(mock_client)
    db_core.save_gh_students([GHStudent.from_api(s) for s in students])

    # Verify assignments saved
    rows = list(db_conn["gh_assignments"].rows)
    assert len(rows) == 2
    slugs = {r["slug"] for r in rows}
    assert slugs == {"wk01-lab", "hw-01"}

    # Verify students saved
    student_rows = list(db_conn["gh_students"].rows)
    assert len(student_rows) == 3
    logins = {r["github_username"] for r in student_rows}
    assert logins == {"alice-gh", "bob-gh", "charlie-gh"}


@pytest.mark.asyncio
async def test_gh_students_not_in_canvas(mock_client, classroom_config, db_conn):
    """GH-only student saved to gh_students but not in master students table."""
    students = await classroom.fetch_all_students(mock_client)
    db_core.save_gh_students([GHStudent.from_api(s) for s in students])

    gh_logins = {r["github_username"] for r in db_conn["gh_students"].rows}
    assert "charlie-gh" in gh_logins

    # Canvas students table should be empty (no canvas data loaded)
    canvas_rows = list(db_conn["students"].rows)
    assert len(canvas_rows) == 0


@pytest.mark.asyncio
async def test_assignment_no_deadline(mock_client, classroom_config, db_conn):
    """Assignment without a deadline saves correctly with NULL."""
    assignments = await classroom.fetch_assignments(mock_client)
    db_core.save_gh_assignments([GHAssignment.from_api(a) for a in assignments])

    hw01 = next(r for r in db_conn["gh_assignments"].rows if r["slug"] == "hw-01")
    assert hw01["deadline"] is None
