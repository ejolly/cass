"""Tests for cass.models — grading logic, display helpers."""

import pytest

from cass.models import (
    CanvasSubmission,
    GHSubmission,
    Student,
    compute_canvas_grade,
    compute_gh_grade,
    numeric_grade,
)
from cass.models.grading import format_lateness

# --- compute_gh_grade ---


@pytest.mark.parametrize(
    "submitted, late, lateness_seconds, commits_after_deadline, "
    "expected_grade, expected_numeric",
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
def test_compute_gh_grade(
    submitted,
    late,
    lateness_seconds,
    commits_after_deadline,
    expected_grade,
    expected_numeric,
):
    sub = GHSubmission(
        github_username="alice",
        assignment_slug="hw-01",
        submitted=submitted,
        late=late,
        lateness_seconds=lateness_seconds,
        commits_after_deadline=commits_after_deadline,
    )
    g = compute_gh_grade(sub)
    assert g.grade == expected_grade
    assert g.numeric_score == expected_numeric


# --- compute_canvas_grade ---


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
def test_compute_canvas_grade(
    submitted, score, points_possible, expected_grade, expected_numeric
):
    sub = CanvasSubmission(
        canvas_user_id=100,
        canvas_assignment_id=42,
        submitted=submitted,
        score=score,
        workflow_state="graded" if score is not None else "",
    )
    g = compute_canvas_grade(sub, points_possible)
    assert g.posted_grade == expected_grade
    assert g.score == expected_numeric


def test_compute_canvas_grade_no_points():
    sub = CanvasSubmission(
        canvas_user_id=100,
        canvas_assignment_id=42,
        submitted=True,
        score=10.0,
    )
    g = compute_canvas_grade(sub, 0.0)
    assert g.posted_grade == "10"
    assert g.score == 10.0


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
    assert format_lateness(seconds) == expected


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
    "canvas_id, name, github_username, expected",
    [
        (100, "Alice Smith", "", "Alice Smith"),
        (100, "", "alice-gh", "alice-gh"),
        (100, "", "", "100"),
    ],
    ids=["name", "github-fallback", "canvas-id-fallback"],
)
def test_student_display_name(canvas_id, name, github_username, expected):
    s = Student(
        canvas_id=canvas_id,
        name=name,
        github_username=github_username,
    )
    assert s.display_name == expected


def test_student_handle_lower():
    s = Student(canvas_id=100, github_username="AliceSmith")
    assert s.handle_lower == "alicesmith"


def test_gh_submission_with_assignment_slug():
    sub = GHSubmission(
        github_username="alice",
        assignment_slug="final-project",
        submitted=True,
    )
    new = sub.with_assignment_slug("proposal")
    assert new.assignment_slug == "proposal"
    assert new.github_username == "alice"
    assert new.submitted is True
