"""DuckDB database for cass — per-project, self-contained."""

from __future__ import annotations

import time

import duckdb

from .config import get_config
from .models import Assignment, Grade, Student, Submission

DB_FILENAME = "cass.db"
_SCHEMA_VERSION = 4

_conn: duckdb.DuckDBPyConnection | None = None


def db_path() -> str:
    return str(get_config().root / DB_FILENAME)


def get_db() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is not None:
        return _conn
    _conn = duckdb.connect(db_path())
    _init_schema(_conn)
    return _conn


def reset() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    version = int(row[0]) if row else 0

    if version < _SCHEMA_VERSION:
        for table in ("students", "assignments", "submissions", "grades", "api_cache"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")

    conn.execute(
        """
        INSERT OR REPLACE INTO meta (key, value)
        VALUES ('schema_version', ?)
    """,
        [str(_SCHEMA_VERSION)],
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            endpoint TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            fetched_at DOUBLE NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            identifier TEXT NOT NULL,
            github_username TEXT NOT NULL DEFAULT '',
            github_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            canvas_id TEXT NOT NULL DEFAULT '',
            excluded BOOLEAN NOT NULL DEFAULT false
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            slug TEXT NOT NULL DEFAULT '',
            canvas_id INTEGER NOT NULL DEFAULT 0,
            deadline TIMESTAMPTZ,
            points_possible DOUBLE NOT NULL DEFAULT 0,
            accepted INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            student_id TEXT NOT NULL,
            assignment_id TEXT NOT NULL,
            source TEXT NOT NULL,
            submitted BOOLEAN NOT NULL DEFAULT false,
            submitted_at TIMESTAMPTZ,
            late BOOLEAN NOT NULL DEFAULT false,
            lateness_seconds INTEGER NOT NULL DEFAULT 0,
            repo_name TEXT NOT NULL DEFAULT '',
            commits_after_deadline INTEGER NOT NULL DEFAULT 0,
            score DOUBLE,
            workflow_state TEXT NOT NULL DEFAULT '',
            fetched_at DOUBLE NOT NULL,
            PRIMARY KEY (student_id, assignment_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grades (
            student_id TEXT NOT NULL,
            assignment_id TEXT NOT NULL,
            grade TEXT NOT NULL,
            numeric_score DOUBLE,
            source TEXT NOT NULL DEFAULT 'auto',
            updated_at DOUBLE NOT NULL,
            PRIMARY KEY (student_id, assignment_id)
        )
    """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STUDENT_COLS = (
    "identifier",
    "github_username",
    "github_id",
    "name",
    "canvas_id",
    "excluded",
)
_ASSIGNMENT_COLS = (
    "id",
    "source",
    "title",
    "slug",
    "canvas_id",
    "deadline",
    "points_possible",
    "accepted",
)
_SUBMISSION_COLS = (
    "student_id",
    "assignment_id",
    "source",
    "submitted",
    "submitted_at",
    "late",
    "lateness_seconds",
    "repo_name",
    "commits_after_deadline",
    "score",
    "workflow_state",
)
_GRADE_COLS = ("student_id", "assignment_id", "grade", "numeric_score", "source")


def _rows_to_structs(rows: list[tuple], cols: tuple[str, ...], struct_type: type):
    """Convert positional rows to struct instances using named columns."""
    return [struct_type(**dict(zip(cols, row))) for row in rows]


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


def save_students(students: list[Student]) -> int:
    conn = get_db()
    conn.execute("DELETE FROM students")
    if not students:
        return 0
    conn.executemany(
        "INSERT INTO students (identifier, github_username, github_id, name, canvas_id, excluded) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                s.identifier,
                s.github_username,
                s.github_id,
                s.name,
                s.canvas_id,
                s.excluded,
            )
            for s in students
        ],
    )
    return len(students)


def load_students(include_excluded: bool = False) -> list[Student]:
    conn = get_db()
    where = "" if include_excluded else "WHERE excluded = false"
    cols = _STUDENT_COLS
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM students {where} ORDER BY lower(identifier)"
    ).fetchall()
    return _rows_to_structs(rows, cols, Student)


def students_exist() -> bool:
    try:
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) FROM students").fetchone()
        return row is not None and row[0] > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


def save_assignments(assignments: list[Assignment]) -> int:
    conn = get_db()
    conn.execute("DELETE FROM assignments")
    if not assignments:
        return 0
    conn.executemany(
        "INSERT INTO assignments (id, source, title, slug, canvas_id, deadline, points_possible, accepted) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                a.id,
                a.source,
                a.title,
                a.slug,
                a.canvas_id,
                a.deadline,
                a.points_possible,
                a.accepted,
            )
            for a in assignments
        ],
    )
    return len(assignments)


def load_assignments() -> list[Assignment]:
    conn = get_db()
    cols = _ASSIGNMENT_COLS
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM assignments ORDER BY id"
    ).fetchall()
    return _rows_to_structs(rows, cols, Assignment)


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def save_submissions(submissions: list[Submission]) -> int:
    conn = get_db()
    now = time.time()
    if not submissions:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO submissions "
        "(student_id, assignment_id, source, submitted, submitted_at, late, "
        "lateness_seconds, repo_name, commits_after_deadline, score, workflow_state, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                s.student_id,
                s.assignment_id,
                s.source,
                s.submitted,
                s.submitted_at,
                s.late,
                s.lateness_seconds,
                s.repo_name,
                s.commits_after_deadline,
                s.score,
                s.workflow_state,
                now,
            )
            for s in submissions
        ],
    )
    return len(submissions)


def load_submissions(assignment_id: str | None = None) -> list[Submission]:
    conn = get_db()
    cols = _SUBMISSION_COLS
    select = f"SELECT {', '.join(cols)} FROM submissions"
    if assignment_id:
        rows = conn.execute(
            f"{select} WHERE assignment_id = ? ORDER BY student_id",
            [assignment_id],
        ).fetchall()
    else:
        rows = conn.execute(f"{select} ORDER BY assignment_id, student_id").fetchall()
    return _rows_to_structs(rows, cols, Submission)


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------


def save_grades(grades: list[Grade]) -> int:
    conn = get_db()
    now = time.time()
    if not grades:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO grades "
        "(student_id, assignment_id, grade, numeric_score, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (g.student_id, g.assignment_id, g.grade, g.numeric_score, g.source, now)
            for g in grades
        ],
    )
    return len(grades)


def load_grades(assignment_id: str | None = None) -> list[Grade]:
    conn = get_db()
    cols = _GRADE_COLS
    select = f"SELECT {', '.join(cols)} FROM grades"
    if assignment_id:
        rows = conn.execute(
            f"{select} WHERE assignment_id = ? ORDER BY student_id",
            [assignment_id],
        ).fetchall()
    else:
        rows = conn.execute(f"{select} ORDER BY assignment_id, student_id").fetchall()
    return _rows_to_structs(rows, cols, Grade)


# ---------------------------------------------------------------------------
# Cache (kept here for consolidation)
# ---------------------------------------------------------------------------


def cache_load(key: str, ttl_hours: float = 6) -> str | None:
    """Return cached JSON string if fresh, else None."""
    conn = get_db()
    row = conn.execute(
        "SELECT data, fetched_at FROM api_cache WHERE endpoint = ?", [key]
    ).fetchone()
    if row is None:
        return None
    age_hours = (time.time() - row[1]) / 3600
    if age_hours > ttl_hours:
        return None
    return row[0]


def cache_save(key: str, data: str) -> None:
    """Write JSON string to cache."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (endpoint, data, fetched_at) "
        "VALUES (?, ?, ?)",
        [key, data, time.time()],
    )


def cache_clear() -> None:
    conn = get_db()
    conn.execute("DELETE FROM api_cache")


def cache_count() -> int:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()
    return row[0] if row else 0


def cache_list() -> list[tuple[str, float]]:
    conn = get_db()
    return conn.execute(
        "SELECT endpoint, fetched_at FROM api_cache ORDER BY fetched_at DESC"
    ).fetchall()


# ---------------------------------------------------------------------------
# Raw query (for `cass query`)
# ---------------------------------------------------------------------------


def run_query(sql: str) -> duckdb.DuckDBPyRelation:
    conn = get_db()
    return conn.sql(sql)
