"""Dry run: record Canvas writes instead of sending them.

A dry-run client sends GETs as usual but records every other request and
answers it with a synthetic 200 response, so chained calls (create a quiz,
then add its questions) still work. New resources get placeholder IDs
-1, -2, … and later requests to their paths are answered locally.
"""

from __future__ import annotations

__docformat__ = "google"

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import raise_for_canvas_status
from .raw import parse_body, request_fields

_ID_RE = re.compile(r"-?\d+")
_PLACEHOLDER_RE = re.compile(r"-\d+")
_TAB_PATH_RE = re.compile(r"^(/courses/\d+/tabs)/([^/]+)$")
_MAX_VALUE_LENGTH = 60

# Endpoints whose request and response bodies Canvas wraps in a one-item list
# under a key (``{"quiz_groups": [{...}]}``): path pattern -> key.
_ENVELOPES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/quizzes/-?\d+/groups(/-?\d+)?$"), "quiz_groups"),
]

# Fields cass's own chained calls read from a create response, per endpoint.
# Request fields override these.
_ENDPOINT_DEFAULTS: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (
        re.compile(r"^/courses/\d+/files$"),
        {"upload_url": "https://dry-run.invalid/upload", "upload_params": {}},
    ),
    (re.compile(r"^/courses/\d+/modules/[^/]+/items$"), {"title": ""}),
    (re.compile(r"/update_grades$"), {"workflow_state": "queued"}),
]


@dataclass(frozen=True)
class PlannedRequest:
    """One write a dry run recorded instead of sending.

    Attributes:
        method: HTTP method.
        path: Path relative to ``/api/v1``, or the full URL for uploads.
        body: Parsed request body (form keys nested, as in ``parse_form``).
    """

    method: str
    path: str
    body: dict[str, Any]


def format_plan(requests: Sequence[PlannedRequest]) -> list[str]:
    """Render planned writes, one line each.

    A line is the method, the path with placeholder IDs shown as
    ``<new N>``, and the request fields as ``key=value`` pairs. Nested
    values are shown as compact JSON and long values are cut to 60
    characters.
    """
    lines = []
    for request in requests:
        line = f"{request.method} {_display_path(request.path)}"
        fields = request_fields(request.body)
        if fields:
            line += "  " + "  ".join(
                f"{key}={_display_value(value)}" for key, value in fields.items()
            )
        lines.append(line)
    return lines


def _display_path(path: str) -> str:
    segments = path.split("/")
    return "/".join(
        f"<new {segment[1:]}>" if _PLACEHOLDER_RE.fullmatch(segment) else segment
        for segment in segments
    )


def _display_value(value: Any) -> str:
    if isinstance(value, dict | list):
        text = json.dumps(value, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) > _MAX_VALUE_LENGTH:
        text = text[: _MAX_VALUE_LENGTH - 3] + "..."
    return text


def _clear_empty(value: Any) -> Any:
    """Turn empty strings into ``None`` (how a form clears a field), recursively."""
    if value == "":
        return None
    if isinstance(value, dict):
        return {key: _clear_empty(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clear_empty(item) for item in value]
    return value


def _defaults_for(path: str) -> dict[str, Any]:
    for pattern, defaults in _ENDPOINT_DEFAULTS:
        if pattern.search(path):
            return dict(defaults)
    return {}


def _envelope_key(path: str) -> str | None:
    for pattern, key in _ENVELOPES:
        if pattern.search(path):
            return key
    return None


def _wrap(result: dict[str, Any], envelope_key: str | None) -> dict[str, Any]:
    """Wrap a response in its endpoint's envelope, if the request used one."""
    return {envelope_key: [result]} if envelope_key else result


class DryRunRecorder:
    """Records planned writes and keeps the synthetic body of each written path."""

    def __init__(self) -> None:
        self.planned: list[PlannedRequest] = []
        self._bodies: dict[str, dict[str, Any]] = {}
        self._last_placeholder = 0

    def stored(self, path: str) -> dict[str, Any] | None:
        """Synthetic body for a path this dry run created or changed, if any."""
        return self._bodies.get(path)

    def has_placeholder(self, path: str) -> bool:
        """Whether *path* contains a placeholder ID segment such as ``-1``."""
        return any(_PLACEHOLDER_RE.fullmatch(segment) for segment in path.split("/"))

    def record(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        fetch_current: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Record a write and build its synthetic response body.

        A POST to a collection creates a resource with the next placeholder
        ID. Any other write merges the request fields into the resource's
        current body: the stored one, else ``{}`` under a placeholder path,
        else ``fetch_current()`` (called once per path). A ``/reorder`` POST
        is recorded and answered with ``{}``. Endpoints in ``_ENVELOPES``
        take and return their fields wrapped in a one-item list.
        """
        self.planned.append(PlannedRequest(method, path, body))
        path = path.rstrip("/")
        envelope_key = _envelope_key(path)
        if (
            envelope_key
            and isinstance(body.get(envelope_key), list)
            and body[envelope_key]
        ):
            fields = _clear_empty(body[envelope_key][0])
        else:
            envelope_key = None
            fields = _clear_empty(request_fields(body))
        last_segment = path.rsplit("/", 1)[-1]
        ends_with_id = _ID_RE.fullmatch(last_segment) is not None

        if method == "POST" and last_segment == "reorder":
            # An action on existing items, not a new resource.
            return {}

        if method == "POST" and not ends_with_id:
            new_id = self._next_placeholder()
            result = {**_defaults_for(path), **fields, "id": new_id}
            self._bodies[f"{path}/{new_id}"] = result
            return _wrap(result, envelope_key)

        current = self._bodies.get(path)
        if current is None and self.has_placeholder(path):
            # Under a resource the dry run created; Canvas has nothing to fetch.
            current = {}
        if current is None:
            current = fetch_current()
        # Keep the ID as Canvas types it: numeric IDs are ints, tab IDs strings.
        resource_id = int(last_segment) if ends_with_id else last_segment
        result = {**current, **fields, "id": resource_id}
        self._bodies[path] = result
        return _wrap(result, envelope_key)

    def record_upload(
        self, url: str, params: dict[str, Any], filename: str
    ) -> dict[str, Any]:
        """Record the file POST to an upload URL and build the file's body."""
        self.planned.append(PlannedRequest("POST", url, {**params, "file": filename}))
        new_id = self._next_placeholder()
        result = {"id": new_id, "display_name": filename, "filename": filename}
        # Stored so a following PUT /files/<new id> merges into this body.
        self._bodies[f"/files/{new_id}"] = result
        return result

    def _next_placeholder(self) -> int:
        self._last_placeholder -= 1
        return self._last_placeholder


class DryRunTransport(httpx.BaseTransport):
    """Sends GETs through *wrapped*; records everything else in *recorder*.

    Args:
        recorder: Where planned writes and synthetic bodies are kept.
        wrapped: Transport for real GETs (cass's ``RetryTransport``).
        api_root: The client's API base URL, e.g.
            ``https://canvas.example.com/api/v1``; recorded paths are
            relative to it.
    """

    def __init__(
        self,
        recorder: DryRunRecorder,
        *,
        wrapped: httpx.BaseTransport,
        api_root: str,
    ) -> None:
        self._recorder = recorder
        self._wrapped = wrapped
        self._api_root = api_root

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = self._api_path(request.url)
        if request.method in ("GET", "HEAD"):
            stored = self._recorder.stored(path)
            if stored is not None:
                return httpx.Response(200, json=stored)
            if self._recorder.has_placeholder(path):
                # A list under a resource that does not exist yet is empty.
                return httpx.Response(200, json=[])
            return self._wrapped.handle_request(request)

        synthetic = self._recorder.record(
            request.method,
            path,
            parse_body(request),
            lambda: self._fetch_current(request, path),
        )
        return httpx.Response(200, json=synthetic)

    def _api_path(self, url: httpx.URL) -> str:
        """Path relative to the API root without the query; else the full URL."""
        full = str(url.copy_with(query=None))
        if full.startswith(self._api_root):
            return full.removeprefix(self._api_root)
        return full

    def _fetch_current(self, request: httpx.Request, path: str) -> dict[str, Any]:
        """GET the resource at *path* for real (raises ``CanvasAPIError``)."""
        tab_match = _TAB_PATH_RE.match(path)
        if tab_match:
            # Canvas has no single-tab GET; find the tab in the course's list.
            tabs_url = request.url.copy_with(
                path=request.url.path.rsplit("/", 1)[0], query=b"per_page=100"
            )
            tabs = self._get(request, tabs_url)
            tab_id = tab_match.group(2)
            for tab in tabs if isinstance(tabs, list) else []:
                if str(tab.get("id")) == tab_id:
                    return tab
            return {}
        current = self._get(request, request.url.copy_with(query=None))
        return current if isinstance(current, dict) else {}

    def _get(self, original: httpx.Request, url: httpx.URL) -> Any:
        headers = {
            key: value
            for key, value in original.headers.items()
            if key.lower() not in ("content-type", "content-length")
        }
        get_request = httpx.Request("GET", url, headers=headers)
        response = self._wrapped.handle_request(get_request)
        response.read()
        response.request = get_request
        raise_for_canvas_status(response)
        return response.json()

    def close(self) -> None:
        self._wrapped.close()
