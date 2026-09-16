"""Viewer configuration — constants, display names, column config."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Internal tables shown only in the dev section
DEV_TABLES = {
    "_canvas_assignments_synced",
    "_canvas_grades_synced",
}

# Column display config: hide internal IDs, reorder for readability
HIDDEN_COLUMNS: dict[str, list[str]] = {
    "canvas_assignments": ["canvas_id"],
    "canvas_students": ["canvas_id"],
    "canvas_submissions": ["canvas_user_id", "canvas_assignment_id", "due_at", "late"],
    "canvas_grades": ["canvas_user_id", "canvas_assignment_id"],
}

COLUMN_ORDERING: dict[str, list[str]] = {
    "canvas_students": [
        "student",
        "email",
    ],
    "canvas_assignments": [
        "assignment_group",
        "name",
        "points_possible",
        "due_at",
        "published",
    ],
    "canvas_submissions": [
        "student",
        "assignment_name",
        "assignment_group",
        "submitted_at",
        "score",
        "workflow_state",
    ],
    "canvas_grades": [
        "student",
        "assignment_name",
        "assignment_group",
        "score",
        "posted_grade",
        "updated_at",
    ],
}

# Human-friendly column header names
COLUMN_DISPLAY_NAMES: dict[str, dict[str, str]] = {
    "canvas_students": {
        "student": "Student",
        "email": "Email",
        "canvas_id": "Canvas ID",
    },
    "canvas_assignments": {
        "assignment_group": "Group",
        "name": "Name",
        "points_possible": "Points",
        "due_at": "Deadline",
        "published": "Published",
    },
    "canvas_submissions": {
        "student": "Student",
        "assignment_name": "Assignment",
        "assignment_group": "Group",
        "submitted_at": "Submitted",
        "score": "Score",
        "workflow_state": "State",
    },
}

# Type aliases for pending changes
ChangeFields = dict[str, object]
RowChanges = dict[str, ChangeFields]
TableChanges = dict[str, RowChanges]
PendingChanges = dict[str, TableChanges]


# ---------------------------------------------------------------------------
# Display names and grouping
# ---------------------------------------------------------------------------

_DISPLAY_NAMES: dict[str, str] = {
    "canvas_students": "Students",
    "canvas_assignments": "Assignments",
    "canvas_submissions": "Submissions",
    "canvas_grades": "Gradebook",
}

# Desired display order within each group
_GROUP_ORDER: dict[str, list[str]] = {
    "canvas": [
        "canvas_grades",
        "canvas_assignments",
        "canvas_submissions",
    ],
}


def display_name(table: str) -> str:
    """Return a user-friendly display name for a table."""
    return _DISPLAY_NAMES.get(table, table)


def classify_table(name: str) -> str:
    """Classify a table into a sidebar group."""
    return "canvas" if name.startswith("canvas_") else "other"


def _sort_group(items: list[dict[str, str]], order: list[str]) -> list[dict[str, str]]:
    """Sort items by the predefined order, unknown items go last."""
    rank = {name: i for i, name in enumerate(order)}
    return sorted(items, key=lambda t: rank.get(t["name"], 999))


def group_tables(tables: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Group tables into sidebar sections."""
    canvas = [t for t in tables if classify_table(t["name"]) == "canvas"]
    if not canvas:
        return []
    return [
        {
            "label": "Canvas LMS",
            "items": _sort_group(canvas, _GROUP_ORDER["canvas"]),
        }
    ]
