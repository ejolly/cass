"""Viewer configuration — constants, display names, column config."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCLUDED_TABLES = {
    "meta",
    "canvas_students",
    "gh_grades",
    "_canvas_assignments_synced",
    "_canvas_grades_synced",
}

# Internal tables shown only in the dev section
DEV_TABLES = {"_canvas_assignments_synced", "_canvas_grades_synced"}

READ_ONLY_TABLES = {
    "canvas_submissions",
    "gh_submissions",
    "gh_students",
    "gh_assignments",
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
    "gh_students": """
        SELECT
            COALESCE(s.name, gs.name) AS student,
            gs.github_username,
            COALESCE(s.email, gs.email) AS email,
            gs.github_id
        FROM gh_students gs
        LEFT JOIN students s ON gs.github_username = s.github_username
        ORDER BY student
    """,
    "gh_assignments": """
        SELECT
            ga.title,
            ga.points_possible,
            ga.deadline,
            ga.accepted,
            ga.submissions_count,
            ga.passing_count,
            ga.slug,
            ga.gh_id,
            ga.starter_code_repo,
            ga.submittable_files
        FROM gh_assignments ga
        ORDER BY ga.deadline, ga.title
    """,
    "gh_submissions": """
        SELECT
            gs.github_username,
            gs.assignment_slug,
            COALESCE(s.name, gst.name, gs.github_username) AS student,
            ga.title AS assignment_name,
            gs.submitted,
            gs.commit_count,
            gs.commits_after_deadline,
            gs.late,
            'https://github.com/' || gs.repo_name AS repo_url,
            CASE WHEN gs.last_commit_sha != ''
                THEN 'https://github.com/' || gs.repo_name
                    || '/commit/' || gs.last_commit_sha
                ELSE '' END AS commit_url,
            gs.last_commit_at,
            gs.last_commit_sha
        FROM gh_submissions gs
        LEFT JOIN students s ON gs.github_username = s.github_username
        LEFT JOIN gh_students gst
            ON gs.github_username = gst.github_username
        LEFT JOIN gh_assignments ga ON gs.assignment_slug = ga.slug
        ORDER BY gs.last_commit_at DESC, gs.github_username
    """,
}

# Column display config: hide internal IDs, reorder for readability
HIDDEN_COLUMNS: dict[str, list[str]] = {
    "canvas_assignments": ["canvas_id"],
    "canvas_students": ["canvas_id"],
    "canvas_submissions": ["canvas_user_id", "canvas_assignment_id", "due_at"],
    "canvas_grades": ["canvas_user_id", "canvas_assignment_id"],
    "gh_assignments": ["gh_id", "slug", "starter_code_repo", "submittable_files"],
    "gh_students": ["github_id"],
    "gh_submissions": [
        "github_username",
        "assignment_slug",
        "last_commit_sha",
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
        "student",
        "assignment_name",
        "submitted",
        "commit_count",
        "commits_after_deadline",
        "late",
        "repo_url",
        "commit_url",
        "last_commit_at",
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
        "student": "Student",
        "assignment_name": "Assignment",
        "submitted": "Submitted",
        "commit_count": "Commits",
        "commits_after_deadline": "Late Commits",
        "late": "Late",
        "repo_url": "Repo",
        "commit_url": "Latest Commit",
        "last_commit_at": "Last Commit",
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
    "github": ["gh_assignments", "gh_submissions", "gh_students"],
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
