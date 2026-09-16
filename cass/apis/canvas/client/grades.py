"""Submissions, grade pushes, progress polling, and grade posting."""

from __future__ import annotations

__docformat__ = "google"

import logging
import time
from typing import Any

import httpx
import msgspec

from ..auth import CanvasAuthError
from ..schema import CanvasProgress, CanvasSubmissionResponse
from .base import BaseClient

_log = logging.getLogger(__name__)


class GradesMixin(BaseClient):
    """Submissions, grade pushes, progress polling, and grade posting."""

    def list_submissions(self, assignment_id: int) -> list[CanvasSubmissionResponse]:
        """List submissions for an assignment.

        Args:
            assignment_id: Canvas assignment ID.

        Returns:
            All submissions for the assignment.
        """
        data = self._get_paginated(
            self._course(f"/assignments/{assignment_id}/submissions")
        )
        return msgspec.convert(data, list[CanvasSubmissionResponse], strict=False)

    def push_grade(
        self, assignment_id: int, student_canvas_id: int, grade: str
    ) -> bool:
        """Push a single grade to Canvas.

        Args:
            assignment_id: Canvas assignment ID.
            student_canvas_id: Student's Canvas user ID.
            grade: Grade string to post.

        Returns:
            True on success, False on failure.
        """
        try:
            resp = self._client.put(
                self._course(
                    f"/assignments/{assignment_id}/submissions/{student_canvas_id}"
                ),
                data={"submission[posted_grade]": grade},
            )
            resp.raise_for_status()
            return True
        except CanvasAuthError:
            raise
        except (httpx.HTTPStatusError, RuntimeError) as exc:
            _log.warning(
                "Failed to push grade for student %s: %s", student_canvas_id, exc
            )
            return False

    def bulk_push_grades(
        self, assignment_id: int, grade_data: dict[int, str]
    ) -> CanvasProgress:
        """Push grades in bulk for one assignment via the update_grades endpoint.

        Args:
            assignment_id: Canvas assignment ID.
            grade_data: Mapping of student_canvas_id → posted_grade string.

        Returns:
            Progress object for tracking completion.
        """
        params: dict[str, str] = {}
        for student_id, grade in grade_data.items():
            params[f"grade_data[{student_id}][posted_grade]"] = grade
        resp = self._client.post(
            self._course(f"/assignments/{assignment_id}/submissions/update_grades"),
            data=params,
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasProgress, strict=False)

    def check_progress(self, progress_id: int) -> CanvasProgress:
        """Check the status of an async Canvas operation.

        Args:
            progress_id: Progress object ID.

        Returns:
            Current progress state.
        """
        resp = self._client.get(f"/progress/{progress_id}")
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasProgress, strict=False)

    def wait_for_progress(
        self, progress_id: int, *, timeout: float = 120.0
    ) -> CanvasProgress:
        """Poll a progress object until completion or timeout.

        Args:
            progress_id: Progress object ID.
            timeout: Maximum seconds to wait.

        Returns:
            Completed or failed progress object.

        Raises:
            RuntimeError: If the progress times out or fails.
        """
        start = time.time()
        while time.time() - start < timeout:
            p = self.check_progress(progress_id)
            if p.workflow_state == "completed":
                return p
            if p.workflow_state == "failed":
                raise RuntimeError(
                    f"Canvas bulk operation failed: {p.message or 'unknown error'}"
                )
            time.sleep(1.0)
        raise RuntimeError(f"Canvas bulk operation timed out after {timeout:.0f}s")

    def _graphql(
        self, query: str, variables: dict[str, object] | None = None
    ) -> dict[str, Any]:
        """Execute a Canvas GraphQL mutation/query.

        Args:
            query: GraphQL query or mutation string.
            variables: Optional variables dict.

        Returns:
            The ``data`` dict from the GraphQL response.

        Raises:
            RuntimeError: If the response contains top-level errors.
        """
        # GraphQL endpoint is at /api/graphql, not under /api/v1
        base = self._base_url.replace("/api/v1", "")
        payload: dict[str, object] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self._client.post(
            f"{base}/api/graphql",
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
            raise RuntimeError(f"Canvas GraphQL error: {msgs}")
        return body.get("data", {})

    _POST_GRADES_MUTATION = """
mutation ($assignmentId: ID!, $gradedOnly: Boolean) {
  postAssignmentGrades(input: {assignmentId: $assignmentId, gradedOnly: $gradedOnly}) {
    progress { _id state }
    errors { attribute message }
  }
}
"""

    _HIDE_GRADES_MUTATION = """
mutation ($assignmentId: ID!) {
  hideAssignmentGrades(input: {assignmentId: $assignmentId}) {
    progress { _id state }
    errors { attribute message }
  }
}
"""

    def post_assignment_grades(
        self, assignment_id: int, *, graded_only: bool = True
    ) -> CanvasProgress | None:
        """Post (reveal) grades to students for a manual-post assignment.

        Uses the Canvas GraphQL ``postAssignmentGrades`` mutation.

        Args:
            assignment_id: Canvas assignment ID.
            graded_only: If True, only post grades for graded submissions.

        Returns:
            Progress object for tracking, or None if no progress was started.

        Raises:
            RuntimeError: If the mutation returns validation errors.
        """
        data = self._graphql(
            self._POST_GRADES_MUTATION,
            {"assignmentId": str(assignment_id), "gradedOnly": graded_only},
        )
        result = data.get("postAssignmentGrades", {})
        errors: list[Any] = result.get("errors") or []
        if errors:
            msgs = "; ".join(f"{e['attribute']}: {e['message']}" for e in errors)
            raise RuntimeError(f"postAssignmentGrades failed: {msgs}")
        progress = result.get("progress")
        if progress and progress.get("_id"):
            return CanvasProgress(
                id=int(progress["_id"]),
                workflow_state=progress.get("state", "queued"),
            )
        return None

    def hide_assignment_grades(self, assignment_id: int) -> CanvasProgress | None:
        """Hide grades from students for a manual-post assignment.

        Uses the Canvas GraphQL ``hideAssignmentGrades`` mutation.

        Args:
            assignment_id: Canvas assignment ID.

        Returns:
            Progress object for tracking, or None if no progress was started.

        Raises:
            RuntimeError: If the mutation returns validation errors.
        """
        data = self._graphql(
            self._HIDE_GRADES_MUTATION,
            {"assignmentId": str(assignment_id)},
        )
        result = data.get("hideAssignmentGrades", {})
        errors: list[Any] = result.get("errors") or []
        if errors:
            msgs = "; ".join(f"{e['attribute']}: {e['message']}" for e in errors)
            raise RuntimeError(f"hideAssignmentGrades failed: {msgs}")
        progress = result.get("progress")
        if progress and progress.get("_id"):
            return CanvasProgress(
                id=int(progress["_id"]),
                workflow_state=progress.get("state", "queued"),
            )
        return None
