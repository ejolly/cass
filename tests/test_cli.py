"""CLI surface and workflow command tests."""

from __future__ import annotations

__docformat__ = "google"

import shutil
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlite_utils
from typer.testing import CliRunner

from cass import db
from cass.actions.config import load_config, reset_config
from cass.cli import app
from cass.db.schema import Assignment, Student

runner = CliRunner()

_TESTDB = Path(__file__).parent / "testdb" / "cass.db"


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    yield
    reset_config()


@pytest.fixture
def project_db(project_dir, monkeypatch):
    if not _TESTDB.exists():
        pytest.skip("No test snapshot — run 'uv run poe seed-testdb'")
    monkeypatch.chdir(project_dir)
    copy = project_dir / "cass.db"
    shutil.copy2(_TESTDB, copy)
    sdb = sqlite_utils.Database(str(copy))
    monkeypatch.setattr("cass.db.core._db", sdb)
    return sdb


def _sample_assignment_id(sdb: sqlite_utils.Database) -> int:
    row = sdb.execute(
        "SELECT canvas_id FROM canvas_assignments ORDER BY canvas_id LIMIT 1"
    ).fetchone()
    assert row is not None
    return int(row[0])


class TestCliSurface:
    def test_bare_cli_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage:" in result.stdout
        assert "status" in result.stdout

    def test_top_level_help_lists_new_surface(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in (
            "status",
            "pull",
            "push",
            "revert",
            "query",
            "delete",
            "backup",
            "restore",
            "view",
            "canvas",
        ):
            assert command in result.stdout

    def test_removed_commands_do_not_appear(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in ("gradebook", "export", "import", "drop"):
            assert command not in result.stdout


class TestStatus:
    def test_status_without_config(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No cass.toml found" in result.stdout

    def test_status_with_db_and_pending(self, project_db):
        canvas_id = _sample_assignment_id(project_db)
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "cass status" in result.stdout
        assert "students:" in result.stdout
        assert "assignments:" in result.stdout
        assert "pending change" in result.stdout

    def test_status_shows_pending_github_setup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 0\n"
            'org = ""\n\n'
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "gh ID unresolved" in result.stdout


class TestPull:
    def test_pull_blocks_when_pending(self, project_db):
        canvas_id = _sample_assignment_id(project_db)
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )

        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 1
        assert "Pull blocked" in result.stdout
        assert "cass push" in result.stdout
        assert "cass revert" in result.stdout


class TestPullRepos:
    def test_pull_repos_passes_filtered_assignments_to_shared_fetch(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 4200\n"
            'org = "test-org"\n\n'
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )

        assignments = [
            Assignment(
                slug="hw-01",
                title="HW 01",
                gh_assignment_slug="hw-01",
                canvas_assignment_id=1,
                points_possible=10.0,
                deadline=None,
            ),
            Assignment(
                slug="lab-02",
                title="Lab 02",
                gh_assignment_slug="lab-02",
                canvas_assignment_id=2,
                points_possible=10.0,
                deadline=None,
            ),
        ]
        students = [
            Student(canvas_id=1, name="Alice", github_username="alice-gh"),
        ]
        captured_targets: list[Assignment] = []
        captured_roster: list[Student] = []

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        async def fake_pull_gh(client, targets, roster, **kwargs):
            del client, kwargs
            captured_targets.extend(targets)
            captured_roster.extend(roster)
            return {
                "cloned": 0,
                "updated": 0,
                "up_to_date": 1,
                "skipped": 0,
                "errors": 0,
            }

        monkeypatch.setattr("cass.db.load_students", lambda: students)
        monkeypatch.setattr("cass.db.load_assignments", lambda: assignments)
        monkeypatch.setattr("cass.apis.github.client.GitHubClient", FakeClient)
        monkeypatch.setattr("cass.apis.github.fetch.pull_gh", fake_pull_gh)

        result = runner.invoke(app, ["pull-repos", "--assignment", "hw-01"])

        assert result.exit_code == 0
        assert [a.slug for a in captured_targets] == ["hw-01"]
        assert captured_roster == students


class TestView:
    def test_view_uses_project_root(self, project_db, monkeypatch):
        mock = MagicMock()
        monkeypatch.setattr("cass.viewer.nicegui_app.start_nicegui_server", mock)

        result = runner.invoke(app, ["view", "--port", "8123"])
        assert result.exit_code == 0
        mock.assert_called_once()
        assert mock.call_args.kwargs["port"] == 8123
        assert mock.call_args.kwargs["project_root"] == Path(db.db_path()).parent


class TestPush:
    def test_push_no_pending_changes(self, project_db):
        result = runner.invoke(app, ["push"])
        assert result.exit_code == 0
        assert "No pending Canvas changes to push" in result.stdout

    def test_push_preview_decline_aborts(self, project_db, monkeypatch):
        canvas_id = _sample_assignment_id(project_db)
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )
        monkeypatch.setattr(
            "cass.db.canvas_preview",
            lambda conn, pending: {
                "ok": True,
                "changes": [
                    {
                        "table": "canvas_assignments",
                        "name": "Assignment",
                        "column": "name",
                        "baseline": "hw-01",
                        "current": "Renamed",
                        "live": "hw-01",
                    }
                ],
                "has_conflicts": False,
                "has_errors": False,
            },
        )
        apply_mock = MagicMock(return_value={"ok": True, "results": []})
        monkeypatch.setattr("cass.db.canvas_apply", apply_mock)

        result = runner.invoke(app, ["push"], input="n\n")
        assert result.exit_code == 1
        assert "Canvas Push Preview" in result.stdout
        apply_mock.assert_not_called()

    def test_push_yes_bypasses_confirmation(self, project_db, monkeypatch):
        canvas_id = _sample_assignment_id(project_db)
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )
        monkeypatch.setattr(
            "cass.db.canvas_preview",
            lambda conn, pending: {
                "ok": True,
                "changes": [
                    {
                        "table": "canvas_assignments",
                        "name": "Assignment",
                        "column": "name",
                        "baseline": "hw-01",
                        "current": "Renamed",
                        "live": "hw-01",
                    }
                ],
                "has_conflicts": False,
                "has_errors": False,
            },
        )
        monkeypatch.setattr(
            "cass.db.canvas_apply",
            lambda conn, pending: {
                "ok": True,
                "results": [
                    {
                        "ok": True,
                        "canvas_assignment_id": canvas_id,
                        "count": 1,
                    }
                ],
            },
        )

        result = runner.invoke(app, ["push", "--yes"])
        assert result.exit_code == 0
        assert "Pushed 1 grades/updates" in result.stdout


class TestRevert:
    def test_revert_no_pending_changes(self, project_db):
        result = runner.invoke(app, ["revert"])
        assert result.exit_code == 0
        assert "No pending changes to revert" in result.stdout

    def test_revert_yes_bypasses_confirmation(self, project_db):
        canvas_id = _sample_assignment_id(project_db)
        old_name = project_db.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?", [canvas_id]
        ).fetchone()[0]
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )

        result = runner.invoke(app, ["revert", "--yes"])
        assert result.exit_code == 0
        assert "Reverted 1 change" in result.stdout

        row = project_db.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [canvas_id],
        ).fetchone()
        assert row is not None
        assert row[0] == old_name


class TestQuery:
    def test_query_known_dataset_delegates_rows(self, project_db, monkeypatch):
        mock = MagicMock(return_value="students table\n")
        monkeypatch.setattr("cass.cli.render_rows", mock)

        result = runner.invoke(app, ["query", "students", "--limit", "5"])
        assert result.exit_code == 0
        assert "students table" in result.stdout
        mock.assert_called_once_with(
            db.db_path(),
            "students",
            where="",
            order="",
            limit=5,
        )

    def test_query_unknown_dataset_errors(self, project_db):
        result = runner.invoke(app, ["query", "unknown"])
        assert result.exit_code == 1
        assert "Unknown dataset" in result.stdout

    def test_query_sql_mode_delegates(self, project_db, monkeypatch):
        mock = MagicMock(return_value="count\n")
        monkeypatch.setattr("cass.cli.render_query", mock)

        result = runner.invoke(app, ["query", "--sql", "select count(*) from students"])
        assert result.exit_code == 0
        assert "count" in result.stdout
        mock.assert_called_once()

    def test_query_dataset_and_sql_conflict(self, project_db):
        result = runner.invoke(app, ["query", "students", "--sql", "select 1"])
        assert result.exit_code == 1
        assert "either a dataset or --sql" in result.stdout

    def test_query_missing_sqlite_utils_is_actionable(self, project_db, monkeypatch):
        monkeypatch.setattr(
            "cass.cli.render_rows",
            MagicMock(side_effect=RuntimeError("`sqlite-utils` is not installed")),
        )

        result = runner.invoke(app, ["query", "students"])
        assert result.exit_code == 1
        assert "sqlite-utils" in result.stdout

    def test_gradebook_query_renders_shared_matrix(self, project_db):
        result = runner.invoke(app, ["query", "gradebook", "--limit", "2"])
        assert result.exit_code == 0
        assert "Gradebo" in result.stdout
        # "Student" header may be truncated to "Stude…" in narrow terminals
        assert "Stude" in result.stdout


class TestInit:
    def test_init_repairs_missing_token_without_reasking_for_canvas(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 7\n\n'
            '[[canvas.assignments]]\nname = "HW1"\npoints = 10\n'
        )
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)
        monkeypatch.setattr(
            "cass.apis.canvas.matching.save_token",
            lambda token: (tmp_path / ".canvastoken").write_text(f"{token}\n"),
        )

        result = runner.invoke(app, ["init"], input="secret-token\n\n")

        assert result.exit_code == 0
        assert "Canvas course URL" not in result.stdout
        assert "Canvas course ID" not in result.stdout
        assert (tmp_path / ".canvastoken").read_text() == "secret-token\n"
        assert (
            '[[canvas.assignments]]\nname = "HW1"'
            in (tmp_path / "cass.toml").read_text()
        )

    def test_init_uses_urls_for_canvas_and_github(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)
        monkeypatch.setattr(
            "cass.apis.canvas.matching.save_token",
            lambda token: (tmp_path / ".canvastoken").write_text(f"{token}\n"),
        )
        from cass.apis.github.service import (
            ClassroomResolutionResult,
            ResolvedClassroom,
        )

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            lambda classroom_url: ClassroomResolutionResult(
                url=classroom_url,
                url_id=123456,
                resolved=ResolvedClassroom(
                    url=classroom_url,
                    url_id=123456,
                    gh_id=4200,
                    slug="test-course",
                    title="Test Course",
                    org="test-org",
                ),
                gh_account="ejolly",
            ),
        )

        result = runner.invoke(
            app,
            ["init"],
            input=(
                "https://canvas.example.com/courses/99\n"
                "secret-token\n"
                "https://classroom.github.com/classrooms/123456-test-course\n"
            ),
        )

        assert result.exit_code == 0
        assert "Canvas course ID" not in result.stdout
        assert "GitHub org" not in result.stdout
        assert "Classroom ID" not in result.stdout
        assert "ejolly" in result.stdout

        cfg = load_config()
        assert cfg.canvas_base_url == "https://canvas.example.com"
        assert cfg.canvas_course_id == 99
        assert (
            cfg.classroom_url
            == "https://classroom.github.com/classrooms/123456-test-course"
        )
        assert cfg.classroom_url_id == 123456
        assert cfg.classroom_gh_id == 4200
        assert cfg.org == "test-org"

    def test_init_saves_partial_classroom_when_github_resolution_fails(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)
        monkeypatch.setattr(
            "cass.apis.canvas.matching.save_token",
            lambda token: (tmp_path / ".canvastoken").write_text(f"{token}\n"),
        )
        from cass.apis.github.service import ClassroomResolutionResult

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            lambda classroom_url: ClassroomResolutionResult(
                url=classroom_url,
                url_id=42,
                error_code="gh_auth_invalid",
                error_detail="GitHub authentication is invalid.",
                recovery_hint="Run `gh auth login -h github.com`.",
            ),
        )

        result = runner.invoke(
            app,
            ["init"],
            input=(
                "https://canvas.example.com/courses/7\n"
                "secret-token\n"
                "https://classroom.github.com/classrooms/42-test-course\n"
            ),
        )

        assert result.exit_code == 0
        cfg = load_config()
        assert cfg.classroom_url_id == 42
        assert cfg.classroom_gh_id == 0
        assert cfg.org == ""
        assert cfg.classroom_needs_resolution is True
        assert "setup is incomplete" in result.stdout

    def test_init_retries_unresolved_classroom_before_prompting(
        self, tmp_path, monkeypatch
    ):
        """Rerunning init with a saved unresolved classroom auto-retries."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 0\n"
            '\n[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        (tmp_path / ".canvastoken").write_text("secret-token\n")
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)
        monkeypatch.setattr(
            "cass.apis.canvas.matching.save_token",
            lambda token: None,
        )

        from cass.apis.github.service import (
            ClassroomResolutionResult,
            ResolvedClassroom,
        )

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            lambda url: ClassroomResolutionResult(
                url=url,
                url_id=42,
                resolved=ResolvedClassroom(
                    url=url,
                    url_id=42,
                    gh_id=4200,
                    slug="course",
                    title="My Course",
                    org="test-org",
                ),
                gh_account="ejolly",
            ),
        )

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "retrying resolution" in result.stdout
        assert "GitHub Classroom configured" in result.stdout
        cfg = load_config()
        assert cfg.classroom_gh_id == 4200

    def test_init_shows_auth_failure_on_retry(self, tmp_path, monkeypatch):
        """Retry shows specific failure when auth is bad."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 0\n"
            '\n[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        (tmp_path / ".canvastoken").write_text("secret-token\n")
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)
        monkeypatch.setattr(
            "cass.apis.canvas.matching.save_token",
            lambda token: None,
        )

        from cass.apis.github.service import ClassroomResolutionResult

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            lambda url: ClassroomResolutionResult(
                url=url,
                url_id=42,
                error_code="gh_auth_invalid",
                error_detail="GitHub authentication is invalid.",
                recovery_hint="Run `gh auth login -h github.com`.",
            ),
        )

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "retrying resolution" in result.stdout
        assert "setup is incomplete" in result.stdout
        assert "gh auth login" in result.stdout
