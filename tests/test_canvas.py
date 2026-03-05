"""Tests for cass.canvas — name matching, slugification, roster mapping."""

import pytest

from cass.canvas import (
    CanvasStudent,
    _normalize,
    _slugify,
    find_candidates,
    mapping_from_roster,
    match_students,
)
from cass.models import GHStudentInfo, Student


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


# --- _slugify ---


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
def test_slugify(name, expected):
    assert _slugify(name) == expected


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


# --- mapping_from_roster ---


def test_mapping_from_roster():
    students = [
        Student(identifier="alice", github_username="alice-gh", canvas_id="100"),
        Student(identifier="bob", github_username="bob-gh", canvas_id="200"),
        Student(
            identifier="charlie", github_username="", canvas_id="300"
        ),  # no gh -> skip
        Student(
            identifier="diana", github_username="diana-gh", canvas_id=""
        ),  # no canvas -> skip
        Student(
            identifier="eve", github_username="eve-gh", canvas_id="not-a-number"
        ),  # bad -> skip
    ]
    result = mapping_from_roster(students)
    assert result == {"alice-gh": 100, "bob-gh": 200}
