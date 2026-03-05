"""Tests for cass.models — grading logic, display helpers."""

import pytest

from cass.models import (
    Assignment,
    Student,
    Submission,
    _format_lateness,
    compute_grade,
    numeric_grade,
)


# --- compute_grade: GitHub ---


@pytest.mark.parametrize(
    "submitted, late, lateness_seconds, commits_after, expected_grade, expected_numeric",
    [
        # not submitted
        (False, False, 0, 0, "0", 0.0),
        # late, no lateness info
        (True, True, 0, 0, "0 ()", 0.0),
        # late, 90061s = 1d 01:01
        (True, True, 90061, 0, "0 (+1d 01:01)", 0.0),
        # on time, 0 commits after
        (True, False, 0, 0, "1", 1.0),
        # on time, 3 commits after
        (True, False, 0, 3, "1+ (3)", 1.0),
    ],
    ids=[
        "not-submitted",
        "late-no-info",
        "late-90061s",
        "on-time-clean",
        "on-time-3-commits",
    ],
)
def test_compute_grade_github(
    submitted, late, lateness_seconds, commits_after, expected_grade, expected_numeric
):
    sub = Submission(
        student_id="alice",
        assignment_id="hw-01",
        source="github",
        submitted=submitted,
        late=late,
        lateness_seconds=lateness_seconds,
        commits_after=commits_after,
    )
    assign = Assignment(id="hw-01", source="github", title="HW 01", points_possible=1.0)
    g = compute_grade(sub, assign)
    assert g.grade == expected_grade
    assert g.numeric == expected_numeric


# --- compute_grade: Canvas ---


@pytest.mark.parametrize(
    "submitted, score, points_possible, expected_grade, expected_numeric",
    [
        # not submitted
        (False, None, 50.0, "-", None),
        # submitted, no score
        (True, None, 50.0, "?", None),
        # graded 42/50
        (True, 42.0, 50.0, "42/50", 42.0),
        # perfect 50/50
        (True, 50.0, 50.0, "50/50", 50.0),
    ],
    ids=["not-submitted", "no-score", "graded-42-50", "perfect-50-50"],
)
def test_compute_grade_canvas(
    submitted, score, points_possible, expected_grade, expected_numeric
):
    sub = Submission(
        student_id="alice",
        assignment_id="quiz-1",
        source="canvas",
        submitted=submitted,
        score=score,
        workflow_state="graded" if score is not None else "",
    )
    assign = Assignment(
        id="quiz-1",
        source="canvas",
        title="Quiz 1",
        points_possible=points_possible,
    )
    g = compute_grade(sub, assign)
    assert g.grade == expected_grade
    assert g.numeric == expected_numeric


def test_compute_grade_canvas_no_points():
    sub = Submission(
        student_id="alice",
        assignment_id="survey",
        source="canvas",
        submitted=True,
        score=10.0,
    )
    assign = Assignment(
        id="survey", source="canvas", title="Survey", points_possible=0.0
    )
    g = compute_grade(sub, assign)
    assert g.grade == "10"
    assert g.numeric == 10.0


# --- _format_lateness ---


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, ""),
        (-5, ""),
        (3600, "+1:00"),
        (3661, "+1:01"),
        (86400, "+1d 00:00"),
        (90061, "+1d 01:01"),
        (180000, "+2d 02:00"),
    ],
    ids=["zero", "negative", "1h", "1h1m1s", "1d", "1d1h1m", "2d2h"],
)
def test_format_lateness(seconds, expected):
    assert _format_lateness(seconds) == expected


# --- numeric_grade ---


@pytest.mark.parametrize(
    "grade_str, expected",
    [
        ("-", None),
        ("?", None),
        ("0", 0.0),
        ("0 (+1d 01:01)", 0.0),
        ("1", 1.0),
        ("1+ (3)", 1.0),
        ("8/10", 8.0),
        ("42/50", 42.0),
    ],
    ids=[
        "dash",
        "question",
        "zero",
        "zero-late",
        "one",
        "one-plus",
        "8-of-10",
        "42-of-50",
    ],
)
def test_numeric_grade(grade_str, expected):
    assert numeric_grade(grade_str) == expected


# --- Student display ---


@pytest.mark.parametrize(
    "identifier, name, github_username, canvas_id, expected",
    [
        ("alice", "", "", "", "alice"),
        ("", "Alice Smith", "", "", "Alice Smith"),
        ("", "", "alice-gh", "", "alice-gh"),
        ("", "", "", "12345", "12345"),
        ("", "", "", "", ""),
    ],
    ids=["identifier", "name-fallback", "github-fallback", "canvas-fallback", "empty"],
)
def test_student_display_name(identifier, name, github_username, canvas_id, expected):
    s = Student(
        identifier=identifier,
        name=name,
        github_username=github_username,
        canvas_id=canvas_id,
    )
    assert s.display_name == expected


def test_student_handle_lower():
    s = Student(identifier="alice", github_username="AliceSmith")
    assert s.handle_lower == "alicesmith"
