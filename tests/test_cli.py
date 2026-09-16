"""CLI surface and workflow command tests."""

from __future__ import annotations

__docformat__ = "google"

import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlite_utils
from typer.testing import CliRunner

from cass import db
from cass.actions.config import load_config, reset_config
from cass.cli import app

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
            "canvas_students",
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

    def test_init_fresh_project_asks_only_for_canvas(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)
        monkeypatch.setattr(
            "cass.apis.canvas.matching.save_token",
            lambda token: (tmp_path / ".canvastoken").write_text(f"{token}\n"),
        )

        result = runner.invoke(
            app,
            ["init"],
            input="https://canvas.example.com/courses/99\nsecret-token\n",
        )

        assert result.exit_code == 0
        assert "GitHub" not in result.stdout
        cfg = load_config()
        assert cfg.canvas_base_url == "https://canvas.example.com"
        assert cfg.canvas_course_id == 99
        assert "[classroom]" not in (tmp_path / "cass.toml").read_text()

    def test_init_drops_stale_classroom_section(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\ngh_id = 4200\n\n"
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 7\n'
        )
        (tmp_path / ".canvastoken").write_text("secret-token\n")
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "[classroom]" not in (tmp_path / "cass.toml").read_text()
        assert "course_id = 7" in (tmp_path / "cass.toml").read_text()
        assert "Removed obsolete [classroom] section." in result.stdout


class TestSessionCookieAuth:
    def test_init_skips_token_prompt_when_creds_file_exists(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 7\n'
        )
        (tmp_path / ".canvascreds").write_text("canvas_session=abc\n")
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)

        result = runner.invoke(app, ["init"], input="\n")

        assert result.exit_code == 0
        assert "Canvas API token" not in result.stdout
        assert ".canvascreds" in result.stdout
        assert not (tmp_path / ".canvastoken").exists()

    def test_init_gitignores_both_credential_files(self, tmp_path):
        from cass.cli import ensure_token_gitignored

        (tmp_path / ".gitignore").write_text(".canvastoken\n")
        ensure_token_gitignored(tmp_path)
        lines = (tmp_path / ".gitignore").read_text().splitlines()
        assert lines.count(".canvastoken") == 1
        assert ".canvascreds" in lines

    def test_status_reports_auth_source(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CANVAS_TOKEN", raising=False)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        (tmp_path / ".canvascreds").write_text("canvas_session=abc\n")

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "session cookie (.canvascreds" in result.stdout

    def test_run_prints_auth_error_without_traceback(self, monkeypatch, capsys):
        from cass.apis.canvas.auth import CanvasAuthError
        from cass.cli import run

        def boom() -> None:
            raise CanvasAuthError("Canvas rejected the session cookie")

        monkeypatch.setattr("cass.cli.app", boom)
        with pytest.raises(SystemExit) as exc:
            run()
        assert exc.value.code == 1
        assert "Canvas rejected the session cookie" in capsys.readouterr().out


class TestCliErrors:
    def _run_with(self, monkeypatch, exc: Exception):
        from cass.cli import run

        def boom() -> None:
            raise exc

        monkeypatch.setattr("cass.cli.app", boom)
        with pytest.raises(SystemExit) as info:
            run()
        return info.value.code

    def test_run_prints_http_error_without_traceback(self, monkeypatch, capsys):
        import httpx

        req = httpx.Request("DELETE", "https://canvas.example.com/api/v1/modules/1")
        resp = httpx.Response(404, request=req, json={"errors": [{"message": "x"}]})
        exc = httpx.HTTPStatusError("nope", request=req, response=resp)
        assert self._run_with(monkeypatch, exc) == 1
        out = capsys.readouterr().out
        assert "404" in out
        assert "/modules/1" in out
        assert "Traceback" not in out

    def test_run_prints_runtime_error_without_traceback(self, monkeypatch, capsys):
        code = self._run_with(monkeypatch, RuntimeError("Assignment not found: nope"))
        assert code == 1
        out = capsys.readouterr().out
        assert "Assignment not found: nope" in out
        assert "Traceback" not in out


class TestReportHelpers:
    def test_due_renders_local_date(self, monkeypatch):
        from cass.cli.canvas import due

        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        # 23:59 PDT on Oct 1 is 06:59Z on Oct 2 — must still show Oct 1
        assert due("2026-10-02T06:59:00Z") == "2026-10-01"
        assert due("2026-10-01T23:59:00-07:00") == "2026-10-01"
        assert due(None) == ""

    def test_long_ids_fold_instead_of_truncating(self, monkeypatch, capsys):
        from rich.console import Console

        from cass.cli import report

        monkeypatch.setattr(report, "console", Console(width=40, force_terminal=False))
        report.render_list(
            ["Label", "Type", "ID"],
            [["Media Gallery", "external", "context_external_tool_5826"]],
        )
        out = capsys.readouterr().out
        assert "…" not in out
        # ID may wrap across lines but every character must survive
        assert "context_external_tool_5826" in "".join(
            line.split("│")[-1].strip() for line in out.splitlines() if "│" in line
        )

    def test_row_count_pluralizes(self, capsys):
        from cass.cli import report

        report.render_list(["A"], [["x"]])
        assert "1 row\n" in capsys.readouterr().out
        report.render_list(["A"], [["x"], ["y"]])
        assert "2 rows" in capsys.readouterr().out
        report.render_list(["A"], [])
        assert "0 rows" in capsys.readouterr().out


class TestCanvasModules:
    @pytest.fixture
    def modules_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasModule

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.list_modules.return_value = [
            CanvasModule(id=1, name="Week 1", position=1),
            CanvasModule(id=2, name="Week 2", position=2),
        ]
        fake.resolve_module.return_value = CanvasModule(id=1, name="Week 1", position=1)
        monkeypatch.setattr("cass.cli.canvas.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas.client", lambda: fake)
        return fake

    def test_publish_all_without_id(self, modules_client):
        result = runner.invoke(app, ["canvas", "modules", "publish", "--all"])
        assert result.exit_code == 0, result.output
        assert modules_client.publish.call_count == 2
        assert "Week 2" in result.stdout

    def test_publish_requires_id_or_all(self, modules_client):
        result = runner.invoke(app, ["canvas", "modules", "publish"])
        assert result.exit_code == 1
        assert "Give a module ID or name, or --all" in result.output
        modules_client.publish.assert_not_called()

    def test_add_item_defaults_title_to_content(self, modules_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "modules",
                "add-item",
                "Week 1",
                "--type",
                "Assignment",
                "--content-id",
                "42",
            ],
        )
        assert result.exit_code == 0, result.output
        modules_client.create_module_item.assert_called_once_with(
            1, item_type="Assignment", content_id=42, title=None
        )


class TestCanvasQuizzes:
    def test_create_has_no_points_option(self, monkeypatch):
        monkeypatch.setattr("cass.cli.canvas.require_canvas", lambda: None)
        result = runner.invoke(app, ["canvas", "quizzes", "create", "--help"])
        assert result.exit_code == 0
        assert "--points" not in result.stdout


class TestCanvasSync:
    def test_due_at_with_offset_is_idempotent(self, monkeypatch, tmp_path):
        from cass.apis.canvas.schema import CanvasAssignmentResponse

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
            '\n[[canvas.assignments]]\nname = "HW1"\npoints = 10\n'
            'due_at = "2026-10-01T23:59:00-07:00"\npublished = true\n'
        )
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.list_assignments.return_value = [
            CanvasAssignmentResponse(
                id=1,
                name="HW1",
                points_possible=10,
                due_at="2026-10-02T06:59:00Z",
                published=True,
            )
        ]
        monkeypatch.setattr("cass.cli.canvas.client", lambda: fake)

        result = runner.invoke(app, ["canvas", "sync"])
        assert result.exit_code == 0, result.output
        assert "0 create, 0 update, 1 skip" in result.stdout


class TestCanvasTabsAndFiles:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasFile, CanvasFolder, CanvasTab

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.resolve_tab.return_value = CanvasTab(
            id="context_external_tool_5826", label="Media Gallery"
        )
        fake.update_tab.return_value = CanvasTab(
            id="context_external_tool_5826", label="Media Gallery", hidden=True
        )
        fake.list_folders.return_value = [
            CanvasFolder(id=1, name="course files", full_name="course files")
        ]
        fake.list_files.return_value = [
            CanvasFile(id=18962999, display_name="notes.txt", size=20, folder_id=1)
        ]
        monkeypatch.setattr("cass.cli.canvas.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas.client", lambda: fake)
        return fake

    def test_hide_tab_resolves_by_label(self, fake_client):
        result = runner.invoke(app, ["canvas", "hide-tab", "Media Gallery"])
        assert result.exit_code == 0, result.output
        fake_client.resolve_tab.assert_called_once_with("Media Gallery")
        fake_client.update_tab.assert_called_once_with(
            "context_external_tool_5826", hidden=True
        )

    def test_show_tab_resolves_by_label(self, fake_client):
        result = runner.invoke(app, ["canvas", "show-tab", "media gallery"])
        assert result.exit_code == 0, result.output
        fake_client.update_tab.assert_called_once_with(
            "context_external_tool_5826", hidden=False
        )

    def test_files_tree_shows_ids(self, fake_client):
        result = runner.invoke(app, ["canvas", "files"])
        assert result.exit_code == 0, result.output
        assert "notes.txt" in result.stdout
        assert "18962999" in result.stdout


class TestCanvasAssignments:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        from cass.apis.canvas.schema import (
            CanvasAssignmentGroup,
            CanvasAssignmentResponse,
        )

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.list_assignment_groups.return_value = [
            CanvasAssignmentGroup(id=9, name="Labs", position=1)
        ]
        fake.resolve_assignment_group.return_value = CanvasAssignmentGroup(
            id=9, name="Labs", position=1
        )
        fake.create_assignment_group.return_value = CanvasAssignmentGroup(
            id=10, name="Homeworks", position=2, group_weight=40.0
        )
        fake.create_assignment.return_value = CanvasAssignmentResponse(id=1, name="HW1")
        monkeypatch.setattr("cass.cli.canvas.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas.client", lambda: fake)
        return fake

    def test_create_passes_description(self, fake_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "assignments",
                "create",
                "HW1",
                "--group",
                "Labs",
                "-d",
                "<p>Do it</p>",
            ],
        )
        assert result.exit_code == 0, result.output
        kwargs = fake_client.create_assignment.call_args.kwargs
        assert kwargs["description"] == "<p>Do it</p>"
        assert kwargs["assignment_group_id"] == 9

    def test_groups_lists(self, fake_client):
        result = runner.invoke(app, ["canvas", "assignments", "groups"])
        assert result.exit_code == 0, result.output
        assert "Labs" in result.stdout

    def test_groups_create(self, fake_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "assignments",
                "groups",
                "create",
                "Homeworks",
                "--weight",
                "40",
                "--position",
                "2",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "id=10" in result.stdout
        fake_client.create_assignment_group.assert_called_once_with(
            "Homeworks", position=2, group_weight=40.0
        )

    def test_groups_delete(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "assignments", "groups", "delete", "Labs", "-y"]
        )
        assert result.exit_code == 0, result.output
        fake_client.resolve_assignment_group.assert_called_once_with("Labs")
        fake_client.delete_assignment_group.assert_called_once_with(9)


class TestCanvasCalendar:
    def test_when_converts_utc_to_local(self, monkeypatch):
        from cass.cli.canvas import when

        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        assert when("2026-09-22T17:00:00Z") == "2026-09-22 10:00"
        assert when(None) == ""

    @pytest.fixture
    def calendar_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasCalendarEvent

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.list_calendar_events.return_value = [
            CanvasCalendarEvent(
                id=234,
                title="Midterm review",
                start_at="2026-10-19T15:00:00-07:00",
                end_at="2026-10-19T16:00:00-07:00",
                location_name="Room 237",
            ),
            CanvasCalendarEvent(
                id=236,
                title="Holiday",
                start_at="2026-10-20T07:00:00Z",
                end_at="2026-10-20T07:00:00Z",
                all_day=True,
                all_day_date="2026-10-20",
            ),
        ]
        fake.create_calendar_event.return_value = CanvasCalendarEvent(
            id=235, title="Office hours"
        )
        fake.update_calendar_event.return_value = CanvasCalendarEvent(
            id=235, title="OH (moved)"
        )
        monkeypatch.setattr("cass.cli.canvas.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas.client", lambda: fake)
        return fake

    def test_list_renders_events(self, calendar_client):
        result = runner.invoke(app, ["canvas", "calendar"])
        assert result.exit_code == 0, result.output
        assert "Midterm review" in result.stdout
        assert "Room 237" in result.stdout
        assert "Holiday" in result.stdout
        calendar_client.list_calendar_events.assert_called_once_with(
            start_date=None, end_date=None
        )

    def test_list_shows_all_day_date_not_utc_midnight(
        self, calendar_client, monkeypatch
    ):
        # UTC+9: 2026-10-20T07:00Z would render as 2026-10-20 16:00 if converted
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        time.tzset()
        result = runner.invoke(app, ["canvas", "calendar"])
        assert result.exit_code == 0, result.output
        holiday = next(line for line in result.stdout.splitlines() if "Holiday" in line)
        assert "2026-10-20" in holiday
        assert "16:00" not in holiday

    def test_list_passes_date_range(self, calendar_client):
        result = runner.invoke(
            app, ["canvas", "calendar", "--from", "2026-10-01", "--to", "2026-10-31"]
        )
        assert result.exit_code == 0, result.output
        calendar_client.list_calendar_events.assert_called_once_with(
            start_date="2026-10-01", end_date="2026-10-31"
        )

    def test_create(self, calendar_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "calendar",
                "create",
                "Office hours",
                "--start",
                "2026-10-20T10:00:00",
                "--end",
                "2026-10-20T11:00:00",
                "--location",
                "Room 237",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "id=235" in result.stdout
        calendar_client.create_calendar_event.assert_called_once_with(
            "Office hours",
            start_at="2026-10-20T10:00:00",
            end_at="2026-10-20T11:00:00",
            description=None,
            location_name="Room 237",
            all_day=False,
        )

    def test_update_only_sends_given_fields(self, calendar_client):
        result = runner.invoke(
            app, ["canvas", "calendar", "update", "235", "--title", "OH (moved)"]
        )
        assert result.exit_code == 0, result.output
        calendar_client.update_calendar_event.assert_called_once_with(
            235, title="OH (moved)"
        )

    def test_update_with_nothing_to_change(self, calendar_client):
        result = runner.invoke(app, ["canvas", "calendar", "update", "235"])
        assert result.exit_code == 0, result.output
        assert "Nothing to update" in result.stdout
        calendar_client.update_calendar_event.assert_not_called()

    def test_delete_with_yes(self, calendar_client):
        result = runner.invoke(app, ["canvas", "calendar", "delete", "235", "-y"])
        assert result.exit_code == 0, result.output
        calendar_client.delete_calendar_event.assert_called_once_with(235)
