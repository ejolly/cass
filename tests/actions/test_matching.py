"""Tests for cass.canvas.matching — name matching, slugification."""

__docformat__ = "google"

import httpx
import pytest

from cass.actions.matching import (
    find_candidates,
    match_students,
    normalize,
    slugify,
)
from cass.apis.canvas.client import RetryTransport
from cass.apis.canvas.schema import CanvasStudentResponse
from cass.apis.github.schema import GHStudentInfo


class TestNormalize:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Alice Smith", "alice smith"),
            ("Smith, Alice", "alice smith"),
            ("  Alice   Smith  ", "alice smith"),
            ("O'Brien", "obrien"),
            ("De La Cruz, Ana Maria", "ana cruz de la maria"),
            ("", ""),
        ],
        ids=[
            "plain",
            "comma-reversed",
            "extra-spaces",
            "apostrophe",
            "multi-part-comma",
            "empty",
        ],
    )
    def test_normalize(self, name, expected):
        assert normalize(name) == expected


class TestSlugify:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Homework 01", "homework-01"),
            ("hw-01", "hw-01"),
            ("  Extra   Spaces  ", "extra-spaces"),
            ("under_score", "under-score"),
            ("path/to/thing", "path-to-thing"),
            ("Quiz (Final)", "quiz-final"),
        ],
        ids=[
            "spaces",
            "hyphens-passthrough",
            "extra-spaces",
            "underscores",
            "slashes",
            "parens",
        ],
    )
    def test_slugify(self, name, expected):
        assert slugify(name) == expected


class TestMatchStudents:
    def test_match(self):
        gh = [
            GHStudentInfo(login="alice-gh", name="Alice Smith"),
            GHStudentInfo(login="bob-gh", name="Bob Jones"),
            GHStudentInfo(login="charlie-gh", name=""),  # no name -> unmatched
        ]
        canvas = [
            CanvasStudentResponse(id=100, name="Alice Smith"),
            CanvasStudentResponse(id=200, name="Bob Jones"),
            CanvasStudentResponse(id=300, name="Diana Prince"),
        ]
        result = match_students(gh, canvas)
        assert result.matched == {"alice-gh": 100, "bob-gh": 200}
        assert [s.login for s in result.unmatched_gh] == ["charlie-gh"]
        assert [s.id for s in result.unmatched_canvas] == [300]

    def test_sortable(self):
        gh = [GHStudentInfo(login="alice-gh", name="Alice Smith")]
        canvas = [
            CanvasStudentResponse(
                id=100, name="Alice M Smith", sortable_name="Smith, Alice M"
            ),
        ]
        result = match_students(gh, canvas)
        assert result.matched == {"alice-gh": 100}
        assert result.unmatched_gh == []
        assert result.unmatched_canvas == []

    def test_find_candidates(self):
        gh = GHStudentInfo(login="alice-gh", name="Alice")
        pool = [
            CanvasStudentResponse(id=1, name="Alice Smith"),
            CanvasStudentResponse(id=2, name="Bob Jones"),
            CanvasStudentResponse(id=3, name="Alice Wonder"),
            CanvasStudentResponse(id=4, name="Charlie Brown"),
        ]
        result = find_candidates(gh, pool)
        assert len(result) == 2
        ids = {c.id for c in result}
        assert ids == {1, 3}

    def test_find_candidates_empty(self):
        gh = GHStudentInfo(login="", name="")
        pool = [CanvasStudentResponse(id=i, name=f"Student {i}") for i in range(10)]
        result = find_candidates(gh, pool)
        assert len(result) == 5


def _mock_transport(responses: list[httpx.Response]) -> httpx.BaseTransport:
    """Transport that yields pre-built responses in order."""
    it = iter(responses)

    class _Mock(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return next(it)

    return _Mock()


class TestRetryTransport:
    def test_success(self):
        """Normal 200 passes through immediately."""
        inner = _mock_transport([httpx.Response(200, json={"ok": True})])
        transport = RetryTransport.__new__(RetryTransport)
        transport._wrapped = inner
        resp = transport.handle_request(httpx.Request("GET", "https://example.com"))
        assert resp.status_code == 200

    def test_429_then_success(self, monkeypatch):
        """429 is retried, and succeeds on the next attempt."""
        monkeypatch.setattr("cass.apis.canvas.client.time.sleep", lambda _: None)
        inner = _mock_transport(
            [
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        transport = RetryTransport.__new__(RetryTransport)
        transport._wrapped = inner
        resp = transport.handle_request(httpx.Request("GET", "https://example.com"))
        assert resp.status_code == 200

    def test_429_exhausted(self, monkeypatch):
        """After MAX_RETRIES 429s, the last 429 response is returned."""
        monkeypatch.setattr("cass.apis.canvas.client.time.sleep", lambda _: None)
        inner = _mock_transport([httpx.Response(429)] * 4)
        transport = RetryTransport.__new__(RetryTransport)
        transport._wrapped = inner
        resp = transport.handle_request(httpx.Request("GET", "https://example.com"))
        assert resp.status_code == 429

    def test_throttle(self, monkeypatch):
        """Low X-Rate-Limit-Remaining triggers a delay."""
        delays: list[float] = []
        monkeypatch.setattr("cass.apis.canvas.client.time.sleep", delays.append)
        inner = _mock_transport(
            [
                httpx.Response(200, headers={"X-Rate-Limit-Remaining": "10"}),
            ]
        )
        transport = RetryTransport.__new__(RetryTransport)
        transport._wrapped = inner
        transport.handle_request(httpx.Request("GET", "https://example.com"))
        assert len(delays) == 1
        assert delays[0] == 1.0
