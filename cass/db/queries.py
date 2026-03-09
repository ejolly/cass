"""Enriched queries and shared query dataset helpers."""

from __future__ import annotations

__docformat__ = "google"

import sqlite_utils

from .core import _SAFE_IDENT_RE, get_db

# ---------------------------------------------------------------------------
# Enriched queries — JOINed views used by the viewer and tests
# ---------------------------------------------------------------------------


def _last_first(name_expr: str) -> str:
    """SQLite expression to convert 'First Last' -> 'Last, First'."""
    return (
        f"CASE WHEN {name_expr} LIKE '% %'"
        f"  THEN substr({name_expr}, instr({name_expr}, ' ') + 1)"
        f"    || ', '"
        f"    || substr({name_expr}, 1, instr({name_expr}, ' ') - 1)"
        f"  ELSE {name_expr}"
        f" END"
    )


ENRICHED_QUERIES: dict[str, str] = {
    "canvas_submissions": """
        SELECT
            cs.canvas_user_id,
            cs.canvas_assignment_id,
            st.sortable_name AS student,
            ca.name AS assignment_name,
            ca.assignment_group,
            CASE WHEN cs.submitted_at IS NOT NULL
                THEN cs.submitted_at
                ELSE '' END AS submitted_at,
            ca.due_at,
            cs.score,
            cs.workflow_state,
            cs.late
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
    "gh_students": f"""
        SELECT
            gs.excluded,
            COALESCE(
                cs.sortable_name,
                {_last_first("gs.name")}
            ) AS student,
            gs.github_username,
            COALESCE(s.email, gs.email) AS email,
            gs.github_id
        FROM gh_students gs
        LEFT JOIN students s ON gs.github_username = s.github_username
        LEFT JOIN canvas_students cs ON s.canvas_id = cs.canvas_id
        ORDER BY student
    """,
    "gh_assignments": """
        SELECT
            ga.title,
            ga.points_possible,
            CASE WHEN ga.deadline IS NOT NULL
                THEN ga.deadline
                ELSE '' END AS deadline,
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
    "gh_submissions": f"""
        SELECT
            gs.github_username,
            gs.assignment_slug,
            CASE WHEN gs.last_commit_at != ''
                THEN gs.last_commit_at
                ELSE '' END AS last_commit_at,
            COALESCE(
                cs.sortable_name,
                {_last_first("gst.name")},
                gs.github_username
            ) AS student,
            ga.title AS assignment_name,
            gs.commit_count,
            CASE WHEN gs.last_commit_sha != ''
                THEN 'https://github.com/' || gs.repo_name
                    || '/commit/' || gs.last_commit_sha
                ELSE '' END AS commit_url,
            gs.late,
            'https://github.com/' || gs.repo_name AS repo_url,
            gs.last_commit_sha
        FROM gh_submissions gs
        LEFT JOIN students s ON gs.github_username = s.github_username
        LEFT JOIN gh_students gst
            ON gs.github_username = gst.github_username
        LEFT JOIN canvas_students cs ON s.canvas_id = cs.canvas_id
        LEFT JOIN gh_assignments ga ON gs.assignment_slug = ga.slug
        WHERE COALESCE(gst.excluded, 0) = 0
        ORDER BY gs.last_commit_at DESC, gs.github_username
    """,
}

QUERY_DATASETS = ("students", "assignments", "submissions", "gradebook")
TABLE_QUERY_DATASETS = {
    "students": "students",
    "assignments": "assignments",
}
SUBMISSIONS_BASE_QUERY = """
    SELECT * FROM (
      SELECT
        s.name AS student,
        a.slug AS assignment,
        'github' AS source,
        gs.submitted,
        gs.late,
        gs.lateness_seconds,
        gs.repo_name,
        gs.commits_after_deadline,
        gs.commit_count
      FROM gh_submissions gs
      JOIN students s ON s.github_username = gs.github_username
      JOIN assignments a ON a.gh_assignment_slug = gs.assignment_slug
      UNION ALL
      SELECT
        s.name AS student,
        a.slug AS assignment,
        'canvas' AS source,
        cs.submitted,
        cs.late,
        cs.lateness_seconds,
        '' AS repo_name,
        0 AS commits_after_deadline,
        0 AS commit_count
      FROM canvas_submissions cs
      JOIN students s ON s.canvas_id = cs.canvas_user_id
      JOIN assignments a ON a.canvas_assignment_id = cs.canvas_assignment_id
    ) submissions
"""


def build_submissions_query(
    *,
    where: str = "",
    order: str = "",
    limit: int = 0,
) -> str:
    """Build the shared submissions dataset query."""
    query = SUBMISSIONS_BASE_QUERY
    if where:
        query += f" WHERE {where}"
    query += f" ORDER BY {order or 'assignment, student'}"
    if limit:
        query += f" LIMIT {limit}"
    return query


def get_enriched_rows(
    sdb: sqlite_utils.Database,
    table: str,
) -> list[dict[str, object]]:
    """Return all rows from a table using enriched query if available."""
    if not _SAFE_IDENT_RE.match(table):
        msg = f"Invalid table name: {table!r}"
        raise ValueError(msg)
    query = ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = sdb.execute(query)
    col_names = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [dict(zip(col_names, row, strict=True)) for row in rows]


# ---------------------------------------------------------------------------
# Raw query (for `cass query`)
# ---------------------------------------------------------------------------


class QueryResult:
    """Thin wrapper around a sqlite3 cursor for Rich table rendering."""

    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]) -> None:
        self.columns = columns
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


def sql(query: str) -> QueryResult:
    """Execute SQL and return a QueryResult with .columns and .fetchall()."""
    sdb = get_db()
    cur = sdb.execute(query)
    cols = [desc[0] for desc in cur.description] if cur.description else []
    return QueryResult(cols, cur.fetchall())


def run_query(query: str) -> list[dict[str, object]]:
    """Execute arbitrary SQL and return results as list of dicts."""
    sdb = get_db()
    return list(sdb.query(query))
