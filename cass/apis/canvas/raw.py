"""Helpers for raw Canvas API calls: path normalization and form encoding."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Iterable
from urllib.parse import urlencode

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
