"""Course, people, sections, enrollments, and grading standards."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Sequence

import msgspec

from ..schema import (
    CanvasCourse,
    CanvasEnrollment,
    CanvasGradingStandard,
    CanvasSection,
    CanvasStudentResponse,
    CanvasUser,
)
from .base import BaseClient


class CourseMixin(BaseClient):
    """Course, people, sections, enrollments, and grading standards."""

    def get_course(self) -> CanvasCourse:
        """Get course details.

        Returns:
            Course metadata.
        """
        resp = self._client.get(self._course("?include[]=total_students"))
        return msgspec.convert(resp.json(), CanvasCourse, strict=False)

    def list_users(
        self, enrollment_type: str | None = None, *, states: Sequence[str] = ()
    ) -> list[CanvasUser]:
        """List course users with enrollments.

        Args:
            enrollment_type: Filter by role (e.g. ``student``, ``teacher``).
            states: Enrollment states to include (e.g. ``active``,
                ``completed``); empty keeps Canvas's default.

        Returns:
            Users sorted by name.
        """
        params: list[tuple[str, object]] = [
            ("include[]", "enrollments"),
            ("include[]", "email"),
        ]
        if enrollment_type:
            params.append(("enrollment_type[]", enrollment_type))
        params.extend(("enrollment_state[]", state) for state in states)
        data = self.get_all(self._course("/users"), params)
        return msgspec.convert(data, list[CanvasUser], strict=False)

    def list_students(self) -> list[CanvasStudentResponse]:
        """List students enrolled in the course.

        Returns:
            Students sorted by Canvas enrollment order.
        """
        data = self._get_paginated(
            self._course("/users?enrollment_type[]=student&include[]=email")
        )
        return msgspec.convert(data, list[CanvasStudentResponse], strict=False)

    def list_sections(self) -> list[CanvasSection]:
        """List all course sections.

        Returns:
            Sections with SIS IDs (if available).
        """
        data = self._get_paginated(self._course("/sections"))
        return msgspec.convert(data, list[CanvasSection], strict=False)

    def list_enrollments(
        self,
        *,
        enrollment_type: str | None = "StudentEnrollment",
        states: Sequence[str] = ("active",),
        include_scores: bool = True,
    ) -> list[CanvasEnrollment]:
        """List enrollments, optionally with computed scores.

        Args:
            enrollment_type: Filter by type (default: StudentEnrollment);
                ``None`` returns every type.
            states: Enrollment states to include (default: active).
            include_scores: Include computed scores (``total_scores``).

        Returns:
            Enrollments, including computed_final_score when requested.
        """
        params: list[tuple[str, object]] = []
        if enrollment_type:
            params.append(("type[]", enrollment_type))
        params.extend(("state[]", state) for state in states)
        if include_scores:
            params.append(("include[]", "total_scores"))
        data = self.get_all(self._course("/enrollments"), params)
        return msgspec.convert(data, list[CanvasEnrollment], strict=False)

    def list_grading_standards(self) -> list[CanvasGradingStandard]:
        """List grading standards available for this course.

        Returns:
            Grading standards with scheme entries.
        """
        data = self._get_paginated(self._course("/grading_standards"))
        return msgspec.convert(data, list[CanvasGradingStandard], strict=False)
