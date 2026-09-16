"""Domain models for cass — Canvas students, assignments, submissions, grades."""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime
from typing import TYPE_CHECKING

import msgspec
import msgspec.structs

if TYPE_CHECKING:
    from ..apis.canvas.schema import CanvasAssignmentResponse, CanvasStudentResponse

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
