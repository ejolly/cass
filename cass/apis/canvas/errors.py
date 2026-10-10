"""Canvas API errors — one exception type for every 4xx/5xx response."""

from __future__ import annotations

__docformat__ = "google"

import httpx

from .auth import _error_detail

_API_PREFIX = "/api/v1"


class CanvasNotFoundError(RuntimeError):
    """A name or ID matched nothing (as opposed to matching several)."""


class CanvasAPIError(httpx.HTTPStatusError):
    """A Canvas request failed with a 4xx/5xx status.

    Attributes:
        method: HTTP method of the failed request.
        path: Request path without the ``/api/v1`` prefix or query string.
        status_code: HTTP status code.
        canvas_message: Canvas's own error message, or the start of the body.
    """

    def __init__(self, response: httpx.Response) -> None:
        request = response.request
        self.method = request.method
        self.path = request.url.path.removeprefix(_API_PREFIX)
        self.status_code = response.status_code
        self.canvas_message = _error_detail(response)
        super().__init__(
            f"{self.method} {self.path} → {self.status_code}: {self.canvas_message}",
            request=request,
            response=response,
        )


def raise_for_canvas_status(response: httpx.Response) -> None:
    """Raise ``CanvasAPIError`` if *response* is a 4xx/5xx; otherwise do nothing."""
    if response.status_code >= 400:
        response.read()
        raise CanvasAPIError(response)
