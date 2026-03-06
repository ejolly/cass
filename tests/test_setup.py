"""Tests for viewer setup: state detection, config writing, pull."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import duckdb
import pytest

from cass import db
from cass.config import load_config, reset_config, write_config
from cass.models import (
    Assignment,
    CanvasAssignment,
    CanvasStudent,
    CanvasSubmission,
    Student,
)


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_config()


# ---------------------------------------------------------------------------
# _detect_state
# ---------------------------------------------------------------------------


def test_detect_state_no_config(tmp_path, monkeypatch):
    """No cass.toml -> 'setup'."""
    monkeypatch.chdir(tmp_path)
    from cass.viewer.nicegui_app import _detect_state

    assert _detect_state() == "setup"


def test_detect_state_config_no_db(tmp_path, monkeypatch):
    """cass.toml exists but no database file -> 'pull'."""
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.viewer.nicegui_app import _detect_state

    assert _detect_state() == "pull"


def test_detect_state_ready(tmp_path, monkeypatch):
    """Both cass.toml and cass.duckdb exist -> 'ready'."""
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    conn = duckdb.connect(str(tmp_path / "cass.duckdb"))
    conn.close()
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.viewer.nicegui_app import _detect_state

    assert _detect_state() == "ready"


def test_detect_state_motherduck(tmp_path, monkeypatch):
    """MotherDuck config -> 'ready' even without local file."""
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\n'
        "course_id = 1\n\n"
        '[database]\nmotherduck = "my_db"\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.viewer.nicegui_app import _detect_state

    assert _detect_state() == "ready"


# ---------------------------------------------------------------------------
# write_config for canvas-only (the setup wizard flow)
# ---------------------------------------------------------------------------


def test_write_config_canvas_only(tmp_path):
    """Setup wizard writes canvas-only config."""
    path = tmp_path / "cass.toml"
    write_config(
        path,
        canvas_base_url="https://canvas.ucsd.edu",
        canvas_course_id=72335,
    )
    content = path.read_text()
    assert "[canvas]" in content
    assert 'base_url = "https://canvas.ucsd.edu"' in content
    assert "course_id = 72335" in content
    assert "[classroom]" not in content


def test_write_config_canvas_plus_github(tmp_path):
    """Setup wizard writes both sections when GitHub provided."""
    path = tmp_path / "cass.toml"
    write_config(
        path,
        classroom_id=299058,
        org="psyc-201",
        canvas_base_url="https://canvas.ucsd.edu",
        canvas_course_id=72335,
    )
    content = path.read_text()
    assert "[classroom]" in content
    assert "id = 299058" in content
    assert "[canvas]" in content


def test_write_config_then_load(tmp_path, monkeypatch):
    """Config written by write_config is loadable."""
    path = tmp_path / "cass.toml"
    write_config(
        path,
        canvas_base_url="https://canvas.ucsd.edu",
        canvas_course_id=72335,
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    cfg = load_config()
    assert cfg.has_canvas is True
    assert cfg.canvas_base_url == "https://canvas.ucsd.edu"
    assert cfg.canvas_course_id == 72335
    assert cfg.has_classroom is False


# ---------------------------------------------------------------------------
# pull_grades_headless
# ---------------------------------------------------------------------------


def test_pull_grades_headless_canvas(db_conn):
    """pull_grades_headless computes canvas grades from submissions."""
    from cass.pull import pull_grades_headless

    db.upsert_students([Student(canvas_id=100, name="Alice")])
    db.upsert_assignments(
        [
            _make_assignment("hw-01", canvas_id=42, points=10.0),
        ]
    )
    db.save_canvas_assignments(
        [
            CanvasAssignment(id=42, name="HW 01", points_possible=10.0),
        ]
    )
    db.save_canvas_submissions(
        [
            CanvasSubmission(
                canvas_user_id=100,
                canvas_assignment_id=42,
                submitted=True,
                submitted_at=datetime(2026, 1, 15, 12, 0, 0),
                late=False,
                lateness_seconds=0,
                score=8.0,
                workflow_state="graded",
            ),
        ]
    )

    pull_grades_headless()

    grades = db.load_canvas_grades()
    assert len(grades) == 1
    assert grades[0].canvas_user_id == 100
    assert grades[0].score == 8.0


def test_pull_grades_headless_empty(db_conn):
    """pull_grades_headless with no data does not raise."""
    from cass.pull import pull_grades_headless

    pull_grades_headless()
    assert db.load_canvas_grades() == []


# ---------------------------------------------------------------------------
# pull_all_async
# ---------------------------------------------------------------------------


def test_pull_all_async_canvas_only(tmp_path, monkeypatch, db_conn):
    """pull_all_async fetches Canvas data and populates the db."""
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    cfg = load_config()

    mock_students = [
        CanvasStudent(id=100, name="Alice Smith", email="a@t.edu"),
        CanvasStudent(id=200, name="Bob Jones", email="b@t.edu"),
    ]
    mock_assignments = [
        CanvasAssignment(id=42, name="HW 01", points_possible=10.0),
    ]
    mock_submissions = [
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

    with (
        patch(
            "cass.pull.matching_mod.fetch_students_with_sections",
            return_value=(mock_students, {}),
        ),
        patch(
            "cass.pull.matching_mod.fetch_canvas_assignments",
            return_value=(mock_assignments, {42: "Homework"}),
        ),
        patch(
            "cass.pull.matching_mod.fetch_canvas_submissions",
            return_value=mock_submissions,
        ),
    ):
        from cass.pull import pull_all_async

        progress_log: list[tuple[str, str]] = []

        asyncio.run(
            pull_all_async(
                cfg,
                on_progress=lambda s, d: progress_log.append((s, d)),
            )
        )

    students = db.load_students()
    assert len(students) == 2

    assignments = db.load_assignments()
    assert len(assignments) == 1
    assert assignments[0].title == "HW 01"

    grades = db.load_canvas_grades()
    assert len(grades) == 1

    steps_seen = {step for step, _ in progress_log}
    assert "students" in steps_seen
    assert "assignments" in steps_seen
    assert "grades" in steps_seen


def test_pull_all_async_no_callback(tmp_path, monkeypatch, db_conn):
    """pull_all_async works without a progress callback."""
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    cfg = load_config()

    with (
        patch(
            "cass.pull.matching_mod.fetch_students_with_sections",
            return_value=([], {}),
        ),
        patch(
            "cass.pull.matching_mod.fetch_canvas_assignments",
            return_value=([], {}),
        ),
    ):
        from cass.pull import pull_all_async

        asyncio.run(pull_all_async(cfg, on_progress=None))


def test_pull_all_async_with_github(tmp_path, monkeypatch, db_conn):
    """pull_all_async creates and closes a GitHubClient when configured."""
    (tmp_path / "cass.toml").write_text(
        '[classroom]\nid = 42\norg = "test-org"\n\n'
        '[canvas]\nbase_url = "https://canvas.example.com"\n'
        "course_id = 1\n"
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    cfg = load_config()

    mock_students = [
        CanvasStudent(id=100, name="Alice Smith", email="a@t.edu"),
    ]
    mock_gh_client = AsyncMock()

    with (
        patch(
            "cass.pull.matching_mod.fetch_students_with_sections",
            return_value=(mock_students, {}),
        ),
        patch(
            "cass.pull.matching_mod.fetch_canvas_assignments",
            return_value=([], {}),
        ),
        patch(
            "cass.pull.GitHubClient",
            return_value=mock_gh_client,
        ),
        patch(
            "cass.pull.classroom.fetch_all_students",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "cass.pull.classroom.fetch_assignments",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        from cass.pull import pull_all_async

        asyncio.run(pull_all_async(cfg))

    mock_gh_client.close.assert_awaited_once()
    students = db.load_students()
    assert len(students) == 1


def test_pull_all_async_github_client_closed_on_error(
    tmp_path,
    monkeypatch,
    db_conn,
):
    """GitHubClient is closed even when pull raises after client creation."""
    (tmp_path / "cass.toml").write_text(
        '[classroom]\nid = 42\norg = "test-org"\n\n'
        '[canvas]\nbase_url = "https://canvas.example.com"\n'
        "course_id = 1\n"
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    cfg = load_config()

    mock_students = [
        CanvasStudent(id=100, name="Alice", email="a@t.edu"),
    ]
    mock_gh_client = AsyncMock()

    with (
        patch(
            "cass.pull.matching_mod.fetch_students_with_sections",
            return_value=(mock_students, {}),
        ),
        patch(
            "cass.pull.GitHubClient",
            return_value=mock_gh_client,
        ),
        patch(
            "cass.pull.classroom.fetch_all_students",
            new_callable=AsyncMock,
            side_effect=RuntimeError("GH API down"),
        ),
    ):
        from cass.pull import pull_all_async

        with pytest.raises(RuntimeError, match="GH API down"):
            asyncio.run(pull_all_async(cfg))

    # Client must be closed even though an error occurred
    mock_gh_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assignment(
    slug: str,
    *,
    canvas_id: int = 0,
    points: float = 1.0,
) -> Assignment:
    return Assignment(
        slug=slug,
        title=slug.replace("-", " ").title(),
        gh_assignment_slug="",
        canvas_assignment_id=canvas_id,
        points_possible=points,
        deadline=None,
    )
