"""Assignments and assignment groups."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from ..schema import CanvasAssignmentGroup, CanvasAssignmentResponse
from .base import BaseClient


class AssignmentsMixin(BaseClient):
    """Assignments and assignment groups."""

    def list_assignments(self) -> list[CanvasAssignmentResponse]:
        """List all course assignments.

        Returns:
            Assignments from all assignment groups.
        """
        data = self._get_paginated(self._course("/assignments"))
        return msgspec.convert(data, list[CanvasAssignmentResponse], strict=False)

    def get_assignment(self, assignment_id: int) -> CanvasAssignmentResponse:
        """Get a single assignment by ID."""
        resp = self._client.get(self._course(f"/assignments/{assignment_id}"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignmentResponse, strict=False)

    def create_assignment(
        self,
        name: str,
        *,
        points_possible: float = 0.0,
        due_at: str | None = None,
        submission_types: list[str] | None = None,
        published: bool = False,
        assignment_group_id: int | None = None,
        description: str | None = None,
        grading_type: str = "points",
    ) -> CanvasAssignmentResponse:
        """Create a new assignment.

        Args:
            name: Assignment name.
            points_possible: Total points.
            due_at: Due date in ISO 8601 format.
            submission_types: Allowed submission types.
            published: Whether to publish immediately.
            assignment_group_id: Assignment group to place in.
            description: HTML description.
            grading_type: Grading type (points, letter_grade, etc.).

        Returns:
            The created assignment.
        """
        params: dict[str, object] = {
            "assignment[name]": name,
            "assignment[points_possible]": points_possible,
            "assignment[published]": published,
            "assignment[grading_type]": grading_type,
        }
        if due_at:
            params["assignment[due_at]"] = due_at
        if submission_types:
            params["assignment[submission_types][]"] = submission_types
        if assignment_group_id:
            params["assignment[assignment_group_id]"] = assignment_group_id
        if description:
            params["assignment[description]"] = description

        resp = self._client.post(self._course("/assignments"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignmentResponse, strict=False)

    def update_assignment(
        self, assignment_id: int, **kwargs: object
    ) -> CanvasAssignmentResponse:
        """Update an assignment.

        Args:
            assignment_id: Canvas assignment ID.
            **kwargs: Fields to update (name, points_possible, due_at, published, etc.).

        Returns:
            The updated assignment.
        """
        params = {f"assignment[{k}]": v for k, v in kwargs.items()}
        resp = self._client.put(
            self._course(f"/assignments/{assignment_id}"), data=params
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignmentResponse, strict=False)

    def delete_assignment(self, assignment_id: int) -> None:
        """Delete an assignment."""
        resp = self._client.delete(self._course(f"/assignments/{assignment_id}"))
        resp.raise_for_status()

    def list_assignment_groups(self) -> list[CanvasAssignmentGroup]:
        """List assignment groups (grade categories).

        Returns:
            Assignment groups with weights and rules.
        """
        data = self._get_paginated(self._course("/assignment_groups"))
        return msgspec.convert(data, list[CanvasAssignmentGroup], strict=False)

    def create_assignment_group(
        self,
        name: str,
        *,
        position: int | None = None,
        group_weight: float | None = None,
    ) -> CanvasAssignmentGroup:
        """Create a new assignment group.

        Args:
            name: Group name.
            position: Optional position in the group list.
            group_weight: Optional percentage weight for weighted grades.

        Returns:
            The created assignment group.
        """
        # Unlike most Canvas create endpoints, these params are not nested.
        params: dict[str, object] = {"name": name}
        if position is not None:
            params["position"] = position
        if group_weight is not None:
            params["group_weight"] = group_weight
        resp = self._client.post(self._course("/assignment_groups"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignmentGroup, strict=False)

    def delete_assignment_group(self, group_id: int) -> None:
        """Delete an assignment group (Canvas also deletes its assignments)."""
        resp = self._client.delete(self._course(f"/assignment_groups/{group_id}"))
        resp.raise_for_status()

    def resolve_assignment_group(self, id_or_name: str) -> CanvasAssignmentGroup:
        """Resolve an assignment group by numeric ID or name (case-insensitive).

        Raises:
            RuntimeError: If no group matches; the message lists the available groups.
        """
        groups = sorted(self.list_assignment_groups(), key=lambda g: g.position)
        return self._resolve(groups, id_or_name, "Assignment group", lambda g: g.name)

    def resolve_assignment(self, id_or_name: str) -> CanvasAssignmentResponse:
        """Resolve an assignment by numeric ID or name (case-insensitive).

        Raises:
            RuntimeError: If no assignment matches.
        """
        if id_or_name.isdigit():
            return self.get_assignment(int(id_or_name))
        return self._resolve(
            self.list_assignments(), id_or_name, "Assignment", lambda a: a.name
        )
