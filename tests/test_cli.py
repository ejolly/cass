"""CLI surface and workflow command tests."""

from __future__ import annotations

__docformat__ = "google"

import json
import re
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlite_utils
import typer.main
from typer.testing import CliRunner

from cass import db
from cass.actions.config import load_config, reset_config
from cass.cli import app

runner = CliRunner()

_TESTDB = Path(__file__).parent / "testdb" / "cass.db"


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    from cass.actions.config import set_config_path

    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture(autouse=True)
def stub_course_time_zone(monkeypatch):
    monkeypatch.setattr(
        "cass.apis.canvas.matching.fetch_course_time_zone",
        lambda: "America/Los_Angeles",
    )


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
    def test_canvas_subcommands(self):
        canvas = typer.main.get_command(app).commands["canvas"]  # ty: ignore[unresolved-attribute]
        assert set(canvas.commands) == {
            "people",
            "modules",
            "assignments",
            "quizzes",
            "calendar",
            "files",
            "announcements",
            "tabs",
            "login",
            "sync",
            "api",
        }

    def test_only_prompt_helper_calls_typer_confirm(self):
        root = Path(__file__).parents[1]
        users = [
            path.relative_to(root).as_posix()
            for path in (root / "cass" / "cli").rglob("*.py")
            if "typer.confirm" in path.read_text()
        ]
        assert users == ["cass/cli/prompts.py"]

    def test_only_allowed_console_instances(self):
        root = Path(__file__).parents[1]
        counts = {
            path.relative_to(root).as_posix(): path.read_text().count("Console(")
            for path in (root / "cass" / "cli").rglob("*.py")
        }
        assert {name: n for name, n in counts.items() if n} == {
            "cass/cli/__init__.py": 2,
            "cass/cli/canvas/_common.py": 2,
            "cass/cli/report.py": 1,
        }

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

    def test_version_matches_package_metadata(self):
        from importlib.metadata import version

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.stdout.strip() == f"cass {version('cassroom')}"


class TestStreams:
    def test_hint_goes_to_stderr_during_quizzes_list(self, monkeypatch):
        import httpx

        from cass.apis.canvas.client import CanvasClient

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/courses/1":
                return httpx.Response(
                    200, json={"id": 1, "time_zone": "America/Los_Angeles"}
                )
            if request.url.path == "/api/v1/courses/1/quizzes":
                return httpx.Response(
                    200, json=[{"id": 3, "title": "Quiz A", "quiz_type": "survey"}]
                )
            return httpx.Response(404)

        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr(
            "cass.cli.canvas._common.client",
            lambda dry_run=False: CanvasClient(
                "https://canvas.example.com",
                token="t",
                course_id=1,
                transport=httpx.MockTransport(handler),
            ),
        )
        result = runner.invoke(app, ["canvas", "quizzes", "list"])
        assert result.exit_code == 0, result.output
        assert "Quiz A" in result.stdout
        assert "time zone" not in result.stdout
        assert "Course time zone is not in cass.toml" in result.stderr


class TestConfigOption:
    @pytest.fixture
    def two_projects(self, tmp_path):
        f25 = tmp_path / "f25"
        f25.mkdir()
        (f25 / "cass_f25.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 25\n'
        )
        cwd = tmp_path / "f26"
        cwd.mkdir()
        return f25 / "cass_f25.toml", cwd

    def test_config_flag_uses_files_directory(self, two_projects, monkeypatch):
        path, cwd = two_projects
        monkeypatch.chdir(cwd)
        result = runner.invoke(app, ["--config", str(path), "status"])
        assert result.exit_code == 0, result.output
        assert "cass_f25.toml" in result.stdout

    def test_cass_config_env(self, two_projects, monkeypatch):
        path, cwd = two_projects
        monkeypatch.chdir(cwd)
        result = runner.invoke(app, ["status"], env={"CASS_CONFIG": str(path)})
        assert result.exit_code == 0, result.output
        assert "cass_f25.toml" in result.stdout

    def test_missing_config_exits_with_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["--config", "nope.toml", "status"])
        assert result.exit_code == 1
        assert "nope.toml" in result.output


class TestStatus:
    def test_status_without_config(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No cass.toml found" in result.stderr

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


STATUS_JSON_KEYS = {
    "config_path",
    "course_url",
    "course_id",
    "auth_source",
    "db_path",
    "course_name",
    "counts",
    "pending_changes",
}


class TestStatusJson:
    def test_status_json_without_config(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "No cass.toml found" in result.stderr

    def test_status_json_without_db(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert set(data) == STATUS_JSON_KEYS
        for key in ("db_path", "course_name", "counts", "pending_changes"):
            assert data[key] is None

    def test_status_json_with_db(self, project_db):
        canvas_id = _sample_assignment_id(project_db)
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert set(data["counts"]) == {"students", "assignments", "submissions"}
        assert data["counts"]["students"] > 0
        assert data["pending_changes"] >= 1
        assert data["db_path"].endswith("cass.db")


class TestPull:
    def test_pull_blocks_when_pending(self, project_db):
        canvas_id = _sample_assignment_id(project_db)
        project_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )

        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 1
        assert "Pull blocked" in result.stderr
        assert "cass push" in result.stderr
        assert "cass revert" in result.stderr


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
        assert "No pending Canvas changes to push" in result.stderr

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

        monkeypatch.setattr("cass.cli.prompts._stdin_is_tty", lambda: True)
        result = runner.invoke(app, ["push"], input="n\n")
        assert result.exit_code == 1
        assert "Canvas Push Preview" in result.stdout
        apply_mock.assert_not_called()

    def test_push_dry_run_keeps_pending(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        sdb = sqlite_utils.Database(str(project_dir / "cass.db"))
        db.init_schema(sdb)
        monkeypatch.setattr("cass.db.core._db", sdb)
        sdb["canvas_assignments"].insert(
            {"canvas_id": 7, "name": "HW1", "points_possible": 10, "published": 1}
        )
        db.snapshot_canvas_synced(sdb)
        sdb.execute("UPDATE canvas_assignments SET name = 'HW 1'")
        before = db.get_pending_changes(sdb)
        assert before
        monkeypatch.setattr(
            "cass.db.canvas_preview",
            lambda conn, pending: {
                "ok": True,
                "changes": [
                    {
                        "table": "canvas_assignments",
                        "name": "Assignment",
                        "column": "name",
                        "baseline": "HW1",
                        "current": "HW 1",
                        "live": "HW1",
                    }
                ],
                "has_conflicts": False,
                "has_errors": False,
            },
        )
        apply_mock = MagicMock(return_value={"ok": True, "results": []})
        monkeypatch.setattr("cass.db.canvas_apply", apply_mock)

        result = runner.invoke(app, ["push", "--dry-run"])
        assert result.exit_code == 0
        assert "Canvas Push Preview" in result.stdout
        assert "Dry run" not in result.stdout
        assert "Dry run: nothing pushed" in result.stderr
        apply_mock.assert_not_called()
        assert db.get_pending_changes(sdb) == before

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

    def test_push_warnings_and_failures_go_to_stderr(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        sdb = sqlite_utils.Database(str(project_dir / "cass.db"))
        db.init_schema(sdb)
        monkeypatch.setattr("cass.db.core._db", sdb)
        sdb["canvas_assignments"].insert(
            {"canvas_id": 7, "name": "HW1", "points_possible": 10, "published": 1}
        )
        db.snapshot_canvas_synced(sdb)
        sdb.execute("UPDATE canvas_assignments SET name = 'HW 1'")
        monkeypatch.setattr(
            "cass.db.canvas_preview",
            lambda conn, pending: {
                "ok": True,
                "changes": [
                    {"table": "canvas_assignments", "name": "A", "column": "name"}
                ],
                "has_conflicts": True,
                "has_errors": True,
            },
        )
        monkeypatch.setattr(
            "cass.db.canvas_apply",
            lambda conn, pending: {
                "ok": False,
                "results": [{"ok": False, "canvas_id": 7, "error": "boom"}],
            },
        )

        result = runner.invoke(app, ["push", "--yes"])
        assert "Canvas Push Preview" in result.stdout
        for text in (
            "Conflicts detected",
            "Preview errors detected",
            "boom",
            "Failed 1",
        ):
            assert text in result.stderr
            assert text not in result.stdout
        assert "Pushed 0 grades/updates" in result.stdout


class TestRevert:
    def test_revert_no_pending_changes(self, project_db):
        result = runner.invoke(app, ["revert"])
        assert result.exit_code == 0
        assert "No pending changes to revert" in result.stderr

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


class TestRestore:
    def test_restore_summary_counts_canvas_tables(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        backup = project_dir / "backup.db"
        bdb = sqlite_utils.Database(str(backup))
        db.init_schema(bdb)
        bdb["canvas_students"].insert_all(
            [
                {"canvas_id": 1, "name": "Alice"},
                {"canvas_id": 2, "name": "Bob"},
            ]
        )
        bdb["canvas_assignments"].insert({"canvas_id": 10, "name": "HW 01"})
        bdb.conn.close()

        monkeypatch.setattr("cass.cli.prompts._stdin_is_tty", lambda: True)
        result = runner.invoke(app, ["restore", str(backup)], input="n\n")

        assert "Students: 2, Assignments: 1" in result.stderr


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
        assert "Unknown dataset" in result.stderr

    def test_query_sql_mode_delegates(self, project_db, monkeypatch):
        mock = MagicMock(return_value="count\n")
        monkeypatch.setattr("cass.cli.render_query", mock)

        result = runner.invoke(
            app, ["query", "--sql", "select count(*) from canvas_students"]
        )
        assert result.exit_code == 0
        assert "count" in result.stdout
        mock.assert_called_once()

    def test_query_dataset_and_sql_conflict(self, project_db):
        result = runner.invoke(app, ["query", "students", "--sql", "select 1"])
        assert result.exit_code == 1
        assert "either a dataset or --sql" in result.stderr

    def test_query_missing_sqlite_utils_is_actionable(self, project_db, monkeypatch):
        monkeypatch.setattr(
            "cass.cli.render_rows",
            MagicMock(side_effect=RuntimeError("`sqlite-utils` is not installed")),
        )

        result = runner.invoke(app, ["query", "students"])
        assert result.exit_code == 1
        assert "sqlite-utils" in result.stderr

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
        assert "Canvas course URL" not in result.stderr
        assert "Canvas course ID" not in result.stderr
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
        assert "GitHub" not in result.stderr
        cfg = load_config()
        assert cfg.canvas_base_url == "https://canvas.example.com"
        assert cfg.canvas_course_id == 99
        assert "[classroom]" not in (tmp_path / "cass.toml").read_text()

    def test_init_writes_time_zone(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 7\n'
        )
        (tmp_path / ".canvastoken").write_text("secret-token\n")
        monkeypatch.setattr("cass.actions.doctor.check_prerequisites", list)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (
            'time_zone = "America/Los_Angeles"' in (tmp_path / "cass.toml").read_text()
        )

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
        assert "Removed obsolete [classroom] section." in result.stderr


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
        assert "Canvas API token" not in result.stderr
        assert ".canvascreds" in result.stderr
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
        assert "Canvas rejected the session cookie" in capsys.readouterr().err


class TestCliErrors:
    @pytest.fixture(autouse=True)
    def no_debug(self, monkeypatch):
        monkeypatch.setenv("CASS_DEBUG", "")

    def _run_with(self, monkeypatch, exc: BaseException):
        from cass.cli import run

        def boom() -> None:
            raise exc

        monkeypatch.setattr("cass.cli.app", boom)
        with pytest.raises(SystemExit) as info:
            run()
        return info.value.code

    @pytest.mark.parametrize(
        ("make_exc", "expected"),
        [
            (
                lambda: _auth_error("Canvas rejected the API token"),
                ["Canvas rejected the API token"],
            ),
            (
                lambda: _api_error(
                    404, "DELETE", {"errors": [{"message": "does not exist"}]}
                ),
                ["DELETE /courses/1/modules/9 → 404: does not exist"],
            ),
            (
                lambda: _plain_http_error(500, {"message": "boom"}),
                ["500", "boom"],
            ),
            (
                lambda: __import__("httpx").ConnectError("refused"),
                ["Could not reach Canvas: refused"],
            ),
            (
                lambda: RuntimeError("Assignment not found: nope"),
                ["Assignment not found: nope"],
            ),
            (
                lambda: SystemExit("Canvas credentials not found."),
                ["Canvas credentials not found."],
            ),
        ],
    )
    def test_run_reports_error_cleanly(self, monkeypatch, capsys, make_exc, expected):
        assert self._run_with(monkeypatch, make_exc()) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        for text in expected:
            assert text in captured.err
        assert "Traceback" not in captured.err

    def test_run_passes_int_exit_codes(self, monkeypatch, capsys):
        assert self._run_with(monkeypatch, SystemExit(2)) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_debug_flag_reraises(self, monkeypatch):
        import sys

        from cass.cli import run
        from cass.cli.canvas import _common

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.list_quizzes.side_effect = RuntimeError("boom")
        monkeypatch.setattr(_common, "require_canvas", lambda: None)
        monkeypatch.setattr(_common, "client", lambda **_: fake)
        monkeypatch.setattr(sys, "argv", ["cass", "--debug", "canvas", "quizzes"])
        with pytest.raises(RuntimeError, match="boom"):
            run()

    def test_cass_debug_env_reraises(self, monkeypatch):
        monkeypatch.setenv("CASS_DEBUG", "1")
        from cass.cli import run

        def boom() -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr("cass.cli.app", boom)
        with pytest.raises(RuntimeError, match="boom"):
            run()

    def test_cass_debug_zero_is_off(self, monkeypatch, capsys):
        monkeypatch.setenv("CASS_DEBUG", "0")
        assert self._run_with(monkeypatch, RuntimeError("boom")) == 1
        assert "Traceback" not in capsys.readouterr().err

    def test_pull_runtime_error_reaches_root(self, project_dir, monkeypatch, capsys):
        import sys

        from cass.cli import run

        def fail(*_args, **_kwargs):
            raise RuntimeError("pull failed")

        monkeypatch.chdir(project_dir)
        monkeypatch.setattr("cass.db.pull_block_reason", lambda: None)
        monkeypatch.setattr("cass.actions.pull.pull_all", fail)
        monkeypatch.setattr(sys, "argv", ["cass", "pull"])
        with pytest.raises(SystemExit) as info:
            run()
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "pull failed" in err
        assert "Traceback" not in err

    @pytest.mark.parametrize(
        "args", [["canvas", "quizzes", "nope"], ["canvas", "nope"]]
    )
    def test_usage_errors_exit_2(self, args):
        assert runner.invoke(app, args).exit_code == 2


def _auth_error(message: str) -> Exception:
    from cass.apis.canvas.auth import CanvasAuthError

    return CanvasAuthError(message)


def _error_response(status: int, method: str, body: dict):
    import httpx

    request = httpx.Request(
        method, "https://canvas.example.com/api/v1/courses/1/modules/9"
    )
    return httpx.Response(status, request=request, json=body)


def _api_error(status: int, method: str, body: dict) -> Exception:
    from cass.apis.canvas.errors import CanvasAPIError

    return CanvasAPIError(_error_response(status, method, body))


def _plain_http_error(status: int, body: dict) -> Exception:
    import httpx

    response = _error_response(status, "DELETE", body)
    return httpx.HTTPStatusError("failed", request=response.request, response=response)


class TestReportHelpers:
    def test_due_renders_course_date(self):
        from cass.cli.canvas import due

        # 23:59 PDT on Oct 1 is 06:59Z on Oct 2 — must still show Oct 1
        assert due("2026-10-02T06:59:00Z", "America/Los_Angeles") == "2026-10-01"
        assert due("2026-10-01T23:59:00-07:00", "America/Los_Angeles") == "2026-10-01"
        assert due(None, "America/Los_Angeles") == ""

    def test_id_column_stays_on_one_line(self, monkeypatch, capsys):
        from rich.console import Console

        from cass.cli import report

        monkeypatch.setattr(report, "console", Console(width=80, force_terminal=False))
        report.render_list(
            ["Label", "Type", "Position", "Visibility", "ID"],
            [
                [
                    "Media Gallery",
                    "external",
                    "3",
                    "visible",
                    "context_external_tool_5826",
                ],
                [
                    "A much longer navigation label here",
                    "external",
                    "4",
                    "hidden",
                    "context_external_tool_99999",
                ],
            ],
        )
        out = capsys.readouterr().out
        assert "…" not in out
        for tab_id in ("context_external_tool_5826", "context_external_tool_99999"):
            assert any(tab_id in line for line in out.splitlines())

    def test_row_count_pluralizes(self, capsys):
        from cass.cli import report

        report.render_list(["A"], [["x"]])
        assert "1 row\n" in capsys.readouterr().out
        report.render_list(["A"], [["x"], ["y"]])
        assert "2 rows" in capsys.readouterr().out
        report.render_list(["A"], [])
        assert "0 rows" in capsys.readouterr().out


GROUPS = [
    ("people",),
    ("modules",),
    ("assignments",),
    ("assignments", "groups"),
    ("quizzes",),
    ("calendar",),
    ("files",),
    ("announcements",),
    ("tabs",),
]


class TestGroups:
    @pytest.fixture
    def empty_client(self, monkeypatch):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
        for method in (
            "list_users",
            "list_modules",
            "list_assignments",
            "list_assignment_groups",
            "list_quizzes",
            "list_calendar_events",
            "list_folders",
            "list_files",
            "list_announcements",
            "list_tabs",
        ):
            getattr(fake, method).return_value = []
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    @pytest.mark.parametrize("group", GROUPS)
    def test_bare_group_and_list_both_exit_0(self, empty_client, group):
        for args in (["canvas", *group], ["canvas", *group, "list"]):
            result = runner.invoke(app, args)
            assert result.exit_code == 0, (args, result.output)

    @pytest.mark.parametrize(
        "args",
        [
            ["canvas", "people", "--csv", "x.csv"],
            ["canvas", "quizzes", "--save", "x.md"],
            ["canvas", "calendar", "--from", "2026-10-01"],
        ],
    )
    def test_bare_group_takes_no_options(self, empty_client, args):
        assert runner.invoke(app, args).exit_code == 2

    def test_list_options_on_list(self, empty_client, tmp_path):
        out = tmp_path / "p.csv"
        result = runner.invoke(app, ["canvas", "people", "list", "--csv", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists()


class TestCanvasModules:
    @pytest.fixture
    def modules_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasModule

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
        fake.list_modules.return_value = [
            CanvasModule(id=1, name="Week 1", position=1),
            CanvasModule(id=2, name="Week 2", position=2),
        ]
        fake.resolve_module.return_value = CanvasModule(id=1, name="Week 1", position=1)
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
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

    def test_show_resolves_by_name(self, modules_client):
        from cass.apis.canvas.schema import CanvasModuleItem

        modules_client.list_module_items.return_value = [
            CanvasModuleItem(id=4, title="Reading", type="Page")
        ]
        result = runner.invoke(app, ["canvas", "modules", "show", "Week 1"])
        assert result.exit_code == 0, result.output
        modules_client.resolve_module.assert_called_once_with("Week 1")
        assert "Reading" in result.stdout

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
    @pytest.fixture
    def quiz_client(self, monkeypatch):
        from cass.apis.canvas.schema import (
            CanvasAssignmentGroup,
            CanvasQuiz,
            CanvasQuizAnswer,
            CanvasQuizQuestion,
        )

        quiz = CanvasQuiz(
            id=20,
            title="09-25 Participation Survey",
            quiz_type="graded_survey",
            points_possible=2.0,
            question_count=2,
            allowed_attempts=1,
            hide_results="always",
            unlock_at="2026-09-25T21:15:00Z",
            due_at="2026-09-26T00:00:00Z",
            assignment_group_id=9,
            html_url="https://c.edu/q/20",
        )
        questions = [
            CanvasQuizQuestion(
                id=1,
                position=1,
                question_type="essay_question",
                question_text="<p>What are you <b>hoping</b>?</p>",
            ),
            CanvasQuizQuestion(
                id=2,
                position=2,
                question_type="multiple_choice_question",
                question_text="<p>Which?</p>",
                points_possible=1.0,
                answers=[
                    CanvasQuizAnswer(id=1, text="A", weight=100),
                    CanvasQuizAnswer(id=2, text="B"),
                ],
            ),
        ]
        group = CanvasAssignmentGroup(id=9, name="Participation", position=1)
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
        fake.list_quizzes.return_value = [quiz]
        fake.resolve_quiz.return_value = quiz
        fake.list_quiz_questions.return_value = (questions, False)
        fake.list_assignment_groups.return_value = [group]
        fake.resolve_assignment_group.return_value = group
        fake.create_quiz.return_value = quiz
        fake.update_quiz.return_value = quiz
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    def test_list_shows_due_in_course_time(self, quiz_client):
        result = runner.invoke(app, ["canvas", "quizzes"])
        assert result.exit_code == 0, result.output
        assert "2026-09-25" in result.stdout

    def test_show_settings_and_questions(self, quiz_client):
        result = runner.invoke(app, ["canvas", "quizzes", "show", "20"])
        assert result.exit_code == 0, result.output
        assert "Participation" in result.stdout
        assert "2026-09-25 14:15" in result.stdout
        assert "What are you hoping?" in result.stdout
        assert "<b>" not in result.stdout
        assert "weights" not in result.stdout

    def test_show_notes_statistics_fallback(self, quiz_client):
        questions, _ = quiz_client.list_quiz_questions.return_value
        quiz_client.list_quiz_questions.return_value = (questions, True)
        result = runner.invoke(app, ["canvas", "quizzes", "show", "20"])
        assert result.exit_code == 0, result.output
        assert "answer weights are unavailable" in result.stderr

    def test_show_resolves_by_title(self, quiz_client):
        result = runner.invoke(
            app, ["canvas", "quizzes", "show", "09-25 Participation Survey"]
        )
        assert result.exit_code == 0, result.output
        quiz_client.resolve_quiz.assert_called_once_with("09-25 Participation Survey")

    def test_export_to_stdout(self, quiz_client):
        result = runner.invoke(app, ["canvas", "quizzes", "export", "20"])
        assert result.exit_code == 0, result.output
        assert 'title = "09-25 Participation Survey"' in result.stdout
        assert 'group = "Participation"' in result.stdout
        assert 'due_at = "2026-09-25 17:00"' in result.stdout
        assert (
            'answers = [{ text = "A", correct = true }, { text = "B" }]'
            in result.stdout
        )

    def test_export_to_file(self, quiz_client, tmp_path):
        out = tmp_path / "q.toml"
        result = runner.invoke(
            app, ["canvas", "quizzes", "export", "20", "-o", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert 'type = "graded_survey"' in out.read_text()
        assert "Wrote" in result.stdout

    def test_create_from_file(self, quiz_client, tmp_path):
        from cass.actions.quizzes import QuizSpec

        path = tmp_path / "q.toml"
        path.write_text(
            'title = "S"\ntype = "survey"\ngroup = "Participation"\n'
            '[[questions]]\ntext = "x"\n'
        )
        result = runner.invoke(
            app, ["canvas", "quizzes", "create", "--from", str(path), "--publish"]
        )
        assert result.exit_code == 0, result.output
        spec = quiz_client.create_quiz.call_args.args[0]
        kwargs = quiz_client.create_quiz.call_args.kwargs
        assert isinstance(spec, QuizSpec)
        assert spec.published is True
        assert kwargs["assignment_group_id"] == 9
        assert "id=20" in result.stdout

    def test_create_from_file_missing_group_errors(self, quiz_client, tmp_path):
        from cass.apis.canvas.errors import CanvasNotFoundError

        quiz_client.resolve_assignment_group.side_effect = CanvasNotFoundError(
            "Assignment group not found: Nope"
        )
        path = tmp_path / "q.toml"
        path.write_text('title = "S"\ntype = "survey"\ngroup = "Nope"\n')
        result = runner.invoke(
            app, ["canvas", "quizzes", "create", "--from", str(path)]
        )
        assert result.exit_code == 1
        assert "--create-groups" in result.output
        quiz_client.create_quiz.assert_not_called()

    def test_create_from_file_creates_group(self, quiz_client, tmp_path):
        from cass.apis.canvas.errors import CanvasNotFoundError
        from cass.apis.canvas.schema import CanvasAssignmentGroup

        quiz_client.resolve_assignment_group.side_effect = CanvasNotFoundError("nope")
        quiz_client.create_assignment_group.return_value = CanvasAssignmentGroup(
            id=11, name="Nope"
        )
        path = tmp_path / "q.toml"
        path.write_text('title = "S"\ntype = "survey"\ngroup = "Nope"\n')
        result = runner.invoke(
            app,
            ["canvas", "quizzes", "create", "--from", str(path), "--create-groups"],
        )
        assert result.exit_code == 0, result.output
        quiz_client.create_assignment_group.assert_called_once_with("Nope")
        assert quiz_client.create_quiz.call_args.kwargs["assignment_group_id"] == 11

    def test_create_positional_builds_spec(self, quiz_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "quizzes",
                "create",
                "Placeholder",
                "--type",
                "graded_survey",
                "--points",
                "2",
                "--group",
                "Participation",
                "--due",
                "2026-10-01 17:00",
                "--attempts",
                "-1",
            ],
        )
        assert result.exit_code == 0, result.output
        spec = quiz_client.create_quiz.call_args.args[0]
        assert spec.title == "Placeholder"
        assert spec.points == 2
        assert spec.due_at == "2026-10-01 17:00"
        assert spec.attempts == -1
        assert spec.questions == []

    def test_create_positional_rejects_points_for_non_survey(self, quiz_client):
        result = runner.invoke(
            app, ["canvas", "quizzes", "create", "Q", "--points", "2"]
        )
        assert result.exit_code == 1
        assert "graded_survey" in result.output

    def test_update_from_file_reports_changes(self, quiz_client, tmp_path):
        path = tmp_path / "q.toml"
        path.write_text(
            'title = "09-25 Participation Survey"\ntype = "graded_survey"\n'
            'points = 2\ngroup = "Participation"\nunlock_at = "2026-09-25 14:15"\n'
            'due_at = "2026-09-25 18:00"\nattempts = 1\nhide_results = "always"\n'
        )
        result = runner.invoke(
            app, ["canvas", "quizzes", "update", "20", "--from", str(path)]
        )
        assert result.exit_code == 0, result.output
        quiz_client.update_quiz.assert_called_once_with(
            20, {"due_at": "2026-09-25T18:00:00-07:00"}
        )
        assert "due_at" in result.stdout

    def test_update_from_file_no_changes(self, quiz_client, tmp_path):
        path = tmp_path / "q.toml"
        path.write_text(
            'title = "09-25 Participation Survey"\ntype = "graded_survey"\n'
            'points = 2\ngroup = "Participation"\nunlock_at = "2026-09-25 14:15"\n'
            'due_at = "2026-09-25 17:00"\nattempts = 1\nhide_results = "always"\n'
        )
        result = runner.invoke(
            app, ["canvas", "quizzes", "update", "20", "--from", str(path)]
        )
        assert result.exit_code == 0, result.output
        quiz_client.update_quiz.assert_not_called()
        assert "no changes" in result.stderr.lower()

    _REPORT = (
        "name,id,sis_id,section,submitted,101: Hoping for?,0.0,score\n"
        "Alice Smith,11,A1,Sec A,2026-09-26 01:00:00 UTC,To learn,0.0,0.0\n"
    )

    def test_responses_to_csv(self, quiz_client, tmp_path):
        quiz_client.download_quiz_report.return_value = self._REPORT
        quiz_client.list_quiz_submissions.return_value = []
        out = tmp_path / "responses.csv"
        result = runner.invoke(
            app,
            [
                "canvas",
                "quizzes",
                "responses",
                "20",
                "--all-attempts",
                "--csv",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        quiz_client.download_quiz_report.assert_called_once_with(20, all_versions=True)
        header, row = out.read_text().splitlines()
        assert header.startswith("student,user_id,sis_id,section,attempt")
        assert "To learn" in row
        # Submitted after the quiz's 2026-09-26T00:00Z due date, written in
        # the course time zone.
        assert ",2026-09-25T17:00:00-07:00,true," in row

    def test_responses_table(self, quiz_client):
        quiz_client.download_quiz_report.return_value = self._REPORT
        quiz_client.list_quiz_submissions.return_value = []
        result = runner.invoke(app, ["canvas", "quizzes", "responses", "20"])
        assert result.exit_code == 0, result.output
        assert "Alice Smith" in result.stdout
        assert "To learn" in result.stdout

    def test_responses_wide_prints_report(self, quiz_client):
        quiz_client.download_quiz_report.return_value = self._REPORT
        result = runner.invoke(app, ["canvas", "quizzes", "responses", "20", "--wide"])
        assert result.exit_code == 0, result.output
        assert result.stdout.endswith(self._REPORT)
        quiz_client.list_quiz_submissions.assert_not_called()

    def test_responses_wide_to_csv(self, quiz_client, tmp_path):
        quiz_client.download_quiz_report.return_value = self._REPORT
        out = tmp_path / "wide.csv"
        result = runner.invoke(
            app, ["canvas", "quizzes", "responses", "20", "--wide", "--csv", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.read_text() == self._REPORT


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
        fake.time_zone = "America/Los_Angeles"
        fake.planned_requests = []
        fake.list_assignments.return_value = [
            CanvasAssignmentResponse(
                id=1,
                name="HW1",
                points_possible=10,
                due_at="2026-10-02T06:59:00Z",
                published=True,
            )
        ]
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)

        result = runner.invoke(app, ["canvas", "sync"])
        assert result.exit_code == 0, result.output
        assert "0 create, 0 update, 1 skip" in result.stdout

    def test_naive_due_at_is_localized(self, monkeypatch, tmp_path):
        from cass.apis.canvas.schema import CanvasAssignmentResponse

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
            'time_zone = "America/Los_Angeles"\n'
            '\n[[canvas.assignments]]\nname = "HW1"\npoints = 10\n'
            'due_at = "2026-10-01 23:59"\npublished = true\n'
        )
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
        fake.planned_requests = []
        fake.list_assignments.return_value = [
            CanvasAssignmentResponse(
                id=1,
                name="HW1",
                points_possible=10,
                due_at="2026-10-02T06:59:00Z",
                published=True,
            )
        ]
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)

        result = runner.invoke(app, ["canvas", "sync"])
        assert result.exit_code == 0, result.output
        assert "0 create, 0 update, 1 skip" in result.stdout

    def _quiz_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "quizzes").mkdir()
        (tmp_path / "quizzes" / "s.toml").write_text(
            'title = "Survey"\ntype = "survey"\ngroup = "Participation"\n'
            '[[questions]]\ntext = "x"\n'
        )
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
            'time_zone = "America/Los_Angeles"\n\n'
            '[[canvas.quizzes]]\nfile = "quizzes/s.toml"\n'
        )
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
        fake.list_quizzes.return_value = []
        fake.list_assignments.return_value = []
        fake.list_assignment_groups.return_value = []
        fake.planned_requests = []
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    def test_quiz_missing_group_is_an_error(self, monkeypatch, tmp_path):
        fake = self._quiz_project(tmp_path, monkeypatch)
        result = runner.invoke(app, ["canvas", "sync", "--apply"])
        assert result.exit_code == 1
        assert "Participation" in result.output
        fake.create_quiz.assert_not_called()

    def test_quiz_dry_run_lists_group_and_quiz(self, monkeypatch, tmp_path):
        fake = self._quiz_project(tmp_path, monkeypatch)
        calls: list[bool] = []
        monkeypatch.setattr(
            "cass.cli.canvas._common.client",
            lambda dry_run=False: (calls.append(dry_run), fake)[1],
        )
        result = runner.invoke(app, ["canvas", "sync", "--create-groups"])
        assert result.exit_code == 0, result.output
        assert calls == [True]
        assert "group" in result.stdout
        assert "quiz" in result.stdout
        assert "2 create" in result.stdout

    def test_dry_run_sends_no_write_and_prints_table_and_plan(
        self, monkeypatch, tmp_path
    ):
        import httpx

        from cass.apis.canvas.client import CanvasClient

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
            'time_zone = "America/Los_Angeles"\n\n'
            '[[canvas.modules]]\nname = "Week 9"\npublished = true\n'
        )
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=[])

        monkeypatch.setattr(
            "cass.cli.canvas._common.client",
            lambda dry_run=False: CanvasClient(
                "https://canvas.example.com",
                token="t",
                course_id=1,
                transport=httpx.MockTransport(handler),
                time_zone="America/Los_Angeles",
                dry_run=dry_run,
            ),
        )
        result = runner.invoke(app, ["canvas", "sync"])
        assert result.exit_code == 0, result.output
        assert [r for r in seen if r.method != "GET"] == []
        assert "Canvas Sync" in result.stdout
        assert "1 create" in result.stdout
        assert "POST /courses/1/modules" in result.stdout
        assert "PUT /courses/1/modules/<new 1>" in result.stdout

    def test_quiz_apply_creates_group_then_quiz(self, monkeypatch, tmp_path):
        from cass.apis.canvas.schema import CanvasAssignmentGroup

        fake = self._quiz_project(tmp_path, monkeypatch)
        fake.create_assignment_group.return_value = CanvasAssignmentGroup(
            id=11, name="Participation"
        )
        result = runner.invoke(app, ["canvas", "sync", "--apply", "--create-groups"])
        assert result.exit_code == 0, result.output
        fake.create_assignment_group.assert_called_once_with("Participation")
        assert fake.create_quiz.call_args.kwargs["assignment_group_id"] == 11


class TestCanvasTabsAndFiles:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasFile, CanvasFolder, CanvasTab

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
        fake.resolve_tab.return_value = CanvasTab(
            id="context_external_tool_5826", label="Media Gallery"
        )
        fake.resolve_file.return_value = CanvasFile(id=15, display_name="notes.txt")
        fake.update_tab.return_value = CanvasTab(
            id="context_external_tool_5826", label="Media Gallery", hidden=True
        )
        fake.list_folders.return_value = [
            CanvasFolder(id=1, name="course files", full_name="course files")
        ]
        fake.list_files.return_value = [
            CanvasFile(id=18962999, display_name="notes.txt", size=20, folder_id=1)
        ]
        readings = CanvasFolder(
            id=3,
            name="readings",
            full_name="course files/readings",
            parent_folder_id=1,
        )
        fake.update_file.return_value = CanvasFile(id=15, display_name="notes.txt")
        fake.resolve_folder.return_value = readings
        fake.create_folder.return_value = readings
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    def test_files_mv_creates_folder_and_moves(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "files", "mv", "notes.txt", "readings/week1"]
        )
        assert result.exit_code == 0, result.output
        fake_client.create_folder.assert_called_once_with("readings/week1")
        fake_client.update_file.assert_called_once_with(
            15, folder_id=3, on_duplicate=None
        )
        assert "Moved:" in result.stdout

    def test_files_rename(self, fake_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "files",
                "rename",
                "15",
                "new.txt",
                "--on-duplicate",
                "overwrite",
            ],
        )
        assert result.exit_code == 0, result.output
        fake_client.update_file.assert_called_once_with(
            15, name="new.txt", on_duplicate="overwrite"
        )
        assert "Renamed:" in result.stdout

    def test_files_publish_unpublish(self, fake_client):
        assert runner.invoke(app, ["canvas", "files", "publish", "15"]).exit_code == 0
        fake_client.update_file.assert_called_with(15, locked=False)
        assert runner.invoke(app, ["canvas", "files", "unpublish", "15"]).exit_code == 0
        fake_client.update_file.assert_called_with(15, locked=True)

    def test_folders_create(self, fake_client):
        result = runner.invoke(app, ["canvas", "files", "folders", "create", "a/b"])
        assert result.exit_code == 0, result.output
        fake_client.create_folder.assert_called_once_with("a/b")
        assert "Created folder:" in result.stdout

    def test_folders_delete_needs_yes_off_tty(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "files", "folders", "delete", "readings"]
        )
        assert result.exit_code == 1
        assert "--yes" in result.stderr
        fake_client.delete_folder.assert_not_called()

    def test_folders_delete_force(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "files", "folders", "delete", "readings", "--force", "-y"]
        )
        assert result.exit_code == 0, result.output
        fake_client.delete_folder.assert_called_once_with(3, force=True)
        assert "Deleted folder:" in result.stdout

    def test_folders_delete_root_refused(self, fake_client):
        from cass.apis.canvas.schema import CanvasFolder

        fake_client.resolve_folder.return_value = CanvasFolder(
            id=1, name="course files", full_name="course files"
        )
        result = runner.invoke(app, ["canvas", "files", "folders", "delete", "1", "-y"])
        assert result.exit_code == 1
        # the entry point turns this RuntimeError into a one-line stderr error
        assert "root folder" in str(result.exception)
        fake_client.delete_folder.assert_not_called()

    def test_folders_bare_runs_list(self, fake_client):
        from cass.apis.canvas.schema import CanvasFolder

        fake_client.list_folders.return_value = [
            CanvasFolder(id=1, name="course files", full_name="course files"),
            CanvasFolder(
                id=3,
                name="readings",
                full_name="course files/readings",
                parent_folder_id=1,
            ),
        ]
        result = runner.invoke(app, ["canvas", "files", "folders"])
        assert result.exit_code == 0, result.output
        assert "readings" in result.stdout

    def test_delete_file_without_yes_on_non_tty_exits_1(self, fake_client):
        result = runner.invoke(app, ["canvas", "files", "delete", "15"])
        assert result.exit_code == 1
        assert "--yes" in result.stderr
        fake_client.delete_file.assert_not_called()

    def test_files_delete_by_name(self, fake_client):
        result = runner.invoke(app, ["canvas", "files", "delete", "notes.txt", "-y"])
        assert result.exit_code == 0, result.output
        fake_client.resolve_file.assert_called_once_with("notes.txt")
        fake_client.delete_file.assert_called_once_with(15)

    def test_hide_tab_resolves_by_label(self, fake_client):
        result = runner.invoke(app, ["canvas", "tabs", "hide", "Media Gallery"])
        assert result.exit_code == 0, result.output
        fake_client.resolve_tab.assert_called_once_with("Media Gallery")
        fake_client.update_tab.assert_called_once_with(
            "context_external_tool_5826", hidden=True
        )

    def test_show_tab_resolves_by_label(self, fake_client):
        result = runner.invoke(app, ["canvas", "tabs", "show", "media gallery"])
        assert result.exit_code == 0, result.output
        fake_client.update_tab.assert_called_once_with(
            "context_external_tool_5826", hidden=False
        )

    def test_upload_options_reach_action(self, fake_client, monkeypatch, tmp_path):
        from cass.actions.files import FileUpload, OnDuplicate
        from cass.apis.canvas.schema import CanvasFile

        (tmp_path / "notes.txt").write_text("hi")
        monkeypatch.chdir(tmp_path)
        action = MagicMock(
            return_value=FileUpload(CanvasFile(id=9, display_name="w1.txt"), False)
        )
        monkeypatch.setattr("cass.actions.files.upload_course_file", action)

        result = runner.invoke(
            app,
            [
                *("canvas", "files", "upload", "notes.txt"),
                *("--folder", "readings", "--name", "w1.txt"),
                *("--on-duplicate", "skip", "--unpublished"),
            ],
        )

        assert result.exit_code == 0, result.output
        assert action.call_args.kwargs == {
            "folder": "readings",
            "name": "w1.txt",
            "on_duplicate": OnDuplicate.SKIP,
            "unpublished": True,
        }

    def test_upload_skip_message(self, fake_client, monkeypatch, tmp_path):
        from cass.actions.files import FileUpload
        from cass.apis.canvas.schema import CanvasFile

        (tmp_path / "notes.txt").write_text("hi")
        monkeypatch.chdir(tmp_path)
        skipped = FileUpload(CanvasFile(id=7, display_name="w1.txt"), skipped=True)
        monkeypatch.setattr(
            "cass.actions.files.upload_course_file", MagicMock(return_value=skipped)
        )

        result = runner.invoke(app, ["canvas", "files", "upload", "notes.txt"])

        assert result.exit_code == 0, result.output
        assert "Skipped: w1.txt (id=7)" in result.stdout

    def test_upload_bad_on_duplicate_is_usage_error(
        self, fake_client, monkeypatch, tmp_path
    ):
        (tmp_path / "notes.txt").write_text("hi")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["canvas", "files", "upload", "notes.txt", "--on-duplicate", "keep"]
        )

        assert result.exit_code == 2

    def _folder_listing(self, fake_client):
        from cass.apis.canvas.schema import CanvasFile, CanvasFolder

        root = CanvasFolder(id=1, name="course files", full_name="course files")
        readings = CanvasFolder(
            id=3, name="readings", full_name="course files/readings"
        )
        slides = CanvasFolder(id=4, name="slides", full_name="course files/slides")
        fake_client.list_folders.return_value = [root, readings, slides]
        fake_client.list_files.return_value = [
            CanvasFile(id=30, display_name="a.pdf", folder_id=3),
            CanvasFile(id=40, display_name="b.pdf", folder_id=4),
        ]
        fake_client.resolve_folder.return_value = readings

    def test_files_list_folder_filters(self, fake_client):
        self._folder_listing(fake_client)

        result = runner.invoke(app, ["canvas", "files", "list", "--folder", "readings"])
        assert result.exit_code == 0, result.output
        assert "a.pdf" in result.stdout
        assert "b.pdf" not in result.stdout

        result = runner.invoke(
            app, ["canvas", "files", "list", "--folder", "readings", "--json"]
        )
        assert result.exit_code == 0, result.output
        records = [json.loads(line) for line in result.stdout.splitlines()]
        assert sorted(r["id"] for r in records) == [3, 30]

    def test_files_list_unknown_folder_exits_1(self, fake_client, monkeypatch, capsys):
        import sys

        from cass.apis.canvas.errors import CanvasNotFoundError
        from cass.cli import run

        fake_client.resolve_folder.side_effect = CanvasNotFoundError(
            "Folder not found: nope"
        )
        monkeypatch.setenv("CASS_DEBUG", "")
        monkeypatch.setattr(
            sys, "argv", ["cass", "canvas", "files", "list", "--folder", "nope"]
        )

        with pytest.raises(SystemExit) as info:
            run()

        assert info.value.code == 1
        assert "Folder not found: nope" in capsys.readouterr().err

    def test_files_tree_shows_ids(self, fake_client):
        result = runner.invoke(app, ["canvas", "files"])
        assert result.exit_code == 0, result.output
        assert "notes.txt" in result.stdout
        assert "18962999" in result.stdout

    def test_files_tree_shows_folder_ids(self, fake_client):
        result = runner.invoke(app, ["canvas", "files"])
        assert result.exit_code == 0, result.output
        assert re.search(r"id=1\b", result.stdout)
        assert "id=18962999" in result.stdout

    def test_tabs_list_full_ids_at_80_columns(self, fake_client, monkeypatch):
        from rich.console import Console

        from cass.apis.canvas.schema import CanvasTab
        from cass.cli import report

        monkeypatch.setattr(report, "console", Console(width=80, force_terminal=False))
        fake_client.list_tabs.return_value = [
            CanvasTab(id="context_external_tool_5826", label="Media Gallery"),
            CanvasTab(
                id="context_external_tool_99999",
                label="A much longer navigation label here",
                hidden=True,
            ),
        ]
        result = runner.invoke(app, ["canvas", "tabs", "list"])
        assert result.exit_code == 0, result.output
        for tab_id in ("context_external_tool_5826", "context_external_tool_99999"):
            assert any(tab_id in line for line in result.stdout.splitlines())


class TestCanvasAnnouncements:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasAnnouncement

        fake = MagicMock()
        fake.__enter__.return_value = fake
        announcement = CanvasAnnouncement(id=13, title="Welcome")
        fake.resolve_announcement.return_value = announcement
        fake.update_announcement.return_value = announcement
        fake.create_announcement.return_value = announcement
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    def test_update_by_title(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "announcements", "update", "Welcome", "--title", "Hi"]
        )
        assert result.exit_code == 0, result.output
        fake_client.update_announcement.assert_called_once_with(13, title="Hi")

    def test_delete_by_title(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "announcements", "delete", "Welcome", "-y"]
        )
        assert result.exit_code == 0, result.output
        fake_client.delete_announcement.assert_called_once_with(13)

    def test_create(self, fake_client):
        result = runner.invoke(
            app, ["canvas", "announcements", "create", "Hello", "-m", "Hi"]
        )
        assert result.exit_code == 0, result.output
        fake_client.create_announcement.assert_called_once_with("Hello", "Hi")


class TestCanvasAssignments:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        from cass.apis.canvas.schema import (
            CanvasAssignmentGroup,
            CanvasAssignmentResponse,
        )

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
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
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    def test_show_resolves_by_name(self, fake_client):
        from cass.apis.canvas.schema import CanvasAssignmentResponse

        fake_client.resolve_assignment.return_value = CanvasAssignmentResponse(
            id=7, name="HW1"
        )
        result = runner.invoke(app, ["canvas", "assignments", "show", "HW1"])
        assert result.exit_code == 0, result.output
        fake_client.resolve_assignment.assert_called_once_with("HW1")
        assert "HW1" in result.stdout

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

    def test_create_due_in_course_time(self, fake_client):
        result = runner.invoke(
            app,
            [
                "canvas",
                "assignments",
                "create",
                "HW1",
                "--group",
                "Labs",
                "--due",
                "2026-10-01 23:59",
            ],
        )
        assert result.exit_code == 0, result.output
        kwargs = fake_client.create_assignment.call_args.kwargs
        assert kwargs["due_at"] == "2026-10-01T23:59:00-07:00"

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
    def test_when_converts_utc_to_course_zone(self):
        from cass.cli.canvas import when

        assert when("2026-09-22T17:00:00Z", "America/Los_Angeles") == "2026-09-22 10:00"
        assert when(None, "America/Los_Angeles") == ""

    @pytest.fixture
    def calendar_client(self, monkeypatch):
        from cass.apis.canvas.schema import CanvasCalendarEvent

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.time_zone = "America/Los_Angeles"
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
        monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
        monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: fake)
        return fake

    def test_create_localizes_start(self, calendar_client):
        result = runner.invoke(
            app, ["canvas", "calendar", "create", "OH", "--start", "2026-10-19 15:00"]
        )
        assert result.exit_code == 0, result.output
        kwargs = calendar_client.create_calendar_event.call_args.kwargs
        assert kwargs["start_at"] == "2026-10-19T15:00:00-07:00"

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
            app,
            [
                "canvas",
                "calendar",
                "list",
                "--from",
                "2026-10-01",
                "--to",
                "2026-10-31",
            ],
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
            start_at="2026-10-20T10:00:00-07:00",
            end_at="2026-10-20T11:00:00-07:00",
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
        assert "Nothing to update" in result.stderr
        assert result.stdout == ""
        calendar_client.update_calendar_event.assert_not_called()

    def test_delete_with_yes(self, calendar_client):
        result = runner.invoke(app, ["canvas", "calendar", "delete", "235", "-y"])
        assert result.exit_code == 0, result.output
        calendar_client.delete_calendar_event.assert_called_once_with(235)


class TestGroupIdFor:
    """``group_id_for`` creates only missing groups; ambiguous names propagate."""

    @pytest.fixture
    def client(self):
        from cass.apis.canvas.client import CanvasClient
        from cass.apis.canvas.schema import CanvasAssignmentGroup

        class StubClient:
            dry_run = False
            created: list[str]
            _resolve = CanvasClient._resolve
            resolve_assignment_group = CanvasClient.resolve_assignment_group

            def __init__(self) -> None:
                self.created = []

            def list_assignment_groups(self):
                return [
                    CanvasAssignmentGroup(id=1, name="Labs", position=1),
                    CanvasAssignmentGroup(id=2, name="Labs", position=2),
                    CanvasAssignmentGroup(id=3, name="Exams", position=3),
                ]

            def create_assignment_group(self, name):
                self.created.append(name)
                return CanvasAssignmentGroup(id=9, name=name, position=4)

        return StubClient()

    @pytest.mark.parametrize("create", [False, True])
    def test_ambiguous_name_propagates_and_creates_nothing(self, client, create):
        from cass.cli.canvas._common import group_id_for

        with pytest.raises(RuntimeError, match="ambiguous"):
            group_id_for(client, "Labs", create=create)  # ty: ignore[invalid-argument-type]
        assert client.created == []

    def test_missing_name_creates_when_asked(self, client):
        from cass.cli.canvas._common import group_id_for

        assert group_id_for(client, "Quizzes", create=True) == 9  # ty: ignore[invalid-argument-type]
        assert client.created == ["Quizzes"]

    def test_missing_name_without_create_exits(self, client):
        import typer

        from cass.cli.canvas._common import group_id_for

        with pytest.raises(typer.Exit):
            group_id_for(client, "Quizzes", create=False)  # ty: ignore[invalid-argument-type]
        assert client.created == []

    def test_fail_message_stays_on_one_line(self, monkeypatch, capfd):
        from cass.cli import _fail

        monkeypatch.setenv("COLUMNS", "80")
        monkeypatch.setattr("cass.cli.err_console", _fresh_err_console())
        _fail("word " * 60)
        err = capfd.readouterr().err
        assert len(err.strip().splitlines()) == 1


def _fresh_err_console():
    from rich.console import Console

    return Console(stderr=True, width=80)
