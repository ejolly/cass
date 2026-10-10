"""Helpers for raw Canvas API calls: path normalization and request bodies."""

from __future__ import annotations

__docformat__ = "google"

import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx

_API_PREFIX = "/api/v1"


def api_path(path: str) -> str:
    """Normalize a user-supplied API path to one relative to ``/api/v1``.

    An ``http(s)://`` URL is returned unchanged. Otherwise ``/api/v1/x``,
    ``/x`` and ``x`` all become ``/x``.
    """
    if path.startswith(("http://", "https://")):
        return path
    path = "/" + path.lstrip("/")
    if path == _API_PREFIX or path.startswith(_API_PREFIX + "/"):
        path = path.removeprefix(_API_PREFIX)
    return path or "/"


def _form_value(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def form_content(pairs: Iterable[tuple[str, object]]) -> bytes:
    """URL-encode key/value pairs as a form body, keeping repeated keys.

    Values are encoded like httpx does: ``True``/``False`` become
    ``true``/``false`` and ``None`` becomes an empty value.
    """
    return urlencode([(key, _form_value(value)) for key, value in pairs]).encode()


def parse_form(pairs: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Parse form pairs into nested data using the Rails bracket convention.

    ``quiz[title]`` nests into ``{"quiz": {"title": ...}}``, ``a[]`` collects
    a list, and ``order[][id]`` builds a list of dicts. Keys without valid
    brackets are kept as plain keys.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        _assign(result, _split_key(key), value)
    return result


def _split_key(key: str) -> list[str]:
    """Split ``a[b][]`` into ``["a", "b", ""]``; a malformed key stays whole."""
    head, bracket, rest = key.partition("[")
    if not bracket or not key.endswith("]") or not head:
        return [key]
    return [head, *rest[:-1].split("][")]


def _assign(node: dict[str, Any], parts: list[str], value: str) -> None:
    key, rest = parts[0], parts[1:]
    if not rest:
        node[key] = value
        return
    if rest[0] == "":  # "[]" means a list
        items = node.get(key)
        if not isinstance(items, list):
            items = node[key] = []
        sub_parts = rest[1:]
        if not sub_parts:
            items.append(value)
            return
        # Start a new dict when the last one already holds this field.
        starts_new_item = (
            not items
            or not isinstance(items[-1], dict)
            or (len(sub_parts) == 1 and sub_parts[0] in items[-1])
        )
        if starts_new_item:
            items.append({})
        _assign(items[-1], sub_parts, value)
        return
    child = node.get(key)
    if not isinstance(child, dict):
        child = node[key] = {}
    _assign(child, rest, value)


def parse_body(request: httpx.Request) -> dict[str, Any]:
    """Read a request's JSON or form body as a dict (``{}`` for anything else).

    A JSON body that is not an object is returned as ``{"body": value}``.
    """
    content = request.content
    if not content:
        return {}
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        data = json.loads(content)
        return data if isinstance(data, dict) else {"body": data}
    if content_type.startswith("application/x-www-form-urlencoded"):
        return parse_form(parse_qsl(content.decode(), keep_blank_values=True))
    return {}


def request_fields(body: dict[str, Any]) -> dict[str, Any]:
    """Remove a resource wrapper: ``{"quiz": {...}}`` becomes ``{...}``."""
    if len(body) == 1:
        (value,) = body.values()
        if isinstance(value, dict):
            return value
    return body
