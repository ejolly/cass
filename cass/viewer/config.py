"""Viewer configuration — constants, display names, column config."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCLUDED_TABLES = {"meta", "canvas_students"}

READ_ONLY_TABLES = {
    "canvas_submissions",
    "gh_assignments",
    "gh_submissions",
    "gh_students",
    "gh_grades",
    "assignments",
    "students",
}

CANVAS_PUSHABLE: dict[str, set[str]] = {
    "canvas_assignments": {"name", "points_possible", "due_at", "published"},
    "canvas_grades": {"posted_grade"},
}

ENRICHED_QUERIES: dict[str, str] = {
    "canvas_submissions": """
        SELECT
            cs.canvas_user_id,
            cs.canvas_assignment_id,
            st.sortable_name AS student,
            ca.name AS assignment_name,
            ca.assignment_group,
            cs.submitted_at,
            ca.due_at,
            cs.score,
            cs.workflow_state
        FROM canvas_submissions cs
        LEFT JOIN canvas_students st ON cs.canvas_user_id = st.canvas_id
        LEFT JOIN canvas_assignments ca
            ON cs.canvas_assignment_id = ca.canvas_id
    """,
    "canvas_students": """
        SELECT
            cs.sortable_name AS student,
            cs.email,
            cs.canvas_id
        FROM canvas_students cs
        ORDER BY cs.sortable_name
    """,
    "canvas_assignments": """
        SELECT
            ca.assignment_group,
            ca.name,
            ca.points_possible,
            ca.due_at,
            ca.published,
            ca.canvas_id
        FROM canvas_assignments ca
        ORDER BY ca.assignment_group, ca.name
    """,
    "canvas_grades": """
        SELECT
            cg.canvas_user_id,
            cg.canvas_assignment_id,
            st.sortable_name AS student,
            ca.name AS assignment_name,
            ca.assignment_group,
            cg.score,
            cg.posted_grade,
            cg.updated_at
        FROM canvas_grades cg
        LEFT JOIN canvas_students st ON cg.canvas_user_id = st.canvas_id
        LEFT JOIN canvas_assignments ca
            ON cg.canvas_assignment_id = ca.canvas_id
    """,
}

# Column display config: hide internal IDs, reorder for readability
HIDDEN_COLUMNS: dict[str, list[str]] = {
    "canvas_assignments": ["canvas_id"],
    "canvas_students": ["canvas_id"],
    "canvas_submissions": ["canvas_user_id", "canvas_assignment_id", "due_at"],
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
    "gh_students": "Students",
    "gh_assignments": "Assignments",
    "gh_submissions": "Submissions",
    "gh_grades": "Grades",
    "students": "Students",
    "assignments": "Assignments",
}

# Desired display order within each group
_GROUP_ORDER: dict[str, list[str]] = {
    "canvas": [
        "canvas_grades",
        "canvas_assignments",
        "canvas_submissions",
    ],
    "github": ["gh_students", "gh_assignments", "gh_submissions", "gh_grades"],
    "combined": ["students", "assignments"],
}


def display_name(table: str) -> str:
    """Return a user-friendly display name for a table."""
    return _DISPLAY_NAMES.get(table, table)


def classify_table(name: str) -> str:
    """Classify a table into a sidebar group."""
    if name.startswith("canvas_"):
        return "canvas"
    if name.startswith("gh_"):
        return "github"
    return "combined"


def _sort_group(items: list[dict[str, str]], order: list[str]) -> list[dict[str, str]]:
    """Sort items by the predefined order, unknown items go last."""
    rank = {name: i for i, name in enumerate(order)}
    return sorted(items, key=lambda t: rank.get(t["name"], 999))


def group_tables(
    tables: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Group tables into sidebar sections."""
    canvas = [t for t in tables if classify_table(t["name"]) == "canvas"]
    github = [t for t in tables if classify_table(t["name"]) == "github"]
    combined = [t for t in tables if classify_table(t["name"]) == "combined"]
    groups: list[dict[str, Any]] = []
    if canvas:
        groups.append(
            {
                "label": "Canvas LMS",
                "items": _sort_group(canvas, _GROUP_ORDER["canvas"]),
            }
        )
    if github:
        groups.append(
            {
                "label": "GitHub Classroom",
                "items": _sort_group(github, _GROUP_ORDER["github"]),
            }
        )
    if combined:
        groups.append(
            {
                "label": "Combined",
                "items": _sort_group(combined, _GROUP_ORDER["combined"]),
            }
        )
    return groups
