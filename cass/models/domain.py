"""Domain models for cass — user-facing types for students, assignments, submissions, grades."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import msgspec
import msgspec.structs

DataSource = Literal["github", "canvas"]
GradeSource = Literal["auto", "manual"]


class Student(msgspec.Struct):
    """A student in the course roster."""

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


class Assignment(msgspec.Struct):
    """An assignment from GitHub Classroom or Canvas LMS."""

    id: str
    source: DataSource
    title: str
    slug: str = ""
    canvas_id: int = 0
    deadline: datetime | None = None
    points_possible: float = 0.0
    accepted: int = 0


class Submission(msgspec.Struct):
    """A student's submission for an assignment."""

    student_id: str
    assignment_id: str
    source: DataSource
    submitted: bool = False
    submitted_at: datetime | None = None
    late: bool = False
    lateness_seconds: int = 0
    repo_name: str = ""
    commits_after_deadline: int = 0
    score: float | None = None
    workflow_state: str = ""

    def with_assignment_id(self, assignment_id: str) -> Submission:
        """Return a copy with a different assignment_id."""
        return msgspec.structs.replace(self, assignment_id=assignment_id)


class Grade(msgspec.Struct):
    """A computed or manual grade for a student-assignment pair."""

    student_id: str
    assignment_id: str
    grade: str  # display: "0", "1", "1+ (2)", "2/2", etc.
    numeric_score: float | None = None
    source: GradeSource = "auto"
