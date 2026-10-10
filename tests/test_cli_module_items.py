"""``cass canvas modules show`` and ``modules items`` against a fake Canvas."""

from __future__ import annotations

__docformat__ = "google"

import json
from collections.abc import Iterator
from urllib.parse import parse_qs

import httpx
import pytest
from typer.testing import CliRunner

from cass.actions.config import reset_config, set_config_path
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()
API = "/api/v1"
CASS_TOML = """\
[canvas]
base_url = "https://canvas.example.com"
course_id = 1
"""

MODULE = {"id": 5, "name": "Week 1", "position": 1, "published": True}
ITEMS = [
    {"id": 21, "title": "Reading", "type": "SubHeader", "position": 1, "indent": 0,
     "published": True},
    {"id": 22, "title": "HW1", "type": "Assignment", "content_id": 7, "position": 2,
     "indent": 1, "published": False},
    {"id": 23, "title": "Dup", "type": "SubHeader", "position": 3, "indent": 0},
    {"id": 24, "title": "Dup", "type": "SubHeader", "position": 4, "indent": 0},
]  # fmt: skip


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture
def sent(tmp_path, monkeypatch) -> list[httpx.Request]:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cass.toml").write_text(CASS_TOML)
    requests: list[httpx.Request] = []
    routes: dict[str, object] = {
        "/courses/1/modules": [MODULE],
        "/courses/1/modules/5": MODULE,
        "/courses/1/modules/5/items": ITEMS,
        **{f"/courses/1/modules/5/items/{i['id']}": i for i in ITEMS},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path.removeprefix(API)
        if request.method == "GET":
            return httpx.Response(200, json=routes.get(path, []))
        form = parse_qs(request.content.decode())
        title = form.get("module_item[title]", ["New"])[0]
        return httpx.Response(200, json={"id": 99, "title": title})

    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(handler),
            dry_run=dry_run,
        ),
    )
    return requests


def _writes(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in requests if r.method != "GET"]


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_show_lists_position_and_indent(sent):
    result = runner.invoke(app, ["canvas", "modules", "show", "Week 1"])
    assert result.exit_code == 0, result.output
    assert "Indent" in result.stdout
    assert "Reading" in result.stdout

    result = runner.invoke(app, ["canvas", "modules", "show", "Week 1", "--json"])
    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)
    assert "indent" in record["items"][0]
    assert "type" in record["items"][0]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["--type", "Assignment", "--content-id", "7"],
            {"module_item[type]": "Assignment", "module_item[content_id]": "7"},
        ),
        (
            ["--type", "page", "--page-url", "week-1"],
            {"module_item[type]": "Page", "module_item[page_url]": "week-1"},
        ),
        (
            ["--type", "ExternalUrl", "--url", "https://x.org", "--title", "Site"],
            {
                "module_item[type]": "ExternalUrl",
                "module_item[external_url]": "https://x.org",
                "module_item[title]": "Site",
            },
        ),
        (
            ["--type", "SubHeader", "--title", "Week 2", "--indent", "1"],
            {
                "module_item[type]": "SubHeader",
                "module_item[title]": "Week 2",
                "module_item[indent]": "1",
            },
        ),
    ],
)
def test_items_add_sends_reference(sent, args, expected):
    result = runner.invoke(app, ["canvas", "modules", "items", "add", "Week 1", *args])
    assert result.exit_code == 0, result.output
    (post,) = _writes(sent)
    assert post.method == "POST"
    assert _form(post) == expected


@pytest.mark.parametrize(
    "args",
    [
        ["--type", "Page"],
        ["--type", "SubHeader", "--content-id", "1", "--title", "x"],
        ["--type", "ExternalUrl", "--url", "u"],
        ["--type", "Discussion", "--content-id", "1"],
    ],
)
def test_items_add_bad_reference_exits_2(sent, args):
    result = runner.invoke(app, ["canvas", "modules", "items", "add", "Week 1", *args])
    assert result.exit_code == 2, result.output
    assert _writes(sent) == []


def test_items_update_by_title_skips_unchanged_published(sent):
    result = runner.invoke(
        app,
        [
            *("canvas", "modules", "items", "update", "Week 1", "Reading"),
            *("--title", "Readings", "--publish"),
        ],
    )
    assert result.exit_code == 0, result.output
    (put,) = _writes(sent)
    assert (put.method, put.url.path) == ("PUT", f"{API}/courses/1/modules/5/items/21")
    assert _form(put) == {"module_item[title]": "Readings"}


def test_items_update_without_options_exits_2(sent):
    result = runner.invoke(
        app, ["canvas", "modules", "items", "update", "Week 1", "Reading"]
    )
    assert result.exit_code == 2, result.output
    assert _writes(sent) == []


def test_items_update_ambiguous_title_exits_1(sent, monkeypatch, capsys):
    from cass.cli import run

    argv = ["cass", "canvas", "modules", "items", "update", "Week 1", "Dup"]
    monkeypatch.setattr("sys.argv", [*argv, "--title", "X"])
    with pytest.raises(SystemExit) as exc_info:
        run()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "23" in err
    assert "24" in err
    assert _writes(sent) == []


def test_items_move(sent):
    result = runner.invoke(
        app,
        ["canvas", "modules", "items", "move", "Week 1", "22", "--position", "1"],
    )
    assert result.exit_code == 0, result.output
    (put,) = _writes(sent)
    assert put.url.path == f"{API}/courses/1/modules/5/items/22"
    assert _form(put) == {"module_item[position]": "1"}


def test_items_move_position_zero_exits_2(sent):
    result = runner.invoke(
        app,
        ["canvas", "modules", "items", "move", "Week 1", "22", "--position", "0"],
    )
    assert result.exit_code == 2, result.output
    assert _writes(sent) == []


def test_items_remove_requires_yes_without_tty(sent):
    args = ["canvas", "modules", "items", "remove", "Week 1", "21"]
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert _writes(sent) == []

    result = runner.invoke(app, [*args, "--yes"])
    assert result.exit_code == 0, result.output
    (delete,) = _writes(sent)
    assert (delete.method, delete.url.path) == (
        "DELETE",
        f"{API}/courses/1/modules/5/items/21",
    )


@pytest.mark.parametrize(
    "args",
    [
        ["add", "Week 1", "--type", "Assignment", "--content-id", "7"],
        ["update", "Week 1", "Reading", "--title", "Readings"],
        ["move", "Week 1", "21", "--position", "2"],
        ["remove", "Week 1", "21"],
    ],
)
def test_items_dry_run_sends_nothing(sent, args):
    result = runner.invoke(app, ["canvas", "modules", "items", *args, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert _writes(sent) == []
    assert any(w in result.stdout for w in ("PUT /", "POST /", "DELETE /"))
