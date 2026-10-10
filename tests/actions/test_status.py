from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cass import db
from cass.actions.config import reset_config
from cass.actions.status import StatusCounts, count_pending, project_status
from cass.cli import app
from cass.db.schema import CanvasAssignment, CanvasStudent, CanvasSubmission


def test_count_pending():
    pending = {"t": {"1": {"a": {}, "b": {}}, "2": {"c": {}}}}
    assert count_pending(pending) == 3


def test_project_status_without_db(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    reset_config()

    status = project_status(project_dir / "cass.toml")

    assert status.course_url == "https://canvas.example.com/courses/1"
    assert status.course_id == 1
    assert status.auth_source is None
    assert status.db_path is None
    assert status.course_name is None
    assert status.counts is None
    assert status.pending_changes is None


@pytest.fixture
def populated_project(project_dir, monkeypatch):
    """Project with a small cass.db: meta, rows, and one pending change."""
    monkeypatch.chdir(project_dir)
    reset_config()
    sdb = db.open_db(project_dir)
    monkeypatch.setattr("cass.db.core._db", sdb)
    monkeypatch.setattr("cass.db.core._db_path", None)
    db.save_meta("course_name", "Intro Psych")
    db.save_canvas_students(
        [CanvasStudent(canvas_id=1, name="A"), CanvasStudent(canvas_id=2, name="B")]
    )
    db.save_canvas_assignments(
        [CanvasAssignment(canvas_id=10, name="HW1", points_possible=10.0)]
    )
    db.save_canvas_submissions(
        [
            CanvasSubmission(canvas_user_id=1, canvas_assignment_id=10, score=5.0),
            CanvasSubmission(canvas_user_id=2, canvas_assignment_id=10, score=6.0),
            CanvasSubmission(canvas_user_id=3, canvas_assignment_id=10, score=7.0),
        ]
    )
    db.snapshot_canvas_synced(sdb)
    sdb.execute("UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = 10")
    sdb.conn.commit()
    return project_dir


def test_project_status_with_db(populated_project):
    status = project_status(populated_project / "cass.toml")

    assert status.db_path == str(populated_project / "cass.db")
    assert status.course_name == "Intro Psych"
    assert status.counts == StatusCounts(students=2, assignments=1, submissions=3)
    assert status.pending_changes == 1


def test_status_json_with_populated_db(populated_project):
    result = CliRunner().invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["course_name"] == "Intro Psych"
    assert data["counts"] == {"students": 2, "assignments": 1, "submissions": 3}
    assert data["pending_changes"] == 1


def test_status_human_with_populated_db(populated_project):
    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Course: Intro Psych" in result.stdout
    assert "students: 2" in result.stdout
    assert "canvas submissions: 3" in result.stdout
    assert "1 pending change(s)" in result.stdout
