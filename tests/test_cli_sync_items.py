"""``cass canvas sync`` reconciling declared module items, against a fake Canvas."""

from __future__ import annotations

__docformat__ = "google"

import itertools
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import httpx
import pytest
from typer.testing import CliRunner

from cass.actions.config import reset_config, set_config_path
from cass.actions.module_items import ModuleItemApplyError, ModuleItemLookupError
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()
API = "/api/v1"
CANVAS = """\
[canvas]
base_url = "https://canvas.example.com"
course_id = 1
time_zone = "America/Los_Angeles"
"""
WEEK_1_ITEMS = """
[[canvas.modules]]
name = "Week 1"
published = true

[[canvas.modules.items]]
type = "SubHeader"
title = "Week 1"

[[canvas.modules.items]]
type = "File"
file = "readings/w1.pdf"
source = "w1.pdf"

[[canvas.modules.items]]
type = "Assignment"
title = "HW1"
"""

MODULES = [
    {"id": 5, "name": "Week 1", "position": 1, "published": True},
    {"id": 6, "name": "Week 2", "position": 2, "published": True},
]
FOLDERS = [
    {"id": 2, "name": "course files", "full_name": "course files"},
    {
        "id": 3,
        "name": "readings",
        "full_name": "course files/readings",
        "parent_folder_id": 2,
    },
]
WEEK_1_LIVE = [
    {"id": 31, "title": "Week 1", "type": "SubHeader", "position": 1},
    {
        "id": 33,
        "title": "Old",
        "type": "ExternalUrl",
        "external_url": "https://old.org",
        "position": 2,
    },
]
UPLOADED_FILE = {
    "id": 77,
    "display_name": "w1.pdf",
    "folder_id": 3,
    "size": 4,
    "locked": False,
}


@dataclass
class FakeCourse:
    """Requests the fake Canvas received and the clients the CLI built."""

    requests: list[httpx.Request] = field(default_factory=list)
    clients: list[CanvasClient] = field(default_factory=list)
    fail_writes: set[str] = field(default_factory=set)  # paths that answer 400

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]

    def gets(self) -> list[str]:
        return [r.url.path for r in self.requests if r.method == "GET"]


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture
def sync_course(tmp_path, monkeypatch) -> FakeCourse:
    """A fake course: modules Week 1 (id 5) and Week 2 (id 6), HW1 (id 7)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "w1.pdf").write_bytes(b"1234")
    course = FakeCourse()
    routes: dict[str, object] = {
        "/courses/1/modules": MODULES,
        "/courses/1/assignments": [{"id": 7, "name": "HW1", "published": True}],
        "/courses/1/quizzes": [],
        "/courses/1/pages": [],
        "/courses/1/folders": FOLDERS,
        "/courses/1/files": [],
        "/courses/1/modules/5/items": WEEK_1_LIVE,
        "/courses/1/modules/6/items": [],
        **{f"/courses/1/modules/5/items/{i['id']}": i for i in WEEK_1_LIVE},
        **{f"/courses/1/modules/{m['id']}": m for m in MODULES},
    }
    new_ids = itertools.count(100)

    def handler(request: httpx.Request) -> httpx.Response:
        course.requests.append(request)
        path = request.url.path.removeprefix(API)
        if request.method == "GET":
            # Unknown paths 404 so a missing route fails where it is used;
            # only item lists of modules this sync creates default to empty.
            if path in routes:
                return httpx.Response(200, json=routes[path])
            if re.fullmatch(r"/courses/1/modules/\d+/items", path):
                return httpx.Response(200, json=[])
            return httpx.Response(404, json={"errors": [{"message": "no route"}]})
        if path in course.fail_writes:
            return httpx.Response(400, json={"message": "rejected"})
        if request.method == "POST" and path == "/courses/1/files":
            return httpx.Response(
                200, json={"upload_url": "https://upload.invalid", "upload_params": {}}
            )
        if request.method == "PUT" and path == "/files/77":
            return httpx.Response(200, json=UPLOADED_FILE)
        form = parse_qs(request.content.decode())
        title = form.get("module_item[title]", [""])[0]
        name = form.get("assignment[name]", [""])[0]
        return httpx.Response(
            200, json={"id": next(new_ids), "title": title, "name": name}
        )

    real_post_upload = CanvasClient._post_upload

    def post_upload(self, url, *, data, filename, file):
        if self.dry_run:
            return real_post_upload(self, url, data=data, filename=filename, file=file)
        return httpx.Response(201, json=UPLOADED_FILE)

    monkeypatch.setattr(CanvasClient, "_post_upload", post_upload)

    def make_client(dry_run: bool = False) -> CanvasClient:
        client = CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(handler),
            time_zone="America/Los_Angeles",
            dry_run=dry_run,
        )
        course.clients.append(client)
        return client

    monkeypatch.setattr("cass.cli.canvas._common.client", make_client)
    return course


def write_toml(text: str) -> None:
    with open("cass.toml", "w") as f:
        f.write(CANVAS + text)


def table_rows(stdout: str) -> list[str]:
    """Output lines with column separators dropped and whitespace collapsed."""
    lines = [line.replace("│", " ") for line in stdout.splitlines()]
    return [" ".join(line.split()) for line in lines if line.strip()]


def row_index(rows: list[str], pattern: str) -> int:
    for number, row in enumerate(rows):
        if re.search(pattern, row):
            return number
    raise AssertionError(f"no row matches {pattern!r} in:\n" + "\n".join(rows))


def test_sync_without_items_is_unchanged(sync_course):
    write_toml('\n[[canvas.modules]]\nname = "Week 1"\npublished = true\n')

    result = runner.invoke(app, ["canvas", "sync"])

    assert result.exit_code == 0, result.output
    gets = sync_course.gets()
    for path in ("/pages", "/files", "/modules/5/items"):
        assert not any(get.endswith(path) for get in gets), gets
    summary = row_index(table_rows(result.stdout), r"\d+ create")
    assert table_rows(result.stdout)[summary] == "0 create, 0 update, 1 skip"


def test_omitted_published_leaves_published_content_alone(sync_course):
    write_toml(
        '\n[[canvas.modules]]\nname = "Week 1"\n'
        '\n[[canvas.assignments]]\nname = "HW1"\n'
    )

    result = runner.invoke(app, ["canvas", "sync", "--apply"])

    assert result.exit_code == 0, result.output
    assert sync_course.writes() == []
    rows = table_rows(result.stdout)
    row_index(rows, r"^skip module Week 1$")
    row_index(rows, r"^skip assignment HW1$")


def test_sync_dry_run_shows_upload_then_create(sync_course):
    write_toml(WEEK_1_ITEMS)

    result = runner.invoke(app, ["canvas", "sync"])

    assert result.exit_code == 0, result.output
    assert sync_course.writes() == []
    rows = table_rows(result.stdout)
    upload = row_index(rows, r"^upload file Week 1: readings/w1\.pdf")
    create_file = row_index(rows, r"^create item Week 1: File readings/w1\.pdf")
    assert upload < create_file
    row_index(rows, r"^create item Week 1: Assignment 'HW1'")
    row_index(rows, r"^keep items Week 1: 1 kept")
    row_index(rows, r"^extra item Week 1: ExternalUrl 'Old'")
    row_index(rows, r"1 upload, 0 move, 0 remove, 1 extra$")
    assert "POST /courses/1/modules/5/items" in result.stdout


def test_sync_dry_run_new_module_items_all_create(sync_course):
    write_toml(WEEK_1_ITEMS.replace('name = "Week 1"', 'name = "Week 9"'))

    result = runner.invoke(app, ["canvas", "sync"])

    assert result.exit_code == 0, result.output
    assert sync_course.writes() == []
    item_rows = [row for row in table_rows(result.stdout) if "Week 9:" in row]
    assert [row.split()[0] for row in item_rows] == [
        "create",
        "upload",
        "create",
        "create",
    ]
    assert "POST /courses/1/modules/<new 1>/items" in result.stdout


def test_sync_dry_run_prune_lists_removes(sync_course):
    write_toml(WEEK_1_ITEMS)

    result = runner.invoke(app, ["canvas", "sync", "--prune"])

    assert result.exit_code == 0, result.output
    assert sync_course.writes() == []
    rows = table_rows(result.stdout)
    row_index(rows, r"^remove item Week 1: ExternalUrl 'Old'")
    assert "DELETE /courses/1/modules/5/items/33" in result.stdout


def test_sync_apply_creates_items_and_prunes(sync_course):
    write_toml(WEEK_1_ITEMS)

    result = runner.invoke(app, ["canvas", "sync", "--apply", "--prune"])

    assert result.exit_code == 0, result.output
    sent = [(r.method, r.url.path) for r in sync_course.writes()]
    assert ("POST", f"{API}/courses/1/files") in sent
    assert sent.count(("POST", f"{API}/courses/1/modules/5/items")) == 2
    assert ("DELETE", f"{API}/courses/1/modules/5/items/33") in sent
    assert "Sync complete." in result.stdout


def test_dry_run_item_for_assignment_created_by_same_sync(sync_course):
    write_toml(
        WEEK_1_ITEMS
        + '\n[[canvas.modules.items]]\ntype = "Assignment"\ntitle = "HW2"\n'
        + '\n[[canvas.assignments]]\nname = "HW2"\n'
    )

    result = runner.invoke(app, ["canvas", "sync"])

    assert result.exit_code == 0, result.output
    row_index(table_rows(result.stdout), r"^create item Week 1: Assignment 'HW2'")
    (client,) = sync_course.clients
    planned = client.planned_requests
    # The assignment POST is the first write, so it gets placeholder id -1.
    assert (planned[0].method, planned[0].path) == ("POST", "/courses/1/assignments")
    assert planned[0].body["assignment"]["name"] == "HW2"
    item_posts = [
        p.body["module_item"]
        for p in planned
        if (p.method, p.path) == ("POST", "/courses/1/modules/5/items")
    ]
    hw2 = [body for body in item_posts if str(body.get("content_id")) == "-1"]
    assert len(hw2) == 1
    assert hw2[0]["type"] == "Assignment"


LOOKUP_ERROR_TOML = (
    WEEK_1_ITEMS
    + '\n[[canvas.modules]]\nname = "Week 2"\npublished = false\n'
    + '\n[[canvas.modules.items]]\ntype = "Assignment"\ntitle = "HW9"\n'
)
APPLIED_NOTE = "already applied; no module item changes were sent"


def item_or_file_writes(course: FakeCourse) -> list[tuple[str, str]]:
    return [
        (r.method, r.url.path)
        for r in course.writes()
        if re.search(r"/modules/[^/]+/items|/files", r.url.path)
    ]


def test_lookup_error_sends_no_item_writes(sync_course):
    write_toml(LOOKUP_ERROR_TOML)

    result = runner.invoke(app, ["canvas", "sync", "--apply"])

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, ModuleItemLookupError)
    message = str(result.exception)
    assert "Week 2" in message
    assert "HW9" in message
    assert APPLIED_NOTE in message
    # Week 2's unpublish went out before planning failed; no item writes did.
    sent = [(r.method, r.url.path) for r in sync_course.writes()]
    assert ("PUT", f"{API}/courses/1/modules/6") in sent
    assert item_or_file_writes(sync_course) == []


def test_missing_source_under_apply_has_applied_note(sync_course):
    write_toml(WEEK_1_ITEMS.replace('source = "w1.pdf"', 'source = "gone.pdf"'))

    result = runner.invoke(app, ["canvas", "sync", "--apply"])

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, ModuleItemLookupError)
    assert "gone.pdf" in str(result.exception)
    assert APPLIED_NOTE in str(result.exception)
    assert item_or_file_writes(sync_course) == []


def test_dry_run_lookup_error_has_no_applied_note(sync_course):
    write_toml(LOOKUP_ERROR_TOML)

    result = runner.invoke(app, ["canvas", "sync"])

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, ModuleItemLookupError)
    assert "HW9" in str(result.exception)
    assert APPLIED_NOTE not in str(result.exception)
    assert sync_course.writes() == []


def test_apply_error_propagates_unchanged(sync_course):
    write_toml(WEEK_1_ITEMS)
    sync_course.fail_writes.add("/courses/1/modules/5/items")

    result = runner.invoke(app, ["canvas", "sync", "--apply"])

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, ModuleItemApplyError)
    message = str(result.exception)
    assert "upload readings/w1.pdf" in message
    assert APPLIED_NOTE not in message


def test_markup_in_item_titles_prints_literally(sync_course):
    write_toml(
        '\n[[canvas.modules]]\nname = "Week 1"\npublished = true\n'
        '\n[[canvas.modules.items]]\ntype = "SubHeader"\n'
        'title = "[bold]x[/bold] [/b]"\n'
    )

    result = runner.invoke(app, ["canvas", "sync"])

    assert result.exit_code == 0, result.output
    assert "SubHeader '[bold]x[/bold] [/b]'" in result.stdout
