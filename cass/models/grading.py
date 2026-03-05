"""Grading logic — compute grades from submissions."""

from __future__ import annotations

__docformat__ = "google"

from .domain import Assignment, Grade, Submission


def compute_grade(sub: Submission, assign: Assignment) -> Grade:
    """Compute a grade from a submission."""
    if sub.source == "github":
        return _compute_github_grade(sub, assign)
    return _compute_canvas_grade(sub, assign)


def _compute_github_grade(sub: Submission, assign: Assignment) -> Grade:
    if not sub.submitted:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="0",
            numeric_score=0.0,
        )
    if sub.late:
        lateness = _format_lateness(sub.lateness_seconds)
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade=f"0 ({lateness})",
            numeric_score=0.0,
        )
    if sub.commits_after_deadline == 0:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="1",
            numeric_score=1.0,
        )
    return Grade(
        student_id=sub.student_id,
        assignment_id=sub.assignment_id,
        grade=f"1+ ({sub.commits_after_deadline})",
        numeric_score=1.0,
    )


def _compute_canvas_grade(sub: Submission, assign: Assignment) -> Grade:
    if not sub.submitted:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="-",
            numeric_score=None,
        )
    if sub.score is None:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="?",
            numeric_score=None,
        )
    if assign.points_possible > 0:
        grade_str = f"{sub.score:g}/{assign.points_possible:g}"
    else:
        grade_str = f"{sub.score:g}"
    return Grade(
        student_id=sub.student_id,
        assignment_id=sub.assignment_id,
        grade=grade_str,
        numeric_score=sub.score,
    )


def _format_lateness(seconds: int) -> str:
    """Format lateness seconds as '+Nd HH:MM'."""
    if seconds <= 0:
        return ""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"+{d}d {h:02d}:{m:02d}"
    return f"+{h}:{m:02d}"


def numeric_grade(grade_str: str) -> float | None:
    """Convert grade display string to numeric value for Canvas push.

    "0" / "0 (+...)" -> 0, "1" / "1+ (N)" -> 1, "-" / "?" -> None.
    """
    if grade_str in ("-", "?"):
        return None
    if grade_str.startswith("0"):
        return 0.0
    if grade_str.startswith("1"):
        return 1.0
    if "/" in grade_str:
        try:
            return float(grade_str.split("/")[0])
        except ValueError:
            return None
    try:
        return float(grade_str)
    except ValueError:
        return None
