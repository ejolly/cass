"""Canvas LMS API response types."""

from __future__ import annotations

import msgspec

from .github_api import GHStudentInfo


class CanvasStudent(msgspec.Struct):
    id: int
    name: str
    sortable_name: str = ""
    email: str = ""


class CanvasAssignment(msgspec.Struct):
    id: int
    name: str
    points_possible: float = 0.0
    due_at: str | None = None


class CanvasSubmission(msgspec.Struct):
    user_id: int
    submitted_at: str | None = None
    late: bool = False
    missing: bool = False
    seconds_late: float = 0.0
    grade: str | None = None
    score: float | None = None
    workflow_state: str = ""


class MatchResult(msgspec.Struct):
    matched: dict[str, int]  # gh_login -> canvas_id
    unmatched_gh: list[GHStudentInfo]
    unmatched_canvas: list[CanvasStudent]
