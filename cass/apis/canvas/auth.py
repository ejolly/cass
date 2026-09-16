"""Canvas authentication — API token or browser session cookie.

Two ways to authenticate against the Canvas API:

* ``TokenAuth``: a personal API token sent as a Bearer header. Read from
  ``.canvastoken`` or ``$CANVAS_TOKEN``.
* ``SessionAuth``: the ``canvas_session`` and ``_csrf_token`` cookies copied
  from a logged-in browser. Read from ``.canvascreds``. Useful when no API
  token is available; cookies expire after roughly a day.

``find_auth`` picks whichever is configured, preferring ``.canvascreds`` so a
deliberately created cookie file overrides a stale token.
"""

from __future__ import annotations

__docformat__ = "google"

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

import httpx

CREDS_FILENAME = ".canvascreds"
TOKEN_FILENAME = ".canvastoken"
ENV_TOKEN = "CANVAS_TOKEN"

SESSION_COOKIE = "canvas_session"
CSRF_COOKIE = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CanvasAuthError(RuntimeError):
    """Canvas rejected our credentials, with instructions on how to fix them."""


@dataclass(frozen=True)
class BraveSource:
    """Browser profile and Canvas origin authorized to refresh a credential file."""

    profile: str
    origin: str
    path: Path


@dataclass(frozen=True)
class TokenAuth:
    """Bearer-token authentication.

    Args:
        token: Canvas personal API token.
        source: Where the token came from (file name or ``$CANVAS_TOKEN``).
    """

    token: str
    source: str

    @property
    def description(self) -> str:
        """Short human label for status output."""
        return f"token ({self.source})"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def cookies(self) -> dict[str, str]:
        return {}

    def rejected_message(self, detail: str) -> str:
        return (
            f"Canvas rejected the API token from {self.source}: {detail}\n"
            f"Create a new token under Account > Settings > Approved Integrations "
            f"and run 'cass init', or save it to {TOKEN_FILENAME}."
        )


@dataclass(frozen=True)
class SessionAuth:
    """Browser session-cookie authentication.

    Args:
        session: Value of the ``canvas_session`` cookie.
        csrf_token: URL-decoded value of the ``_csrf_token`` cookie. Required
            for writes (Canvas checks it against the ``X-CSRF-Token`` header);
            may be empty for read-only use.
        source: File the cookies were read from.
        brave: Profile to refresh from, present only for imported Brave sessions.
    """

    session: str
    csrf_token: str
    source: str
    brave: BraveSource | None = None

    @property
    def description(self) -> str:
        """Short human label for status output."""
        suffix = ", auto-refresh from Brave" if self.brave else ""
        if not self.csrf_token:
            suffix += ", read-only: no _csrf_token"
        return f"session cookie ({self.source}{suffix})"

    def headers(self) -> dict[str, str]:
        return {CSRF_HEADER: self.csrf_token} if self.csrf_token else {}

    def cookies(self) -> dict[str, str]:
        cookies = {SESSION_COOKIE: self.session}
        if self.csrf_token:
            # Canvas stores the CSRF token URL-encoded in the cookie but
            # expects the decoded value in the header.
            cookies[CSRF_COOKIE] = quote(self.csrf_token, safe="")
        return cookies

    def rejected_message(self, detail: str) -> str:
        return (
            f"Canvas rejected the session cookie from {self.source}: {detail}\n"
            f"{self.refresh_message()} Delete {self.source} to use an API token."
        )

    def refresh_message(self) -> str:
        if self.brave:
            import shlex

            profile = self.brave.profile
            option = (
                f" --profile {shlex.quote(profile)}" if profile != "Default" else ""
            )
            return (
                "Log in to Canvas in Brave, then run "
                f"'cass canvas login --from-brave{option}' and retry."
            )
        return (
            "Log in to Canvas in Brave and run 'cass canvas login --from-brave', "
            f"or copy fresh {SESSION_COOKIE} and {CSRF_COOKIE} cookies into "
            f"{self.source}, then retry."
        )

    def csrf_rejected_message(self) -> str:
        return (
            f"Canvas rejected the write (CSRF check failed). The {CSRF_COOKIE} "
            f"value in {self.source} may be stale or mis-copied. "
            f"{self.refresh_message()}"
        )

    def csrf_missing_message(self) -> str:
        return (
            f"Writing to Canvas with a session cookie requires the {CSRF_COOKIE} "
            f"cookie, but {self.source} only has {SESSION_COOKIE}. "
            f"{self.refresh_message()}"
        )


CanvasAuth = TokenAuth | SessionAuth


def _clean_value(raw: str) -> str:
    """Strip whitespace and surrounding quotes from a pasted cookie value."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def parse_creds(
    text: str, source: str = CREDS_FILENAME, *, path: Path | None = None
) -> SessionAuth:
    """Parse a ``.canvascreds`` file of ``name=value`` cookie lines.

    Values may be quoted (as copied from browser devtools) and the CSRF token
    may be URL-encoded or decoded; both forms are normalised.

    Raises:
        SystemExit: If ``canvas_session`` is missing.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = _clean_value(value)

    session = values.get(SESSION_COOKIE, "")
    if not session:
        raise SystemExit(
            f"{source} must contain a '{SESSION_COOKIE}=...' line copied from "
            f"your browser's cookies for Canvas."
        )
    csrf_token = unquote(values.get(CSRF_COOKIE, ""))
    brave = None
    if values.get("browser") == "brave":
        origin = values.get("canvas_origin", "")
        profile = values.get("browser_profile", "")
        if not origin or not profile:
            raise CanvasAuthError(
                "Incomplete Brave credentials. Run 'cass canvas login --from-brave'."
            )
        brave = BraveSource(profile, origin, path or Path(source).resolve())
    return SessionAuth(
        session=session, csrf_token=csrf_token, source=source, brave=brave
    )


def find_auth(root: Path) -> CanvasAuth | None:
    """Locate Canvas credentials for the project at *root*.

    Order: ``.canvascreds`` (session cookie), ``.canvastoken``, ``$CANVAS_TOKEN``.

    Returns:
        The configured auth, or ``None`` if nothing usable was found.
    """
    creds_path = root / CREDS_FILENAME
    if creds_path.exists():
        text = creds_path.read_text()
        if text.strip():
            return parse_creds(text, path=creds_path.resolve())

    token_path = root / TOKEN_FILENAME
    if token_path.exists():
        token = token_path.read_text().strip()
        if token:
            return TokenAuth(token=token, source=TOKEN_FILENAME)

    token = os.environ.get(ENV_TOKEN, "")
    if token:
        return TokenAuth(token=token, source=f"${ENV_TOKEN}")
    return None


def _error_detail(response: httpx.Response) -> str:
    """Best-effort extraction of Canvas's error message from a response."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict) and "message" in first:
            return str(first["message"])
    return f"HTTP {response.status_code}"


def _is_csrf_rejection(response: httpx.Response) -> bool:
    """Canvas answers a failed CSRF check with a bare, generic 422 body."""
    if response.status_code != 422:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    errors = body.get("errors") if isinstance(body, dict) else None
    if not isinstance(errors, list) or not errors:
        return False
    first = errors[0]
    return (
        isinstance(first, dict) and first.get("error_code") == "unprocessable_content"
    )


def check_request(auth: CanvasAuth, request: httpx.Request) -> None:
    """Fail fast before sending a request the credentials cannot satisfy.

    Raises:
        CanvasAuthError: For a write with a session cookie but no CSRF token.
    """
    if (
        isinstance(auth, SessionAuth)
        and not auth.csrf_token
        and request.method.upper() not in _SAFE_METHODS
    ):
        raise CanvasAuthError(auth.csrf_missing_message())


def check_response(auth: CanvasAuth, response: httpx.Response) -> None:
    """Translate credential failures into a ``CanvasAuthError`` with guidance.

    Raises:
        CanvasAuthError: On 401, or on a CSRF-rejected write under session auth.
    """
    if response.status_code == 401:
        raise CanvasAuthError(auth.rejected_message(_error_detail(response)))
    if isinstance(auth, SessionAuth) and _is_csrf_rejection(response):
        raise CanvasAuthError(auth.csrf_rejected_message())
