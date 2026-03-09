"""Tests for viewer setup: state detection, config writing, pull."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from cass import db
from cass.actions.config import load_config, reset_config, write_config
from cass.apis.canvas.schema import CanvasAssignmentResponse, CanvasStudentResponse
from cass.db.core import _connection
from cass.db.schema import Assignment, CanvasSubmission, Student


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_config()


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


class TestWriteLoadRoundTrip:
    def test_both_sections(self, tmp_path, monkeypatch):
        """write_config creates a valid TOML file that load_config can read."""
        monkeypatch.chdir(tmp_path)
        reset_config()
        write_config(
            tmp_path / "cass.toml",
            classroom_url="https://classroom.github.com/classrooms/42-course",
            classroom_url_id=42,
            classroom_gh_id=4200,
            org="test-org",
            canvas_base_url="https://canvas.example.com",
            canvas_course_id=1,
        )
        cfg = load_config()
        assert cfg.classroom_url_id == 42
        assert cfg.classroom_gh_id == 4200
        assert cfg.org == "test-org"
        assert cfg.canvas_base_url == "https://canvas.example.com"
        assert cfg.canvas_course_id == 1
        assert cfg.has_classroom is True
        assert cfg.has_canvas is True

    def test_canvas_only(self, tmp_path, monkeypatch):
        """write_config works without classroom settings."""
        monkeypatch.chdir(tmp_path)
        reset_config()
        write_config(
            tmp_path / "cass.toml",
            canvas_base_url="https://canvas.example.com",
            canvas_course_id=1,
        )
        cfg = load_config()
        assert cfg.has_classroom is False
        assert cfg.has_canvas is True

    def test_with_assignments(self, tmp_path, monkeypatch):
        """load_config parses [canvas.assignments] tables."""
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\n'
            "course_id = 72335\n\n"
            "[[canvas.assignments]]\n"
            'name = "HW1"\npoints = 10.0\ngroup = "Homework"\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()
        assert cfg.canvas_course_id == 72335
        assert cfg.has_classroom is False


class TestPullAllAsync:
    def test_blocks_when_canvas_grades_pending(self, tmp_path, monkeypatch, db_conn):
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        db_conn.execute("INSERT INTO canvas_grades VALUES (100, 42, 9.0, '10', 1.0)")
        db_conn.execute("INSERT INTO _canvas_grades_synced VALUES (100, 42, '9')")

        from cass.actions.pull import pull_all_async

        with pytest.raises(RuntimeError, match=r"cass push.*cass revert"):
            asyncio.run(pull_all_async(cfg))

    def test_canvas_only(self, tmp_path, monkeypatch, db_conn):
        """pull_all_async fetches Canvas data and populates the db."""
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        mock_students = [
            CanvasStudentResponse(id=100, name="Alice Smith", email="a@t.edu"),
            CanvasStudentResponse(id=200, name="Bob Jones", email="b@t.edu"),
        ]
        mock_assignments = [
            CanvasAssignmentResponse(id=42, name="HW 01", points_possible=10.0),
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
                "cass.actions.pull.matching_mod.fetch_course_name",
                return_value="Test Course 101",
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_students_with_sections",
                return_value=(mock_students, {}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_assignments",
                return_value=(mock_assignments, {42: "Homework"}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_submissions",
                return_value=mock_submissions,
            ),
        ):
            from cass.actions.pull import pull_all_async

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

        steps_seen = {step for step, _ in progress_log}
        assert "students" in steps_seen
        assert "assignments" in steps_seen

    def test_canvas_only_persists_after_reopen(self, tmp_path, monkeypatch):
        """pull_all_async commits writes so a fresh DB connection sees them."""
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        mock_students = [
            CanvasStudentResponse(id=100, name="Alice Smith", email="a@t.edu"),
        ]
        mock_assignments = [
            CanvasAssignmentResponse(id=42, name="HW 01", points_possible=10.0),
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
                "cass.actions.pull.matching_mod.fetch_course_name",
                return_value="Test Course 101",
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_students_with_sections",
                return_value=(mock_students, {}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_assignments",
                return_value=(mock_assignments, {42: "Homework"}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_submissions",
                return_value=mock_submissions,
            ),
        ):
            from cass.actions.pull import pull_all_async

            asyncio.run(pull_all_async(cfg))

        reopened = db.open_db(tmp_path)
        assert reopened["students"].count == 1
        assert reopened["assignments"].count == 1
        assert reopened["canvas_submissions"].count == 1
        _connection(reopened).close()

    def test_no_callback(self, tmp_path, monkeypatch, db_conn):
        """pull_all_async works without a progress callback."""
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        with (
            patch(
                "cass.actions.pull.matching_mod.fetch_course_name",
                return_value="Test Course 101",
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_students_with_sections",
                return_value=([], {}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_assignments",
                return_value=([], {}),
            ),
        ):
            from cass.actions.pull import pull_all_async

            asyncio.run(pull_all_async(cfg, on_progress=None))

    def test_no_classroom_clears_stale_github_data(self, tmp_path, monkeypatch):
        """Canvas-only pulls remove stale GitHub tables from the local DB."""
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        conn = db.open_db(tmp_path)
        conn.execute(
            "INSERT INTO gh_students "
            "(github_username, github_id, name, email, excluded) "
            "VALUES ('alice-gh', 1, 'Alice Smith', 'alice@test.edu', 0)"
        )
        conn.execute(
            "INSERT INTO gh_assignments "
            "(slug, gh_id, title, points_possible, deadline, accepted, "
            "submissions_count, passing_count, starter_code_repo, submittable_files) "
            "VALUES ('hw-01', 1, 'Homework 01', 10.0, '', 1, 1, 1, '', '')"
        )
        conn.execute(
            "INSERT INTO gh_submissions "
            "(github_username, assignment_slug, submitted, late, lateness_seconds, "
            "repo_name, commits_after_deadline, commit_count, passing, "
            "gh_autograder_score, last_commit_at, last_commit_sha, fetched_at) "
            "VALUES ('alice-gh', 'hw-01', 1, 0, 0, 'org/hw-01-alice-gh', 0, 3, 1, "
            "'10', '', '', '')"
        )
        _connection(conn).close()

        with (
            patch(
                "cass.actions.pull.matching_mod.fetch_course_name",
                return_value="Test Course 101",
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_students_with_sections",
                return_value=([], {}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_assignments",
                return_value=([], {}),
            ),
        ):
            from cass.actions.pull import pull_all_async

            asyncio.run(pull_all_async(cfg, on_progress=None))

        reopened = db.open_db(tmp_path)
        assert reopened["gh_students"].count == 0
        assert reopened["gh_assignments"].count == 0
        assert reopened["gh_submissions"].count == 0
        _connection(reopened).close()

    def test_partial_classroom_keeps_github_data_and_fails_clearly(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 0\n"
            'org = ""\n\n'
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        conn = db.open_db(tmp_path)
        conn.execute(
            "INSERT INTO gh_students "
            "(github_username, github_id, name, email, excluded) "
            "VALUES ('alice-gh', 1, 'Alice Smith', 'alice@test.edu', 0)"
        )
        _connection(conn).commit()
        _connection(conn).close()

        from cass.actions.pull import pull_all_async

        with pytest.raises(RuntimeError, match="gh-classroom ID is unresolved"):
            asyncio.run(pull_all_async(cfg, on_progress=None))

        db.reset()
        reopened = db.open_db(tmp_path)
        assert reopened["gh_students"].count == 1
        _connection(reopened).close()

    def test_with_github(self, tmp_path, monkeypatch, db_conn):
        """pull_all_async creates and closes a GitHubClient when configured."""
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 4200\n"
            'org = "test-org"\n\n'
            '[canvas]\nbase_url = "https://canvas.example.com"\n'
            "course_id = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        mock_students = [
            CanvasStudentResponse(id=100, name="Alice Smith", email="a@t.edu"),
        ]
        mock_gh_client = AsyncMock()

        with (
            patch(
                "cass.actions.pull.matching_mod.fetch_course_name",
                return_value="Test Course 101",
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_students_with_sections",
                return_value=(mock_students, {}),
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_canvas_assignments",
                return_value=([], {}),
            ),
            patch(
                "cass.actions.pull.GitHubClient",
                return_value=mock_gh_client,
            ),
            patch(
                "cass.actions.pull.classroom.fetch_all_students",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "cass.actions.pull.classroom.fetch_assignments",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from cass.actions.pull import pull_all_async

            asyncio.run(pull_all_async(cfg))

        mock_gh_client.close.assert_awaited_once()
        students = db.load_students()
        assert len(students) == 1

    def test_github_client_closed_on_error(self, tmp_path, monkeypatch, db_conn):
        """GitHubClient is closed even when pull raises after client creation."""
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 4200\n"
            'org = "test-org"\n\n'
            '[canvas]\nbase_url = "https://canvas.example.com"\n'
            "course_id = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        cfg = load_config()

        mock_students = [
            CanvasStudentResponse(id=100, name="Alice", email="a@t.edu"),
        ]
        mock_gh_client = AsyncMock()

        with (
            patch(
                "cass.actions.pull.matching_mod.fetch_course_name",
                return_value="Test Course 101",
            ),
            patch(
                "cass.actions.pull.matching_mod.fetch_students_with_sections",
                return_value=(mock_students, {}),
            ),
            patch(
                "cass.actions.pull.GitHubClient",
                return_value=mock_gh_client,
            ),
            patch(
                "cass.actions.pull.classroom.fetch_all_students",
                new_callable=AsyncMock,
                side_effect=RuntimeError("GH API down"),
            ),
        ):
            from cass.actions.pull import pull_all_async

            with pytest.raises(RuntimeError, match="GH API down"):
                asyncio.run(pull_all_async(cfg))

        # Client must be closed even though an error occurred
        mock_gh_client.close.assert_awaited_once()


class TestFetchGHSubmissions:
    """Tests for parallel _fetch_gh_submissions."""

    def test_fetch_gh_submissions_parallel(self, db_conn, monkeypatch) -> None:
        """All assignments' submissions are collected; on_status shows indices."""
        from cass.actions.pull import _fetch_gh_submissions
        from cass.db.schema import GHSubmission

        # Stub out roster-building DB calls
        monkeypatch.setattr(
            "cass.actions.pull.db.load_gh_student_handles", lambda: set()
        )

        assignments = [
            Assignment(
                slug=f"hw-0{i}",
                title=f"HW 0{i}",
                gh_assignment_slug=f"hw-0{i}",
            )
            for i in range(1, 4)
        ]
        students = [Student(canvas_id=1, github_username="alice")]

        async def mock_fetch(_client, slug, _deadline, _roster, **_kw):
            return [GHSubmission(github_username="alice", assignment_slug=slug)]

        monkeypatch.setattr("cass.actions.pull.classroom.fetch_submissions", mock_fetch)

        status_msgs: list[str] = []
        result = asyncio.run(
            _fetch_gh_submissions(
                object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
                assignments,
                students,
                ttl_hours=1.0,
                force_refresh=False,
                on_status=status_msgs.append,
            )
        )

        assert len(result) == 3
        slugs = {s.assignment_slug for s in result}
        assert slugs == {"hw-01", "hw-02", "hw-03"}
        # Status messages contain completion indices (1/3, 2/3, 3/3)
        assert len(status_msgs) == 3
        assert any("1/3" in m for m in status_msgs)
        assert any("3/3" in m for m in status_msgs)

    def test_fetch_gh_submissions_partial_failure(self, db_conn, monkeypatch) -> None:
        """One failing assignment doesn't prevent others from returning."""
        from cass.actions.pull import _fetch_gh_submissions
        from cass.db.schema import GHSubmission

        monkeypatch.setattr(
            "cass.actions.pull.db.load_gh_student_handles", lambda: set()
        )

        assignments = [
            Assignment(
                slug="hw-01",
                title="HW 01",
                gh_assignment_slug="hw-01",
            ),
            Assignment(
                slug="hw-02",
                title="HW 02",
                gh_assignment_slug="hw-02",
            ),
        ]
        students = [Student(canvas_id=1, github_username="alice")]

        async def mock_fetch(_client, slug, _deadline, _roster, **_kw):
            if slug == "hw-02":
                raise RuntimeError("API timeout")
            return [GHSubmission(github_username="alice", assignment_slug=slug)]

        monkeypatch.setattr("cass.actions.pull.classroom.fetch_submissions", mock_fetch)

        status_msgs: list[str] = []
        result = asyncio.run(
            _fetch_gh_submissions(
                object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
                assignments,
                students,
                ttl_hours=1.0,
                force_refresh=False,
                on_status=status_msgs.append,
            )
        )

        # Only hw-01 succeeds
        assert len(result) == 1
        assert result[0].assignment_slug == "hw-01"
        # Error reported in status
        assert any("ERROR" in m or "error" in m.lower() for m in status_msgs)
