"""Tests for cass.apis.canvas.auth — token and session-cookie authentication."""

import httpx
import pytest

from cass.apis.canvas.auth import (
    CREDS_FILENAME,
    TOKEN_FILENAME,
    CanvasAuthError,
    SessionAuth,
    TokenAuth,
    find_auth,
    parse_creds,
)
from cass.apis.canvas.client import CanvasClient, RetryTransport

CSRF_DECODED = "abc+/def=="
CSRF_ENCODED = "abc%2B%2Fdef%3D%3D"


class TestParseCreds:
    def test_strips_quotes_and_whitespace(self):
        text = f'canvas_session = "sess123"\n_csrf_token="{CSRF_DECODED}"  \n'
        auth = parse_creds(text)
        assert auth.session == "sess123"
        assert auth.csrf_token == CSRF_DECODED

    def test_url_decodes_csrf_token(self):
        auth = parse_creds(f"canvas_session=s\n_csrf_token={CSRF_ENCODED}\n")
        assert auth.csrf_token == CSRF_DECODED

    def test_ignores_comments_and_blank_lines(self):
        auth = parse_creds("# copied from devtools\n\ncanvas_session=s\n")
        assert auth.session == "s"

    def test_missing_session_raises(self):
        with pytest.raises(SystemExit, match="canvas_session"):
            parse_creds("_csrf_token=x\n")

    def test_csrf_optional(self):
        auth = parse_creds("canvas_session=s\n")
        assert auth.csrf_token == ""


class TestFindAuth:
    def test_creds_file_wins_over_token_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CANVAS_TOKEN", "env-token")
        (tmp_path / TOKEN_FILENAME).write_text("file-token\n")
        (tmp_path / CREDS_FILENAME).write_text("canvas_session=s\n")
        auth = find_auth(tmp_path)
        assert isinstance(auth, SessionAuth)
        assert auth.source == CREDS_FILENAME

    def test_token_file_wins_over_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CANVAS_TOKEN", "env-token")
        (tmp_path / TOKEN_FILENAME).write_text("file-token\n")
        auth = find_auth(tmp_path)
        assert auth == TokenAuth(token="file-token", source=TOKEN_FILENAME)

    def test_env_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CANVAS_TOKEN", "env-token")
        auth = find_auth(tmp_path)
        assert auth == TokenAuth(token="env-token", source="$CANVAS_TOKEN")

    def test_none_when_nothing_configured(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CANVAS_TOKEN", raising=False)
        assert find_auth(tmp_path) is None

    def test_empty_files_are_ignored(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CANVAS_TOKEN", raising=False)
        (tmp_path / TOKEN_FILENAME).write_text("  \n")
        (tmp_path / CREDS_FILENAME).write_text("\n")
        assert find_auth(tmp_path) is None


class TestAuthHeaders:
    def test_token_auth_uses_bearer_header(self):
        auth = TokenAuth(token="t", source=TOKEN_FILENAME)
        assert auth.headers() == {"Authorization": "Bearer t"}
        assert auth.cookies() == {}

    def test_session_auth_encodes_cookie_and_decodes_header(self):
        auth = SessionAuth(session="s", csrf_token=CSRF_DECODED, source=CREDS_FILENAME)
        assert auth.cookies() == {"canvas_session": "s", "_csrf_token": CSRF_ENCODED}
        assert auth.headers() == {"X-CSRF-Token": CSRF_DECODED}

    def test_session_auth_without_csrf_sends_no_csrf(self):
        auth = SessionAuth(session="s", csrf_token="", source=CREDS_FILENAME)
        assert auth.cookies() == {"canvas_session": "s"}
        assert auth.headers() == {}


# --- Client integration via mock transport ---


def _client(auth, handler) -> CanvasClient:
    transport = RetryTransport(auth=auth, wrapped=httpx.MockTransport(handler))
    return CanvasClient(
        base_url="https://canvas.example.com",
        auth=auth,
        course_id=1,
        transport=transport,
    )


def _json(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body)


SESSION = SessionAuth(session="s", csrf_token=CSRF_DECODED, source=CREDS_FILENAME)
TOKEN = TokenAuth(token="t", source=TOKEN_FILENAME)
UNAUTHENTICATED = {
    "status": "unauthenticated",
    "errors": [{"message": "user authorization required"}],
}
CSRF_REJECTED = {
    "errors": [{"message": "An error occurred.", "error_code": "unprocessable_content"}]
}


class TestClientSessionAuth:
    def test_sends_cookies_and_csrf_header(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _json(200, {"id": 1, "name": "Course"})

        with _client(SESSION, handler) as c:
            c.get_course()

        req = seen[0]
        assert "Authorization" not in req.headers
        assert req.headers["X-CSRF-Token"] == CSRF_DECODED
        assert f"_csrf_token={CSRF_ENCODED}" in req.headers["Cookie"]
        assert "canvas_session=s" in req.headers["Cookie"]

    def test_token_auth_sends_bearer_only(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _json(200, {"id": 1, "name": "Course"})

        with _client(TOKEN, handler) as c:
            c.get_course()

        assert seen[0].headers["Authorization"] == "Bearer t"
        assert "Cookie" not in seen[0].headers

    def test_401_with_session_explains_how_to_refresh(self):
        with (
            _client(SESSION, lambda r: _json(401, UNAUTHENTICATED)) as c,
            pytest.raises(CanvasAuthError) as exc,
        ):
            c.get_course()
        msg = str(exc.value)
        assert "session" in msg.lower()
        assert CREDS_FILENAME in msg
        assert "canvas_session" in msg
        assert "_csrf_token" in msg

    def test_401_with_token_points_at_token(self):
        body = {"errors": [{"message": "Expired access token."}]}
        with (
            _client(TOKEN, lambda r: _json(401, body)) as c,
            pytest.raises(CanvasAuthError) as exc,
        ):
            c.get_course()
        assert TOKEN_FILENAME in str(exc.value)
        assert "Expired access token" in str(exc.value)

    def test_csrf_rejected_write_explains_csrf(self):
        with (
            _client(SESSION, lambda r: _json(422, CSRF_REJECTED)) as c,
            pytest.raises(CanvasAuthError, match="_csrf_token"),
        ):
            c.update_assignment(5, name="x")

    def test_real_validation_422_is_not_an_auth_error(self):
        body = {"errors": {"name": [{"message": "too long"}]}}
        with (
            _client(SESSION, lambda r: _json(422, body)) as c,
            pytest.raises(httpx.HTTPStatusError),
        ):
            c.update_assignment(5, name="x")

    def test_write_without_csrf_fails_before_request(self):
        no_csrf = SessionAuth(session="s", csrf_token="", source=CREDS_FILENAME)
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.method)
            return _json(200, {})

        with (
            _client(no_csrf, handler) as c,
            pytest.raises(CanvasAuthError, match="_csrf_token"),
        ):
            c.update_assignment(5, name="x")
        assert calls == []

    def test_read_without_csrf_is_allowed(self):
        no_csrf = SessionAuth(session="s", csrf_token="", source=CREDS_FILENAME)
        with _client(no_csrf, lambda r: _json(200, {"id": 1, "name": "C"})) as c:
            assert c.get_course().id == 1
