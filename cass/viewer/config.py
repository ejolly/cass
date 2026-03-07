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
    "students",
    "assignments",
}

CANVAS_PUSHABLE: dict[str, set[str]] = {
    "canvas_assignments": {"name", "points_possible", "due_at", "published"},
    "canvas_grades": {"posted_grade"},
}

# Column display config: hide internal IDs, reorder for readability
HIDDEN_COLUMNS: dict[str, list[str]] = {
    "canvas_assignments": ["canvas_id"],
    "canvas_students": ["canvas_id"],
    "canvas_submissions": ["canvas_user_id", "canvas_assignment_id", "due_at", "late"],
    "canvas_grades": ["canvas_user_id", "canvas_assignment_id"],
    "gh_assignments": ["gh_id", "slug", "starter_code_repo", "submittable_files"],
    "gh_students": ["github_id"],
    "gh_submissions": [
        "github_username",
        "assignment_slug",
        "last_commit_sha",
        "commit_url",
    ],
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
    "gh_students": [
        "excluded",
        "student",
        "github_username",
        "email",
    ],
    "gh_assignments": [
        "title",
        "points_possible",
        "deadline",
        "accepted",
        "submissions_count",
        "passing_count",
    ],
    "gh_submissions": [
        "last_commit_at",
        "student",
        "assignment_name",
        "commit_count",
        "repo_url",
        "late",
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
    "gh_students": {
        "excluded": "Hide",
        "student": "Student",
        "github_username": "GitHub Username",
        "email": "Email",
    },
    "gh_assignments": {
        "title": "Name",
        "points_possible": "Points",
        "deadline": "Deadline",
        "accepted": "Accepted",
        "submissions_count": "Submissions",
        "passing_count": "Passing",
    },
    "gh_submissions": {
        "last_commit_at": "Last Commit",
        "student": "Student",
        "assignment_name": "Assignment",
        "commit_count": "Commits",
        "repo_url": "Repo",
        "late": "Late",
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
    "gh_students": "Roster",
    "gh_assignments": "Assignments",
    "gh_submissions": "Recent Commits",
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
    "github": ["gh_submissions", "gh_students", "gh_assignments"],
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
    return "other"


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
    return groups
