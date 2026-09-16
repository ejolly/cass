"""Canvas client foundation — auth lookup, HTTP transport, and ``BaseClient``.

Resource mixins in this package subclass ``BaseClient`` and are combined into
``CanvasClient`` in ``__init__``."""

from __future__ import annotations

__docformat__ = "google"

import logging
import re
import time
from collections.abc import Callable
from typing import Any, Self, TypeVar

import httpx
from rich.console import Console

from .... import __version__
from ....actions.config import get_config
from ..auth import (
    TOKEN_FILENAME,
    CanvasAuth,
    CanvasAuthError,
    SessionAuth,
    TokenAuth,
    check_request,
    check_response,
    find_auth,
)

T = TypeVar("T")

_console = Console(stderr=True)
_log = logging.getLogger(__name__)

MAX_RETRIES = 3
THROTTLE_THRESHOLD = 50.0
THROTTLE_DELAY = 1.0

# --- Credentials ---


def get_auth() -> CanvasAuth:
    """Locate Canvas credentials for the current project.

    Prefers ``.canvascreds`` (browser session cookie), then ``.canvastoken``,
    then ``$CANVAS_TOKEN``.

    Raises:
        SystemExit: If no credentials are found.
    """
    auth = find_auth(get_config().root)
    if auth is None:
        raise SystemExit(
            "Canvas credentials not found. Run 'cass init' to save an API token "
            f"to {TOKEN_FILENAME}, set the CANVAS_TOKEN environment variable, or "
            "run 'cass canvas login' with --from-brave or --from-chrome "
            "to use your browser session."
        )
    return auth


def get_token() -> str:
    """Read the Canvas API token from ``.canvastoken`` or ``$CANVAS_TOKEN``.

    Raises:
        SystemExit: If no token is found.
    """
    auth = get_auth()
    if not isinstance(auth, TokenAuth):
        raise SystemExit(
            f"A Canvas API token is required here, but only a session cookie "
            f"({auth.source}) is configured."
        )
    return auth.token


def save_token(token: str) -> None:
    """Write a Canvas API token to ``.canvastoken``."""
    cfg = get_config()
    token_path = cfg.root / TOKEN_FILENAME
    token_path.write_text(token.strip() + "\n")


# --- HTTP transport ---


class RetryTransport(httpx.BaseTransport):
    """Wraps a transport with 429 retry, backoff, throttling, and auth checks.

    Args:
        auth: Credentials in use; credential failures (401, CSRF rejection)
            are raised as ``CanvasAuthError`` with instructions to fix them.
        retries: Connection-level retries for the underlying HTTP transport.
        wrapped: Transport to delegate to (defaults to ``httpx.HTTPTransport``;
            tests pass an ``httpx.MockTransport``).
        refresh: Import fresh credentials after a 401, at most once per request.
    """

    def __init__(
        self,
        *,
        auth: CanvasAuth,
        retries: int = 0,
        wrapped: httpx.BaseTransport | None = None,
        refresh: Callable[[], SessionAuth] | None = None,
    ) -> None:
        self._auth = auth
        self._wrapped = wrapped or httpx.HTTPTransport(retries=retries)
        self._refresh = refresh

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        check_request(self._auth, request)
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            response = self._wrapped.handle_request(request)
            response.read()
            if response.status_code == 401 and self._refresh and not refreshed:
                response.close()
                _console.print(
                    "[yellow]Canvas rejected the session; "
                    "refreshing from your browser…[/yellow]"
                )
                self._auth = self._refresh()
                refreshed = True
                request.headers.update(self._auth.headers())
                request.headers.pop("Cookie", None)
                httpx.Cookies(self._auth.cookies()).set_cookie_header(request)
                # Replay only an explicit authentication rejection, at most once.
                response = self._wrapped.handle_request(request)
                response.read()
            try:
                check_response(self._auth, response)
            except CanvasAuthError:
                response.close()
                raise

            if response.status_code == 429:
                if attempt == MAX_RETRIES:
                    return response  # let raise_for_status handle it
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else 2**attempt
                response.close()
                _console.print(
                    f"[yellow]Canvas rate limit hit, retrying in {wait:.0f}s…[/yellow]"
                )
                time.sleep(wait)
                continue

            # Proactive throttle when remaining quota is low
            remaining = response.headers.get("X-Rate-Limit-Remaining")
            if remaining:
                try:
                    if float(remaining) < THROTTLE_THRESHOLD:
                        _log.debug(
                            "Rate limit remaining %.1f, throttling", float(remaining)
                        )
                        time.sleep(THROTTLE_DELAY)
                except ValueError:
                    pass

            # Log request cost at debug level
            cost = response.headers.get("X-Request-Cost")
            if cost:
                _log.debug("Request cost: %s", cost)

            return response

        # Should not reach here, but satisfy the type checker
        raise RuntimeError("Canvas API rate limit exceeded after retries")

    def close(self) -> None:
        self._wrapped.close()


_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class BaseClient:
    """Typed Canvas LMS API client with course_id baked in.

    Args:
        base_url: Canvas instance URL (e.g. ``https://canvas.ucsd.edu``).
        token: Canvas API bearer token (shortcut for ``auth=TokenAuth(...)``).
        course_id: Canvas course ID for all requests.
        auth: Credentials to use; defaults to whatever ``get_auth`` finds.
        transport: HTTP transport override (tests inject a mock here).
        time_zone: IANA course time zone; defaults to ``[canvas] time_zone``
            in cass.toml and is fetched from the course when that is empty.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        course_id: int | None = None,
        *,
        auth: CanvasAuth | None = None,
        transport: httpx.BaseTransport | None = None,
        time_zone: str | None = None,
    ) -> None:
        cfg = get_config() if base_url is None or course_id is None else None
        resolved_base = base_url or (cfg.canvas_base_url if cfg else "")
        self._base_url = resolved_base.rstrip("/") + "/api/v1"
        if token is not None:
            auth = TokenAuth(token=token, source="argument")
        self.auth: CanvasAuth = auth or get_auth()
        if (
            isinstance(self.auth, SessionAuth)
            and self.auth.browser_source is not None
            and self.auth.browser_source.origin != resolved_base.rstrip("/")
        ):
            raise CanvasAuthError(
                "The saved browser session belongs to another Canvas origin. "
                + self.auth.refresh_message()
            )
        self.course_id = course_id or (cfg.canvas_course_id if cfg else 0)
        self._time_zone = time_zone or (cfg.canvas_time_zone if cfg else "")
        self._transport = transport
        self._http: httpx.Client | None = None

    @property
    def _client(self) -> httpx.Client:
        if self._http is None or self._http.is_closed:
            refresh = (
                self._refresh_browser
                if isinstance(self.auth, SessionAuth) and self.auth.browser_source
                else None
            )
            transport = self._transport
            if not isinstance(transport, RetryTransport):
                transport = RetryTransport(
                    auth=self.auth,
                    retries=1,
                    wrapped=transport,
                    refresh=refresh,
                )
            self._http = httpx.Client(
                base_url=self._base_url,
                headers={
                    "User-Agent": f"cass-cli/{__version__}",
                    **self.auth.headers(),
                },
                cookies=self.auth.cookies(),
                transport=transport,
                timeout=30.0,
            )
        return self._http

    def _refresh_browser(self) -> SessionAuth:
        from ..browser import login_from_browser

        if not isinstance(self.auth, SessionAuth) or self.auth.browser_source is None:
            raise CanvasAuthError("This session was not imported from a browser.")
        source = self.auth.browser_source
        auth = login_from_browser(
            source.path.parent, source.origin, source.profile, browser=source.browser
        )
        self.auth = auth
        if self._http is not None:
            self._http.headers.update(auth.headers())
            self._http.cookies.clear()
            self._http.cookies.update(auth.cookies())
        return auth

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http and not self._http.is_closed:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get_paginated(self, path: str) -> list[dict[str, object]]:
        """GET with Canvas-style Link header pagination."""
        results: list[dict[str, object]] = []
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}per_page=100"

        while url:
            resp = self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)

            url = ""
            link = resp.headers.get("link", "")
            if m := _LINK_NEXT_RE.search(link):
                url = m.group(1)
                base = str(self._client.base_url)
                url = url.removeprefix(base)

        return results

    def _course(self, path: str = "") -> str:
        """Build a course-scoped API path."""
        return f"/courses/{self.course_id}{path}"

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send any request with cass's auth and retry handling.

        Use ``self._course(path)`` for course-relative paths. Raises
        ``httpx.HTTPStatusError`` on a 4xx/5xx response.
        """
        resp = self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp

    @property
    def time_zone(self) -> str:
        """IANA time zone of the course (from cass.toml, else fetched once)."""
        if not self._time_zone:
            resp = self._client.get(self._course())
            resp.raise_for_status()
            self._time_zone = resp.json().get("time_zone") or "UTC"
            _console.print(
                "[dim]Course time zone is not in cass.toml; "
                "run 'cass init' to save it.[/dim]"
            )
        return self._time_zone

    def publish(self, resource: str, resource_id: int) -> None:
        """Publish a resource (module, assignment, or quiz).

        Args:
            resource: Resource type (``modules``, ``assignments``, ``quizzes``).
            resource_id: Canvas resource ID.
        """
        key = resource_key(resource)
        resp = self._client.put(
            self._course(f"/{resource}/{resource_id}"),
            data={f"{key}[published]": True},
        )
        resp.raise_for_status()

    def unpublish(self, resource: str, resource_id: int) -> None:
        """Unpublish a resource (module, assignment, or quiz).

        Args:
            resource: Resource type (``modules``, ``assignments``, ``quizzes``).
            resource_id: Canvas resource ID.
        """
        key = resource_key(resource)
        resp = self._client.put(
            self._course(f"/{resource}/{resource_id}"),
            data={f"{key}[published]": False},
        )
        resp.raise_for_status()

    # --- Resolve by name ---

    def _resolve(
        self,
        items: list[T],
        id_or_name: str,
        label: str,
        name_of: Callable[[T], str],
    ) -> T:
        """Match by numeric ID string or case-insensitive name.

        Raises:
            RuntimeError: ``"<label> not found: <id_or_name> (available: ...)"``.
        """
        wanted = id_or_name.lower()
        for item in items:
            item_id = str(getattr(item, "id", ""))
            if item_id == id_or_name or name_of(item).lower() == wanted:
                return item
        names = ", ".join(name_of(item) for item in items)
        raise RuntimeError(f"{label} not found: {id_or_name} (available: {names})")


def resource_key(resource: str) -> str:
    """Map a plural resource name to Canvas API parameter key."""
    return {
        "modules": "module",
        "assignments": "assignment",
        "quizzes": "quiz",
    }.get(resource, resource.rstrip("s"))
