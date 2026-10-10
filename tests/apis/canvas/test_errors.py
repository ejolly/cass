"""Tests for cass.apis.canvas.errors — CanvasAPIError."""

import httpx

from cass.apis.canvas.errors import CanvasAPIError, raise_for_canvas_status


def test_str_and_fields():
    request = httpx.Request(
        "PUT", "https://canvas.example.com/api/v1/courses/1/quizzes/9"
    )
    resp = httpx.Response(
        403, json={"errors": [{"message": "unauthorized"}]}, request=request
    )
    err = CanvasAPIError(resp)
    assert str(err) == "PUT /courses/1/quizzes/9 → 403: unauthorized"
    assert err.method == "PUT"
    assert err.path == "/courses/1/quizzes/9"
    assert err.status_code == 403
    assert err.canvas_message == "unauthorized"
    assert isinstance(err, httpx.HTTPStatusError)
    assert err.response is resp


def test_raise_for_canvas_status_ignores_success():
    request = httpx.Request("GET", "https://canvas.example.com/api/v1/x")
    assert raise_for_canvas_status(httpx.Response(200, request=request)) is None
