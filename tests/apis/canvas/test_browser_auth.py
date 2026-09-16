"""Brave import and bounded automatic renewal, without real browser access."""

from pathlib import Path

import httpx
import pytest

from cass.apis.canvas.auth import CanvasAuthError, SessionAuth, find_auth
from cass.apis.canvas.client import CanvasClient

ORIGIN = "https://canvas.example.com"


@pytest.fixture
def brave(monkeypatch, tmp_path):
    import browser_cookie3

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cookie_file = (
        tmp_path
        / "Library/Application Support/BraveSoftware/Brave-Browser"
        / "Default/Cookies"
    )
    cookie_file.parent.mkdir(parents=True)
    cookie_file.touch()
    jar = httpx.Cookies()
    jar.set("canvas_session", "fresh-session", domain="canvas.example.com")
    jar.set("_csrf_token", "fresh%2Bcsrf", domain="canvas.example.com")

    def read(*, cookie_file, domain_name):
        assert cookie_file.endswith("Default/Cookies")
        assert domain_name == "canvas.example.com"
        return jar.jar

    monkeypatch.setattr(browser_cookie3, "brave", read)
    return jar


def test_login_validates_then_saves_private_credentials(brave, tmp_path):
    from cass.apis.canvas.browser import login_from_brave

    def handler(request):
        assert str(request.url) == ORIGIN + "/api/v1/users/self"
        assert "canvas_session=fresh-session" in request.headers["cookie"]
        return httpx.Response(200, json={"id": 42})

    login_from_brave(tmp_path, ORIGIN, transport=httpx.MockTransport(handler))
    path = tmp_path / ".canvascreds"
    assert path.stat().st_mode & 0o777 == 0o600
    auth = find_auth(tmp_path)
    assert isinstance(auth, SessionAuth)
    assert auth.session == "fresh-session"
    assert auth.csrf_token == "fresh+csrf"
    assert auth.brave.profile == "Default"
    assert auth.brave.origin == ORIGIN
    assert auth.brave.path == path
    assert ".canvascreds" in (tmp_path / ".gitignore").read_text().splitlines()


@pytest.mark.parametrize("status", [401, 302, 500])
def test_failed_validation_preserves_existing_credentials(brave, tmp_path, status):
    from cass.apis.canvas.browser import login_from_brave

    path = tmp_path / ".canvascreds"
    path.write_text("canvas_session=old\n")
    with pytest.raises(CanvasAuthError):
        login_from_brave(
            tmp_path,
            ORIGIN,
            transport=httpx.MockTransport(lambda r: httpx.Response(status)),
        )
    assert path.read_text() == "canvas_session=old\n"


def test_import_ignores_other_domains_and_cookie_names(brave, tmp_path):
    from cass.apis.canvas.browser import login_from_brave

    brave.set("canvas_session", "wrong", domain="canvas.example.com.attacker.com")
    brave.set("unrelated", "secret", domain="canvas.example.com")
    login_from_brave(
        tmp_path,
        ORIGIN,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": 1})),
    )
    text = (tmp_path / ".canvascreds").read_text()
    assert "fresh-session" in text
    assert "wrong" not in text
    assert "secret" not in text


def test_missing_cookie_gives_login_command(brave, tmp_path):
    from cass.apis.canvas.browser import login_from_brave

    brave.delete("_csrf_token", domain="canvas.example.com")
    with pytest.raises(CanvasAuthError, match="cass canvas login --from-brave"):
        login_from_brave(tmp_path, ORIGIN)
    assert not (tmp_path / ".canvascreds").exists()


@pytest.mark.parametrize("profile", ["../Default", "/tmp/profile", "bad\nprofile"])
def test_profile_must_be_a_directory_name(tmp_path, profile):
    from cass.apis.canvas.browser import login_from_brave

    with pytest.raises(CanvasAuthError, match="profile"):
        login_from_brave(tmp_path, ORIGIN, profile)


def _imported_auth(tmp_path):
    (tmp_path / ".canvascreds").write_text(
        "canvas_session=old\n_csrf_token=old-csrf\n"
        "browser=brave\nbrowser_profile=Default\n"
        f"canvas_origin={ORIGIN}\n"
    )
    return find_auth(tmp_path)


def test_401_refresh_retries_and_keeps_new_auth_for_later_requests(
    brave,
    tmp_path,
    monkeypatch,
):
    from cass.apis.canvas import browser

    monkeypatch.setattr(browser, "validate_session", lambda auth, origin, **kw: None)
    requests = []

    def handler(request):
        requests.append((request.headers["cookie"], request.headers["X-CSRF-Token"]))
        if len(requests) == 1:
            return httpx.Response(401, json={})
        assert "canvas_session=fresh-session" in request.headers["cookie"]
        assert request.headers["X-CSRF-Token"] == "fresh+csrf"
        return httpx.Response(200, json={"id": 1, "name": "Course"})

    with CanvasClient(
        ORIGIN,
        course_id=1,
        auth=_imported_auth(tmp_path),
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get_course()
        client.get_course()
    assert len(requests) == 3
    assert find_auth(tmp_path).session == "fresh-session"


def test_failed_refresh_does_not_loop(brave, tmp_path, monkeypatch):
    from cass.apis.canvas import browser

    monkeypatch.setattr(browser, "validate_session", lambda auth, origin, **kw: None)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={})

    with (
        CanvasClient(
            ORIGIN,
            course_id=1,
            auth=_imported_auth(tmp_path),
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(CanvasAuthError, match="cass canvas login --from-brave"),
    ):
        client.get_course()
    assert len(requests) == 2


@pytest.mark.parametrize("status", [403, 422, 500])
def test_other_errors_never_replay_a_write(brave, tmp_path, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={})

    with (
        CanvasClient(
            ORIGIN,
            course_id=1,
            auth=_imported_auth(tmp_path),
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.update_assignment(5, name="unchanged")
    assert len(requests) == 1


def test_imported_credentials_cannot_be_sent_to_another_origin(tmp_path):
    with pytest.raises(CanvasAuthError, match="origin"):
        CanvasClient(
            "https://other.example.com", course_id=1, auth=_imported_auth(tmp_path)
        )


def test_rate_limit_does_not_reset_refresh_budget(brave, tmp_path, monkeypatch):
    from cass.apis.canvas import browser

    monkeypatch.setattr(browser, "validate_session", lambda auth, origin, **kw: None)
    statuses = iter([401, 429, 401, 200])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(next(statuses), headers={"Retry-After": "0"}, json={})

    with (
        CanvasClient(
            ORIGIN,
            course_id=1,
            auth=_imported_auth(tmp_path),
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(CanvasAuthError),
    ):
        client.get_course()
    assert len(requests) == 3


def test_login_cli_imports_and_reports_errors(brave, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from cass.actions.config import reset_config
    from cass.apis.canvas import browser
    from cass.cli import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "cass.toml").write_text(
        f'[canvas]\nbase_url = "{ORIGIN}"\ncourse_id = 1\n'
    )
    monkeypatch.setattr(browser, "validate_session", lambda auth, origin, **kw: None)
    reset_config()
    try:
        result = CliRunner().invoke(app, ["canvas", "login", "--from-brave"])
        assert result.exit_code == 0, result.output
        assert "saved" in result.output
        assert "fresh-session" not in result.output
        assert (tmp_path / ".canvascreds").exists()
        result = CliRunner().invoke(
            app, ["canvas", "login", "--from-brave", "--profile", "missing"]
        )
        assert result.exit_code == 1
        assert "No Brave cookies" in result.output
    finally:
        reset_config()
