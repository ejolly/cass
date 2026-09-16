"""Enriched queries and shared query dataset helpers."""

from __future__ import annotations

__docformat__ = "google"

import sqlite_utils

from .core import _SAFE_IDENT_RE, get_db

# ---------------------------------------------------------------------------
# Enriched queries — JOINed views used by the viewer and tests
# ---------------------------------------------------------------------------

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
}

QUERY_DATASETS = ("students", "assignments", "submissions", "gradebook")
TABLE_QUERY_DATASETS = {
    "students": "canvas_students",
    "assignments": "canvas_assignments",
}
SUBMISSIONS_BASE_QUERY = """
    SELECT * FROM (
      SELECT
        st.sortable_name AS student,
        ca.name AS assignment,
        cs.submitted,
        cs.submitted_at,
        cs.late,
        cs.lateness_seconds,
        cs.score,
        cs.workflow_state
      FROM canvas_submissions cs
      JOIN canvas_students st ON st.canvas_id = cs.canvas_user_id
      JOIN canvas_assignments ca ON ca.canvas_id = cs.canvas_assignment_id
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
