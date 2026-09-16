"""Course, people, sections, enrollments, and grading standards."""

from __future__ import annotations

__docformat__ = "google"

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
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasCourse, strict=False)

    def list_users(self, enrollment_type: str | None = None) -> list[CanvasUser]:
        """List course users with enrollments.

        Args:
            enrollment_type: Filter by role (e.g. ``student``, ``teacher``).

        Returns:
            Users sorted by name.
        """
        path = self._course("/users?include[]=enrollments&include[]=email")
        if enrollment_type:
            path += f"&enrollment_type[]={enrollment_type}"
        data = self._get_paginated(path)
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
        self, *, enrollment_type: str = "StudentEnrollment"
    ) -> list[CanvasEnrollment]:
        """List enrollments with computed scores.

        Args:
            enrollment_type: Filter by type (default: StudentEnrollment).

        Returns:
            Enrollments including computed_final_score.
        """
        data = self._get_paginated(
            self._course(
                f"/enrollments?type[]={enrollment_type}"
                "&state[]=active&include[]=total_scores"
            )
        )
        return msgspec.convert(data, list[CanvasEnrollment], strict=False)

    def list_grading_standards(self) -> list[CanvasGradingStandard]:
        """List grading standards available for this course.

        Returns:
            Grading standards with scheme entries.
        """
        data = self._get_paginated(self._course("/grading_standards"))
        return msgspec.convert(data, list[CanvasGradingStandard], strict=False)
