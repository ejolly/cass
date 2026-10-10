"""``--dry-run`` on every Canvas write command: nothing sent, nothing changed."""

from __future__ import annotations

__docformat__ = "google"

import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import click
import httpx
import pytest
import sqlite_utils
import typer.main
from typer.testing import CliRunner

from cass import db
from cass.actions.config import reset_config, set_config_path
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()
API = "/api/v1"

CASS_TOML = """\
[canvas]
base_url = "https://canvas.example.com"
course_id = 1
time_zone = "America/Los_Angeles"

[[canvas.modules]]
name = "Week 2"

[[canvas.quizzes]]
file = "quizzes/q.toml"
"""

QUIZ_TOML = """\
title = "Quiz A"
type = "survey"
attempts = 2

[[questions]]
text = "x"
"""

MODULE = {"id": 5, "name": "Week 1", "position": 1, "published": False}
ITEM = {
    "id": 21,
    "title": "Reading",
    "type": "SubHeader",
    "position": 1,
    "indent": 0,
    "published": True,
    "module_id": 5,
}
ASSIGNMENT = {"id": 7, "name": "HW1", "published": False}
GROUP = {"id": 9, "name": "Labs"}
QUIZ = {
    "id": 3,
    "title": "Quiz A",
    "quiz_type": "survey",
    "published": False,
    "allowed_attempts": 1,
}

GET_ROUTES: dict[str, object] = {
    "/courses/1": {"id": 1, "name": "C", "time_zone": "America/Los_Angeles"},
    "/courses/1/modules": [MODULE],
    "/courses/1/modules/5": MODULE,
    "/courses/1/modules/5/items": [ITEM],
    "/courses/1/modules/5/items/21": ITEM,
    "/courses/1/assignments": [ASSIGNMENT],
    "/courses/1/assignments/7": ASSIGNMENT,
    "/courses/1/assignment_groups": [GROUP],
    "/courses/1/assignment_groups/9": GROUP,
    "/courses/1/quizzes": [QUIZ],
    "/courses/1/quizzes/3": QUIZ,
    "/courses/1/tabs": [{"id": "files", "label": "Files", "hidden": False}],
    "/calendar_events/11": {"id": 11, "title": "Office hours"},
    "/courses/1/discussion_topics/13": {"id": 13, "title": "Welcome"},
    "/files/15": {"id": 15, "display_name": "notes.txt"},
    "/courses/1/folders": [
        {
            "id": 2,
            "name": "course files",
            "full_name": "course files",
            "parent_folder_id": None,
        },
        {
            "id": 3,
            "name": "readings",
            "full_name": "course files/readings",
            "parent_folder_id": 2,
        },
    ],
    "/folders/3": {
        "id": 3,
        "name": "readings",
        "full_name": "course files/readings",
        "parent_folder_id": 2,
    },
    "/folders/3/files": [{"id": 15, "display_name": "notes.txt", "size": 6}],
    "/courses/1/files": [{"id": 15, "display_name": "notes.txt"}],
    "/courses/1/discussion_topics": [{"id": 13, "title": "Welcome"}],
}

DRY_RUN_COMMANDS = [
    (("canvas", "modules", "create"), ["Week 3"]),
    (("canvas", "modules", "publish"), ["Week 1"]),
    (("canvas", "modules", "unpublish"), ["Week 1"]),
    (("canvas", "modules", "delete"), ["Week 1"]),
    (
        ("canvas", "modules", "items", "add"),
        ["Week 1", "--type", "Assignment", "--content-id", "7"],
    ),
    (
        ("canvas", "modules", "items", "update"),
        ["Week 1", "Reading", "--title", "Readings"],
    ),
    (("canvas", "modules", "items", "move"), ["Week 1", "21", "--position", "2"]),
    (("canvas", "modules", "items", "remove"), ["Week 1", "Reading"]),
    (("canvas", "assignments", "create"), ["HW2", "--group", "Labs"]),
    (("canvas", "assignments", "publish"), ["HW1"]),
    (("canvas", "assignments", "unpublish"), ["HW1"]),
    (("canvas", "assignments", "delete"), ["HW1"]),
    (("canvas", "assignments", "groups", "create"), ["Projects"]),
    (("canvas", "assignments", "groups", "delete"), ["Labs"]),
    (("canvas", "quizzes", "create"), ["Quiz B"]),
    (("canvas", "quizzes", "update"), ["Quiz A", "--from", "quizzes/q.toml"]),
    (
        ("canvas", "quizzes", "update"),
        ["Quiz A", "--from", "quizzes/q.toml", "--questions"],
    ),
    (("canvas", "quizzes", "publish"), ["Quiz A"]),
    (("canvas", "quizzes", "unpublish"), ["Quiz A"]),
    (("canvas", "quizzes", "delete"), ["Quiz A"]),
    (("canvas", "calendar", "create"), ["Review", "--start", "2026-10-20 10:00"]),
    (("canvas", "calendar", "update"), ["11", "--title", "Review session"]),
    (("canvas", "calendar", "delete"), ["11"]),
    (("canvas", "files", "upload"), ["notes.txt"]),
    (
        ("canvas", "files", "upload"),
        ["notes.txt", "--folder", "new/sub", "--name", "n.txt", "--unpublished"],
    ),
    (
        ("canvas", "files", "upload"),
        ["notes.txt", "--folder", "readings", "--on-duplicate", "overwrite"],
    ),
    (("canvas", "files", "delete"), ["notes.txt"]),
    (("canvas", "files", "mv"), ["notes.txt", "readings/week1"]),
    (("canvas", "files", "rename"), ["notes.txt", "n.txt"]),
    (("canvas", "files", "publish"), ["notes.txt"]),
    (("canvas", "files", "unpublish"), ["notes.txt"]),
    (("canvas", "files", "folders", "create"), ["readings/week1"]),
    (("canvas", "files", "folders", "delete"), ["readings"]),
    (("canvas", "announcements", "create"), ["Hello", "--message", "Hi"]),
    (("canvas", "announcements", "update"), ["Welcome", "--title", "Hello again"]),
    (("canvas", "announcements", "delete"), ["13"]),
    (("canvas", "tabs", "show"), ["Files"]),
    (("canvas", "tabs", "hide"), ["Files"]),
    (("canvas", "sync"), []),
    (
        ("canvas", "api"),
        ["POST", "/courses/{course}/modules", "--data", "module[name]=X"],
    ),
    (("push",), []),
]

PUSH_PREVIEW = {
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
}


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture
def course(tmp_path, monkeypatch):
    """A project directory plus a fake Canvas that records every request."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cass.toml").write_text(CASS_TOML)
    (tmp_path / "quizzes").mkdir()
    (tmp_path / "quizzes" / "q.toml").write_text(QUIZ_TOML)
    (tmp_path / "notes.txt").write_text("notes\n")
    sdb = sqlite_utils.Database(str(tmp_path / "cass.db"))
    db.init_schema(sdb)
    monkeypatch.setattr("cass.db.core._db", sdb)
    monkeypatch.setattr("cass.db.core._db_path", None)

    sent: list[httpx.Request] = []
    routes = dict(GET_ROUTES)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method != "GET":
            return httpx.Response(500, json={"message": "write reached Canvas"})
        path = request.url.path.removeprefix(API)
        if path in routes:
            body = routes[path]
            if isinstance(body, httpx.Response):
                return body
            return httpx.Response(200, json=body)
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

    monkeypatch.setattr(
        "cass.db.get_pending_changes",
        lambda conn: {
            "canvas_assignments": {
                "7": {"name": {"baseline": "HW1", "current": "HW 1"}}
            }
        },
    )
    monkeypatch.setattr("cass.db.canvas_preview", lambda conn, pending: PUSH_PREVIEW)

    def fail_apply(conn, pending):
        raise AssertionError("canvas_apply must not run under --dry-run")

    monkeypatch.setattr("cass.db.canvas_apply", MagicMock(side_effect=fail_apply))
    return tmp_path, sdb, sent, routes


def _snapshot(root: Path, sdb: sqlite_utils.Database) -> dict[str, object]:
    return {
        "files": {
            name: (root / name).read_bytes()
            for name in ("cass.toml", "quizzes/q.toml", "notes.txt")
        },
        "rows": {t.name: list(sdb[t.name].rows) for t in sdb.tables},
    }


@pytest.mark.parametrize(
    ("path", "args"), DRY_RUN_COMMANDS, ids=[" ".join(p) for p, _ in DRY_RUN_COMMANDS]
)
def test_dry_run_matrix(course, path, args):
    root, sdb, sent, _ = course
    before = _snapshot(root, sdb)

    result = runner.invoke(app, [*path, *args, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert [r.method for r in sent if r.method != "GET"] == []
    if path == ("canvas", "api"):
        assert "POST /courses/1/modules" in result.stderr
    elif path == ("push",):
        assert "Canvas Push Preview" in result.stdout
    else:
        assert re.search(r"^\s*(POST|PUT|DELETE) /", result.stdout, re.MULTILINE), (
            result.stdout
        )
    assert _snapshot(root, sdb) == before


def test_dry_run_get_failure_exits_1(course):
    _, _, sent, routes = course
    routes["/calendar_events/11"] = httpx.Response(404, json={"message": "not found"})

    result = runner.invoke(app, ["canvas", "calendar", "delete", "11", "--dry-run"])

    assert result.exit_code == 1, result.output
    assert [r.method for r in sent if r.method != "GET"] == []


def _command_paths(
    command: click.Command, prefix: tuple[str, ...] = ()
) -> Iterator[tuple[str, ...]]:
    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            yield from _command_paths(sub, (*prefix, name))
    else:
        yield prefix


def test_every_write_command_is_in_the_matrix():
    write_words = {
        "create",
        "update",
        "delete",
        "publish",
        "unpublish",
        "upload",
        "mv",
        "rename",
        "hide",
        "add",
        "move",
        "remove",
    }
    root = typer.main.get_command(app)
    write_paths = {
        path
        for path in _command_paths(root)
        if path[:1] == ("canvas",)
        and (
            path == ("canvas", "tabs", "show") or write_words & set(path[-1].split("-"))
        )
    }
    assert write_paths
    assert write_paths <= {path for path, _ in DRY_RUN_COMMANDS}


def test_dry_run_create_groups_does_not_claim_creation(course):
    root, _, _, _ = course
    (root / "quizzes" / "grouped.toml").write_text(
        QUIZ_TOML.replace("attempts = 2", 'attempts = 2\ngroup = "New"')
    )
    result = runner.invoke(
        app,
        [
            *("canvas", "quizzes", "create", "--from", "quizzes/grouped.toml"),
            *("--create-groups", "--dry-run"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Created group" not in result.stdout
    assert "Would create group: New" in result.stderr
    assert "Would create group" not in result.stdout
    assert re.search(
        r"^\s*POST /courses/1/assignment_groups", result.stdout, re.MULTILINE
    )


class _FakeClient:
    def __init__(self, planned_requests):
        self.planned_requests = planned_requests


@pytest.mark.parametrize("err", [False, True])
def test_print_plan_empty(capsys, err):
    from cass.cli.canvas._common import print_plan

    print_plan(_FakeClient([]), err=err)  # ty: ignore[invalid-argument-type]

    captured = capsys.readouterr()
    stream = captured.err if err else captured.out
    assert "no Canvas writes needed" in stream
    assert (captured.out if err else captured.err) == ""


@pytest.mark.parametrize("err", [False, True])
def test_print_plan_keeps_each_write_on_one_line(capsys, monkeypatch, err):
    from cass.apis.canvas.dry_run import PlannedRequest, format_plan
    from cass.cli.canvas import _common

    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(_common, "console", _common.Console())
    long_title = "x" * 150
    plan = [
        PlannedRequest("POST", "/courses/1/modules", {"module": {"name": long_title}})
    ]
    expected = f"  {format_plan(plan)[0]}"
    assert len(expected) > 80

    _common.print_plan(_FakeClient(plan), err=err)  # ty: ignore[invalid-argument-type]

    captured = capsys.readouterr()
    stream = captured.err if err else captured.out
    assert expected in stream.splitlines()
