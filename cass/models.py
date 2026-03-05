"""Data models for cass — msgspec structs matching the Go version's types."""

from __future__ import annotations

from datetime import datetime

import msgspec


class Student(msgspec.Struct):
    identifier: str
    github_username: str = ""
    github_id: str = ""
    name: str = ""
    canvas_id: str = ""
    excluded: bool = False

    @property
    def handle_lower(self) -> str:
        return self.github_username.lower()

    @property
    def display_name(self) -> str:
        return self.identifier or self.name or self.github_username or self.canvas_id


class GHStudentInfo(msgspec.Struct):
    """GitHub student info aggregated from accepted assignments + profiles."""

    login: str
    id: str = ""
    name: str = ""


class Assignment(msgspec.Struct):
    id: str  # canonical key: slug (GH) or slugified name (Canvas)
    source: str  # "github" | "canvas"
    title: str
    slug: str = ""  # GitHub Classroom slug (empty for canvas-only)
    canvas_id: int = 0  # Canvas assignment ID (0 if not linked)
    deadline: datetime | None = None
    points_possible: float = 0.0  # Canvas: actual points; GitHub: 1.0
    accepted: int = 0  # GitHub only: how many students accepted


class Submission(msgspec.Struct):
    student_id: str  # -> Student.identifier or github_username
    assignment_id: str  # -> Assignment.id
    source: str  # "github" | "canvas"
    submitted: bool = False
    submitted_at: datetime | None = None
    late: bool = False
    lateness_seconds: int = 0
    # GitHub-specific
    repo_name: str = ""
    commits_after: int = 0
    # Canvas-specific
    score: float | None = None
    workflow_state: str = ""

    def with_assignment_id(self, assignment_id: str) -> Submission:
        """Return a copy with a different assignment_id."""
        return Submission(
            student_id=self.student_id,
            assignment_id=assignment_id,
            source=self.source,
            submitted=self.submitted,
            submitted_at=self.submitted_at,
            late=self.late,
            lateness_seconds=self.lateness_seconds,
            repo_name=self.repo_name,
            commits_after=self.commits_after,
            score=self.score,
            workflow_state=self.workflow_state,
        )


class Grade(msgspec.Struct):
    student_id: str  # -> Student
    assignment_id: str  # -> Assignment
    grade: str  # display: "0", "1", "1+ (2)", "2/2", etc.
    numeric: float | None = None  # for Canvas push
    source: str = "auto"  # "auto" | "manual"


FINAL_PROJECT_SLUG = "final-project"
PROPOSAL_FILE = "pdfs/proposal.pdf"
REPORT_FILE = "pdfs/final-report.pdf"


def compute_grade(sub: Submission, assign: Assignment) -> Grade:
    """Compute a grade from a submission, matching Go's ComputeGrade logic."""
    if sub.source == "github":
        return _compute_github_grade(sub, assign)
    return _compute_canvas_grade(sub, assign)


def _compute_github_grade(sub: Submission, assign: Assignment) -> Grade:
    if not sub.submitted:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="0",
            numeric=0.0,
        )
    if sub.late:
        lateness = _format_lateness(sub.lateness_seconds)
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade=f"0 ({lateness})",
            numeric=0.0,
        )
    if sub.commits_after == 0:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="1",
            numeric=1.0,
        )
    return Grade(
        student_id=sub.student_id,
        assignment_id=sub.assignment_id,
        grade=f"1+ ({sub.commits_after})",
        numeric=1.0,
    )


def _compute_canvas_grade(sub: Submission, assign: Assignment) -> Grade:
    if not sub.submitted:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="-",
            numeric=None,
        )
    if sub.score is None:
        return Grade(
            student_id=sub.student_id,
            assignment_id=sub.assignment_id,
            grade="?",
            numeric=None,
        )
    if assign.points_possible > 0:
        grade_str = f"{sub.score:g}/{assign.points_possible:g}"
    else:
        grade_str = f"{sub.score:g}"
    return Grade(
        student_id=sub.student_id,
        assignment_id=sub.assignment_id,
        grade=grade_str,
        numeric=sub.score,
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
    # Canvas grades like "8/10" — extract numerator
    if "/" in grade_str:
        try:
            return float(grade_str.split("/")[0])
        except ValueError:
            return None
    try:
        return float(grade_str)
    except ValueError:
        return None
