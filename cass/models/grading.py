"""Grading logic — compute grades from submissions."""

from __future__ import annotations

__docformat__ = "google"

from .domain import CanvasGrade, CanvasSubmission, GHGrade, GHSubmission


def compute_gh_grade(sub: GHSubmission) -> GHGrade:
    """Compute a grade from a GitHub Classroom submission."""
    if not sub.submitted:
        return GHGrade(
            github_username=sub.github_username,
            assignment_slug=sub.assignment_slug,
            grade="0",
            numeric_score=0.0,
        )
    if sub.late:
        lateness = _format_lateness(sub.lateness_seconds)
        return GHGrade(
            github_username=sub.github_username,
            assignment_slug=sub.assignment_slug,
            grade=f"0 ({lateness})",
            numeric_score=0.0,
        )
    if sub.commits_after_deadline == 0:
        return GHGrade(
            github_username=sub.github_username,
            assignment_slug=sub.assignment_slug,
            grade="1",
            numeric_score=1.0,
        )
    return GHGrade(
        github_username=sub.github_username,
        assignment_slug=sub.assignment_slug,
        grade=f"1+ ({sub.commits_after_deadline})",
        numeric_score=1.0,
    )


def compute_canvas_grade(
    sub: CanvasSubmission, points_possible: float = 0.0
) -> CanvasGrade:
    """Compute a grade from a Canvas submission."""
    if not sub.submitted:
        return CanvasGrade(
            canvas_user_id=sub.canvas_user_id,
            canvas_assignment_id=sub.canvas_assignment_id,
            score=None,
            posted_grade="-",
        )
    if sub.score is None:
        return CanvasGrade(
            canvas_user_id=sub.canvas_user_id,
            canvas_assignment_id=sub.canvas_assignment_id,
            score=None,
            posted_grade="?",
        )
    if points_possible > 0:
        grade_str = f"{sub.score:g}/{points_possible:g}"
    else:
        grade_str = f"{sub.score:g}"
    return CanvasGrade(
        canvas_user_id=sub.canvas_user_id,
        canvas_assignment_id=sub.canvas_assignment_id,
        score=sub.score,
        posted_grade=grade_str,
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
