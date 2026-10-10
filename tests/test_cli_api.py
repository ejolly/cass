"""``cass canvas api`` CLI tests."""

from __future__ import annotations

__docformat__ = "google"

import json
from collections.abc import Iterator

import httpx
import pytest
from typer.testing import CliRunner

from cass.actions.config import reset_config, set_config_path
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()
API = "/api/v1"


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture
def canvas(monkeypatch, project_dir):
    monkeypatch.chdir(project_dir)
    sent: list[httpx.Request] = []
    routes: dict[tuple[str, str], httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return routes.get(
            (request.method, request.url.path),
            httpx.Response(404, json={"message": "not found"}),
        )

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
    return sent, routes, handler


def invoke(*args: str):
    return runner.invoke(app, ["canvas", "api", *args])


@pytest.mark.parametrize(
    "args",
    [
        ["GET", "/x", "--param", "oops"],
        ["POST", "/x", "--json-body", "{nope"],
        ["POST", "/x", "--data", "a=1", "--json-body", "{}"],
        ["POST", "/x", "--all"],
    ],
    ids=["pair", "bad_json", "data_and_json", "all_non_get"],
)
def test_rejections(canvas, args):
    sent, _, _ = canvas
    result = invoke(*args)
    assert result.exit_code == 2
    assert sent == []


def test_get_prints_json_unchanged(canvas):
    sent, routes, _ = canvas
    routes[("GET", f"{API}/courses/1/modules")] = httpx.Response(
        200, content=b'[{"id": 5}]', headers={"content-type": "application/json"}
    )
    result = invoke(
        "GET",
        "/courses/{course}/modules",
        "--param",
        "include[]=items",
        "--param",
        "include[]=x",
    )
    assert result.exit_code == 0
    assert result.stdout == '[{"id": 5}]\n'
    assert sent[0].url.params.get_list("include[]") == ["items", "x"]
    assert result.stderr == ""


def test_empty_body_prints_nothing(canvas):
    _, routes, _ = canvas
    routes[("DELETE", f"{API}/courses/1/modules/5")] = httpx.Response(204)
    result = invoke("DELETE", "/courses/{course}/modules/5")
    assert result.exit_code == 0
    assert result.stdout == ""


def test_text_body_printed_as_text(canvas):
    _, routes, _ = canvas
    routes[("GET", f"{API}/x")] = httpx.Response(200, text="hello")
    result = invoke("GET", "/x")
    assert result.stdout == "hello\n"


def test_all_prints_one_array(canvas):
    _, routes, _ = canvas
    routes[("GET", f"{API}/things")] = httpx.Response(
        200,
        json=[{"id": 1}],
        headers={"link": f'<https://canvas.example.com{API}/things2>; rel="next"'},
    )
    routes[("GET", f"{API}/things2")] = httpx.Response(200, json=[{"id": 2}])
    result = invoke("GET", "/things", "--all")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": 1}, {"id": 2}]


def test_non_get_echo_goes_to_stderr(canvas):
    sent, routes, _ = canvas
    routes[("PUT", f"{API}/courses/1/modules/5")] = httpx.Response(200, json={"id": 5})
    result = invoke("PUT", "/courses/{course}/modules/5", "--data", "module[name]=X")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"id": 5}
    assert "PUT https://canvas.example.com/api/v1/courses/1/modules/5" in result.stderr
    assert "module%5Bname%5D=X" in result.stderr
    assert sent[0].content == b"module%5Bname%5D=X"


def test_dry_run_non_get_sends_nothing(canvas):
    sent, _, _ = canvas
    result = invoke(
        "POST",
        "/courses/{course}/modules",
        "--data",
        "module[name]=X",
        "--dry-run",
    )
    assert result.exit_code == 0
    assert [r for r in sent if r.method != "GET"] == []
    assert json.loads(result.stdout)["id"] == -1
    assert "POST /courses/1/modules" in result.stderr


def test_dry_run_get_is_sent(canvas):
    sent, routes, _ = canvas
    routes[("GET", f"{API}/x")] = httpx.Response(200, json={"ok": True})
    result = invoke("GET", "/x", "--dry-run")
    assert result.exit_code == 0
    assert len(sent) == 1
    assert json.loads(result.stdout) == {"ok": True}


def _assert_one_error_line(result):
    assert result.exit_code == 1
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "Traceback" not in result.output
    return lines[0]


def test_canvas_api_error(canvas):
    _, routes, _ = canvas
    routes[("GET", f"{API}/x")] = httpx.Response(
        403, json={"errors": [{"message": "unauthorized"}]}
    )
    line = _assert_one_error_line(invoke("GET", "/x"))
    assert "403" in line
    assert "unauthorized" in line


def test_auth_error(canvas):
    _, routes, _ = canvas
    routes[("GET", f"{API}/x")] = httpx.Response(401, json={"message": "bad token"})
    _assert_one_error_line(invoke("GET", "/x"))


def test_transport_error(monkeypatch, canvas):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(boom),
            time_zone="America/Los_Angeles",
            dry_run=dry_run,
        ),
    )
    _assert_one_error_line(invoke("GET", "/x"))
