"""Domain models for cass — user-facing types for students, assignments, submissions, grades."""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime
from typing import Literal

import msgspec
import msgspec.structs

GradeSource = Literal["auto", "manual"]


class Student(msgspec.Struct):
    """A student in the unified course roster (Canvas-authoritative)."""

    canvas_id: int
    github_username: str = ""
    name: str = ""
    email: str = ""
    excluded: bool = False

    @property
    def handle_lower(self) -> str:
        return self.github_username.lower()

    @property
    def display_name(self) -> str:
        return self.name or self.github_username or str(self.canvas_id)


class Assignment(msgspec.Struct):
    """A unified assignment mapping GH Classroom and Canvas."""

    slug: str
    title: str
    gh_assignment_slug: str = ""
    canvas_assignment_id: int = 0
    points_possible: float = 0.0
    deadline: datetime | None = None


class GHSubmission(msgspec.Struct):
    """A GitHub Classroom submission record."""

    github_username: str
    assignment_slug: str
    submitted: bool = False
    late: bool = False
    lateness_seconds: int = 0
    repo_name: str = ""
    commits_after_deadline: int = 0
    commit_count: int = 0
    passing: bool = False
    gh_autograder_score: str = ""

    def with_assignment_slug(self, slug: str) -> GHSubmission:
        """Return a copy with a different assignment_slug."""
        return msgspec.structs.replace(self, assignment_slug=slug)


class CanvasSubmission(msgspec.Struct):
    """A Canvas LMS submission record."""

    canvas_user_id: int
    canvas_assignment_id: int
    submitted: bool = False
    submitted_at: datetime | None = None
    late: bool = False
    lateness_seconds: int = 0
    score: float | None = None
    workflow_state: str = ""


class GHGrade(msgspec.Struct):
    """A computed or manual grade for a GitHub assignment."""

    github_username: str
    assignment_slug: str
    grade: str
    numeric_score: float | None = None
    source: GradeSource = "auto"


class CanvasGrade(msgspec.Struct):
    """A grade ready for Canvas API push."""

    canvas_user_id: int
    canvas_assignment_id: int
    score: float | None = None
    posted_grade: str = ""
