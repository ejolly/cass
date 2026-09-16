"""Domain models for cass.

User-facing types for students, assignments, submissions, grades.
Each model corresponds to either a DB table or a virtual view.
"""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime
from typing import TYPE_CHECKING

import msgspec
import msgspec.structs

if TYPE_CHECKING:
    from ..apis.canvas.schema import CanvasAssignmentResponse, CanvasStudentResponse
    from ..apis.github.schema import GHAssignmentResponse, GHStudentInfo

# ===================================================================
# User-facing tables (Canvas)
# ===================================================================


class CanvasStudent(msgspec.Struct):
    """A Canvas LMS student record."""

    canvas_id: int
    name: str = ""
    sortable_name: str = ""
    email: str = ""
    login_id: str = ""
    sis_user_id: str = ""
    sis_section_id: str = ""

    @classmethod
    def from_api(
        cls,
        s: CanvasStudentResponse,
        *,
        sis_section_id: str = "",
    ) -> CanvasStudent:
        """Convert a Canvas API student response to a domain model."""
        return cls(
            canvas_id=s.id,
            name=s.name,
            sortable_name=s.sortable_name,
            email=s.email,
            login_id=s.login_id,
            sis_user_id=s.sis_user_id or "",
            sis_section_id=sis_section_id,
        )


class CanvasAssignment(msgspec.Struct):
    """A Canvas LMS assignment."""

    canvas_id: int
    name: str = ""
    points_possible: float = 0.0
    due_at: str | None = None
    published: bool = False
    assignment_group: str = ""
    post_manually: bool = False

    @classmethod
    def from_api(
        cls,
        a: CanvasAssignmentResponse,
        *,
        group_name: str = "",
    ) -> CanvasAssignment:
        """Convert a Canvas API assignment response to a domain model."""
        return cls(
            canvas_id=a.id,
            name=a.name,
            points_possible=a.points_possible or 0.0,
            due_at=a.due_at or None,
            published=a.published,
            assignment_group=group_name,
            post_manually=a.post_manually,
        )


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


class CanvasGrade(msgspec.Struct):
    """A grade ready for Canvas API push."""

    canvas_user_id: int
    canvas_assignment_id: int
    score: float | None = None
    posted_grade: str = ""


# ===================================================================
# User-facing tables (GitHub)
# ===================================================================


class GHStudent(msgspec.Struct):
    """A GitHub Classroom roster student."""

    github_username: str
    github_id: int = 0
    name: str = ""
    email: str = ""
    excluded: bool = False

    @classmethod
    def from_api(cls, s: GHStudentInfo) -> GHStudent:
        """Convert a GHStudentInfo API aggregate to a domain model."""
        return cls(
            github_username=s.login.lower(),
            github_id=int(s.id) if s.id else 0,
            name=s.name,
            email=s.email,
        )


class GHAssignment(msgspec.Struct):
    """A GitHub Classroom assignment."""

    slug: str
    gh_id: int = 0
    title: str = ""
    deadline: str | None = None
    points_possible: float = 1.0
    accepted: int = 0
    submissions_count: int = 0
    passing_count: int = 0
    starter_code_repo: str = ""
    submittable_files: str = ""

    @classmethod
    def from_api(cls, a: GHAssignmentResponse) -> GHAssignment:
        """Convert a GHAssignmentResponse API type to a domain model."""
        starter = (
            a.starter_code_repository.full_name
            if a.starter_code_repository and a.starter_code_repository.full_name
            else ""
        )
        return cls(
            slug=a.slug,
            gh_id=a.id,
            title=a.title,
            deadline=a.deadline or None,
            points_possible=1.0,
            accepted=a.accepted,
            submissions_count=a.submissions,
            passing_count=a.passing,
            starter_code_repo=starter,
        )


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
    last_commit_at: str = ""
    last_commit_sha: str = ""

    def with_assignment_slug(self, slug: str) -> GHSubmission:
        """Return a copy with a different assignment_slug."""
        return msgspec.structs.replace(self, assignment_slug=slug)


# ===================================================================
# View models (no backing table)
# ===================================================================


class GHRecentCommit(msgspec.Struct):
    """A row in the enriched GH recent commits view (live query, no table)."""

    github_username: str = ""
    assignment_slug: str = ""
    student: str = ""
    assignment_name: str = ""
    last_commit_at: str = ""
    commit_count: int = 0
    commit_url: str = ""
    repo_url: str = ""
    late: bool = False
    last_commit_sha: str = ""


# ===================================================================
# Internal/master tables
# ===================================================================


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
