"""Tests for cass.canvas.matching — name matching, slugification."""

import httpx
import pytest

from cass.canvas.matching import (
    _normalize,
    slugify,
    find_candidates,
    match_students,
)
from cass.canvas.client import _RetryTransport
from cass.models import CanvasStudent, GHStudentInfo


# --- _normalize ---


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
def test_normalize(name, expected):
    assert _normalize(name) == expected


# --- slugify ---


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
def testslugify(name, expected):
    assert slugify(name) == expected


# --- match_students ---


def test_match_students():
    gh = [
        GHStudentInfo(login="alice-gh", name="Alice Smith"),
        GHStudentInfo(login="bob-gh", name="Bob Jones"),
        GHStudentInfo(login="charlie-gh", name=""),  # no name -> unmatched
    ]
    canvas = [
        CanvasStudent(id=100, name="Alice Smith"),
        CanvasStudent(id=200, name="Bob Jones"),
        CanvasStudent(id=300, name="Diana Prince"),
    ]
    result = match_students(gh, canvas)
    assert result.matched == {"alice-gh": 100, "bob-gh": 200}
    assert [s.login for s in result.unmatched_gh] == ["charlie-gh"]
    assert [s.id for s in result.unmatched_canvas] == [300]


def test_match_students_sortable():
    gh = [GHStudentInfo(login="alice-gh", name="Alice Smith")]
    canvas = [
        CanvasStudent(id=100, name="Alice M Smith", sortable_name="Smith, Alice M"),
    ]
    result = match_students(gh, canvas)
    assert result.matched == {"alice-gh": 100}
    assert result.unmatched_gh == []
    assert result.unmatched_canvas == []


# --- find_candidates ---


def test_find_candidates():
    gh = GHStudentInfo(login="alice-gh", name="Alice")
    pool = [
        CanvasStudent(id=1, name="Alice Smith"),
        CanvasStudent(id=2, name="Bob Jones"),
        CanvasStudent(id=3, name="Alice Wonder"),
        CanvasStudent(id=4, name="Charlie Brown"),
    ]
    result = find_candidates(gh, pool)
    assert len(result) == 2
    ids = {c.id for c in result}
    assert ids == {1, 3}


def test_find_candidates_empty():
    gh = GHStudentInfo(login="", name="")
    pool = [CanvasStudent(id=i, name=f"Student {i}") for i in range(10)]
    result = find_candidates(gh, pool)
    assert len(result) == 5


# --- _RetryTransport ---


def _mock_transport(responses: list[httpx.Response]) -> httpx.BaseTransport:
    """Transport that yields pre-built responses in order."""
    it = iter(responses)

    class _Mock(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return next(it)

    return _Mock()


def test_retry_transport_success():
    """Normal 200 passes through immediately."""
    inner = _mock_transport([httpx.Response(200, json={"ok": True})])
    transport = _RetryTransport.__new__(_RetryTransport)
    transport._wrapped = inner
    resp = transport.handle_request(httpx.Request("GET", "https://example.com"))
    assert resp.status_code == 200


def test_retry_transport_429_then_success(monkeypatch):
    """429 is retried, and succeeds on the next attempt."""
    monkeypatch.setattr("cass.canvas.client.time.sleep", lambda _: None)
    inner = _mock_transport(
        [
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    transport = _RetryTransport.__new__(_RetryTransport)
    transport._wrapped = inner
    resp = transport.handle_request(httpx.Request("GET", "https://example.com"))
    assert resp.status_code == 200


def test_retry_transport_429_exhausted(monkeypatch):
    """After MAX_RETRIES 429s, the last 429 response is returned."""
    monkeypatch.setattr("cass.canvas.client.time.sleep", lambda _: None)
    inner = _mock_transport([httpx.Response(429)] * 4)
    transport = _RetryTransport.__new__(_RetryTransport)
    transport._wrapped = inner
    resp = transport.handle_request(httpx.Request("GET", "https://example.com"))
    assert resp.status_code == 429


def test_retry_transport_throttle(monkeypatch):
    """Low X-Rate-Limit-Remaining triggers a delay."""
    delays: list[float] = []
    monkeypatch.setattr("cass.canvas.client.time.sleep", delays.append)
    inner = _mock_transport(
        [
            httpx.Response(200, headers={"X-Rate-Limit-Remaining": "10"}),
        ]
    )
    transport = _RetryTransport.__new__(_RetryTransport)
    transport._wrapped = inner
    transport.handle_request(httpx.Request("GET", "https://example.com"))
    assert len(delays) == 1
    assert delays[0] == 1.0
