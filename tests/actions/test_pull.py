"""Tests for the Canvas-only pull flow."""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime
from unittest.mock import patch

import pytest
from rich.console import Console

from cass import db
from cass.actions.config import load_config, reset_config
from cass.apis.canvas.schema import CanvasAssignmentResponse, CanvasStudentResponse
from cass.db.core import _connection
from cass.db.schema import CanvasSubmission

_MOCK_STUDENTS = [
    CanvasStudentResponse(id=100, name="Alice Smith", email="a@t.edu"),
    CanvasStudentResponse(id=200, name="Bob Jones", email="b@t.edu"),
]
_MOCK_ASSIGNMENTS = [
    CanvasAssignmentResponse(id=42, name="HW 01", points_possible=10.0),
]
_MOCK_SUBMISSIONS = [
    CanvasSubmission(
        canvas_user_id=100,
        canvas_assignment_id=42,
        submitted=True,
        submitted_at=datetime(2026, 1, 15, 12, 0, 0),
        late=False,
        lateness_seconds=0,
        score=9.0,
        workflow_state="graded",
    ),
]


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_config()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    return load_config()


@pytest.fixture
def canvas_api():
    """Patch every Canvas call the pull flow makes."""
    with (
        patch(
            "cass.actions.pull.canvas_api.fetch_course_name",
            return_value="Test Course 101",
        ),
        patch(
            "cass.actions.pull.canvas_api.fetch_students_with_sections",
            return_value=(_MOCK_STUDENTS, {}),
        ),
        patch(
            "cass.actions.pull.canvas_api.fetch_canvas_assignments",
            return_value=(_MOCK_ASSIGNMENTS, {42: "Homework"}),
        ),
        patch(
            "cass.actions.pull.canvas_api.fetch_canvas_submissions",
            return_value=_MOCK_SUBMISSIONS,
        ) as fetch_submissions,
    ):
        yield fetch_submissions


class TestPullAll:
    def test_blocks_when_canvas_grades_pending(self, cfg, db_conn):
        db_conn.execute("INSERT INTO canvas_grades VALUES (100, 42, 9.0, '10', 1.0)")
        db_conn.execute("INSERT INTO _canvas_grades_synced VALUES (100, 42, '9')")

        from cass.actions.pull import pull_all

        with pytest.raises(RuntimeError, match=r"cass push.*cass revert"):
            pull_all(cfg)

    def test_populates_canvas_tables(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        progress: list[tuple[str, str]] = []
        pull_all(cfg, on_progress=lambda s, d: progress.append((s, d)))

        assert db_conn["canvas_students"].count == 2
        assert db_conn["canvas_assignments"].count == 1
        assert db_conn["canvas_submissions"].count == 1
        assert db.get_meta("course_name", db_conn) == "Test Course 101"
        assert {step for step, _ in progress} >= {
            "students",
            "assignments",
            "submissions",
            "done",
        }

    def test_submissions_use_roster_and_assignment_ids(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg)

        canvas_api.assert_called_once_with(1, 42, {100, 200})

    def test_persists_after_reopen(self, cfg, tmp_path, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg)

        reopened = db.open_db(tmp_path)
        assert reopened["canvas_students"].count == 2
        assert reopened["canvas_submissions"].count == 1
        _connection(reopened).close()

    def test_snapshots_synced_state(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg)

        assert db_conn["_canvas_assignments_synced"].count == 1
        assert db.pull_block_reason(db_conn) is None

    def test_no_callback(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg, on_progress=None)


class TestPullSteps:
    def test_pull_submissions_without_assignments_warns(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_submissions

        console = Console(record=True, width=120)
        pull_submissions(cfg, console)

        assert "No assignments" in console.export_text()
        canvas_api.assert_not_called()

    def test_steps_compose(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import (
            pull_assignments,
            pull_students,
            pull_submissions,
        )

        console = Console(record=True, width=120)
        pull_students(cfg, console)
        pull_assignments(cfg, console)
        pull_submissions(cfg, console)

        assert db_conn["canvas_students"].count == 2
        assert db_conn["canvas_assignments"].count == 1
        assert db_conn["canvas_submissions"].count == 1
