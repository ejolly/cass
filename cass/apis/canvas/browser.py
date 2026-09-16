"""Import a Canvas session from Brave on macOS."""

from __future__ import annotations

__docformat__ = "google"

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from .auth import (
    CREDS_FILENAME,
    CSRF_COOKIE,
    SESSION_COOKIE,
    BraveSource,
    CanvasAuthError,
    SessionAuth,
)


def read_brave_session(source: BraveSource) -> SessionAuth:
    """Read Canvas cookies from one profile, using macOS Keychain access."""
    import browser_cookie3

    auth = SessionAuth("", "", CREDS_FILENAME, brave=source)
    if sys.platform != "darwin":
        raise CanvasAuthError("Importing from Brave currently requires macOS.")
    if (
        not source.profile
        or source.profile in {".", ".."}
        or any(c in source.profile for c in "/\\\r\n\0")
    ):
        raise CanvasAuthError("Use a Brave profile directory name, such as 'Default'.")
    url = urlsplit(source.origin)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise CanvasAuthError("Canvas base_url must be an HTTPS origin.")
    profile = (
        Path.home()
        / "Library/Application Support/BraveSoftware/Brave-Browser"
        / source.profile
    )
    cookie_file = next(
        (p for p in (profile / "Cookies", profile / "Network/Cookies") if p.is_file()),
        None,
    )
    if cookie_file is None:
        raise CanvasAuthError(
            f"No Brave cookies found for profile {source.profile!r}. "
            "Choose a profile directory with --profile. " + auth.refresh_message()
        )
    try:
        jar = browser_cookie3.brave(
            cookie_file=str(cookie_file), domain_name=url.hostname
        )
    except Exception:
        # Browser/Keychain exceptions must not expose cookie or key material.
        raise CanvasAuthError(
            "Could not read Brave cookies. Allow access to Brave Safe Storage "
            "if macOS asks. " + auth.refresh_message()
        ) from None
    values: dict[str, str] = {}
    for cookie in jar:
        if (
            cookie.domain.lstrip(".") != url.hostname
            or cookie.path != "/"
            or cookie.name not in {SESSION_COOKIE, CSRF_COOKIE}
            or cookie.is_expired()
            or not cookie.value
        ):
            continue
        if cookie.name in values and values[cookie.name] != cookie.value:
            raise CanvasAuthError(
                "Conflicting Canvas cookies. " + auth.refresh_message()
            )
        values[cookie.name] = cookie.value
    if any(not values.get(name) for name in (SESSION_COOKIE, CSRF_COOKIE)):
        raise CanvasAuthError(
            "Brave has no complete Canvas session for this site. "
            + auth.refresh_message()
        )
    return SessionAuth(
        values[SESSION_COOKIE],
        unquote(values[CSRF_COOKIE]),
        CREDS_FILENAME,
        brave=source,
    )


def validate_session(
    auth: SessionAuth,
    origin: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Check authentication with a read-only request before replacing credentials."""
    try:
        with httpx.Client(
            cookies=auth.cookies(),
            headers=auth.headers(),
            timeout=30,
            follow_redirects=False,
            transport=transport,
        ) as client:
            response = client.get(origin + "/api/v1/users/self")
    except httpx.RequestError:
        raise CanvasAuthError(
            "Could not reach Canvas to validate the Brave session. "
            "Existing credentials were kept; check your connection and retry."
        ) from None
    if response.status_code in {401, 403} or response.is_redirect:
        raise CanvasAuthError(
            "Canvas rejected Brave's session. " + auth.refresh_message()
        )
    if not response.is_success:
        raise CanvasAuthError(
            f"Canvas returned HTTP {response.status_code} while checking the session. "
            "Existing credentials were kept; try again later."
        )
    try:
        user = response.json()
    except ValueError:
        user = None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise CanvasAuthError(
            "Canvas did not return an authenticated user. " + auth.refresh_message()
        )


def save_brave_session(auth: SessionAuth) -> None:
    """Atomically replace the credential file with owner-only permissions."""
    source = auth.brave
    if source is None:
        raise ValueError("A Brave source is required to save imported credentials.")
    values = {
        SESSION_COOKIE: auth.session,
        CSRF_COOKIE: auth.cookies()[CSRF_COOKIE],
        "browser": "brave",
        "browser_profile": source.profile,
        "canvas_origin": source.origin,
    }
    if any("\n" in value or "\r" in value for value in values.values()):
        raise CanvasAuthError("Invalid line break in Canvas credentials.")
    gitignore = source.path.parent / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if CREDS_FILENAME not in existing.splitlines():
        prefix = (
            existing + "\n" if existing and not existing.endswith("\n") else existing
        )
        gitignore.write_text(prefix + CREDS_FILENAME + "\n")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=source.path.parent,
            prefix=".canvascreds-",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            os.fchmod(file.fileno(), 0o600)
            file.write("".join(f"{key}={value}\n" for key, value in values.items()))
        os.replace(temporary, source.path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def login_from_brave(
    root: Path,
    base_url: str,
    profile: str = "Default",
    *,
    transport: httpx.BaseTransport | None = None,
) -> SessionAuth:
    """Import, validate, and save a refreshable Brave session for this project."""
    source = BraveSource(profile, base_url.rstrip("/"), root.resolve() / CREDS_FILENAME)
    auth = read_brave_session(source)
    validate_session(auth, source.origin, transport=transport)
    save_brave_session(auth)
    return auth
