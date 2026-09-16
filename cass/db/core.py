"""SQLite database for cass — connection, schema, meta, and CRUD.

Schema v16: Canvas source tables (canvas_*) plus Canvas grade tables for
manual push workflows. Synced shadow tables (_canvas_assignments_synced,
_canvas_grades_synced) provide persistent change tracking between local
edits and Canvas state.
"""

from __future__ import annotations

__docformat__ = "google"

import re
import sqlite3
import time
from pathlib import Path

import sqlite_utils

from ..actions.config import get_config
from .catalog import CANVAS_WORKING_TABLES
from .schema import (
    CanvasAssignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
)

DB_FILENAME = "cass.db"
_SCHEMA_VERSION = 16
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Tables excluded from the viewer entirely
EXCLUDED_TABLES = {
    "meta",
    "_canvas_assignments_synced",
    "_canvas_grades_synced",
}

_db: sqlite_utils.Database | None = None
_db_path: str | None = None


def _commit(sdb: sqlite_utils.Database) -> None:
    """Persist pending writes on the underlying sqlite connection."""
    conn = sdb.conn
    if conn is None:
        msg = "Database connection is not open"
        raise RuntimeError(msg)
    conn.commit()


def _connection(sdb: sqlite_utils.Database) -> sqlite3.Connection:
    """Return the live sqlite3 connection or raise if it is unavailable."""
    conn = sdb.conn
    if conn is None:
        msg = "Database connection is not open"
        raise RuntimeError(msg)
    return conn


def _is_connection_usable(sdb: sqlite_utils.Database) -> bool:
    """Return whether the underlying sqlite connection can still execute SQL."""
    try:
        _connection(sdb).execute("SELECT 1").fetchone()
    except (RuntimeError, sqlite3.Error):
        return False
    return True


def db_path(root: Path | None = None) -> str:
    """Return the SQLite file path."""
    project_root = root if root is not None else get_config().root
    return str(project_root / DB_FILENAME)


def connect_db(root: Path | None = None) -> sqlite_utils.Database:
    """Open a lightweight connection to an existing database.

    Unlike ``open_db``, this skips schema init and reconciliation — use it
    when you know the DB already exists (e.g. in a background thread while
    the viewer's main connection is alive).
    """
    sdb = sqlite_utils.Database(db_path(root))
    sdb.execute("PRAGMA journal_mode=WAL")
    sdb.execute("PRAGMA busy_timeout=5000")
    return sdb


def open_db(root: Path | None = None) -> sqlite_utils.Database:
    """Open a database for the resolved project root and ensure schema exists."""
    sdb = sqlite_utils.Database(db_path(root))
    sdb.execute("PRAGMA journal_mode=WAL")
    sdb.execute("PRAGMA busy_timeout=5000")
    init_schema(sdb)
    return sdb


def get_db(root: Path | None = None) -> sqlite_utils.Database:
    """Return the shared Database, creating it on first call."""
    global _db, _db_path
    if _db is not None and _db_path is None:
        if _is_connection_usable(_db):
            return _db
        reset()
    target_path = db_path(root)
    if _db is not None and _db_path == target_path:
        if _is_connection_usable(_db):
            return _db
        reset()
    if _db is not None and _db_path != target_path:
        reset()
    _db = open_db(root)
    _db_path = target_path
    return _db


def reset() -> None:
    global _db, _db_path
    if _db is not None:
        conn = _db.conn
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _db = None
    _db_path = None


def editable_canvas_tables() -> set[str]:
    """Return the current editable Canvas-managed working tables."""
    return set(CANVAS_WORKING_TABLES)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def init_schema(sdb: sqlite_utils.Database) -> None:
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    row = sdb.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    version = int(row[0]) if row else 0

    if version < _SCHEMA_VERSION:
        # Drop all old tables (clean migration)
        for table in (
            "students",
            "assignments",
            "submissions",
            "grades",
            "api_cache",
            "gh_students",
            "canvas_students",
            "gh_assignments",
            "canvas_assignments",
            "gh_submissions",
            "canvas_submissions",
            "canvas_grades",
            "_canvas_assignments_synced",
            "_canvas_grades_synced",
        ):
            sdb.execute(f"DROP TABLE IF EXISTS {table}")

    sdb.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        [str(_SCHEMA_VERSION)],
    )

    # --- Source tables ---

    sdb.execute("""
        CREATE TABLE IF NOT EXISTS canvas_students (
            canvas_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sortable_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            login_id TEXT NOT NULL DEFAULT '',
            sis_user_id TEXT NOT NULL DEFAULT '',
            sis_section_id TEXT NOT NULL DEFAULT ''
        )
    """)
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS canvas_assignments (
            canvas_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            points_possible REAL NOT NULL DEFAULT 0,
            due_at TEXT,
            published BOOLEAN NOT NULL DEFAULT 0,
            assignment_group TEXT NOT NULL DEFAULT '',
            post_manually BOOLEAN NOT NULL DEFAULT 0
        )
    """)
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS canvas_submissions (
            canvas_user_id INTEGER NOT NULL,
            canvas_assignment_id INTEGER NOT NULL,
            submitted BOOLEAN NOT NULL DEFAULT 0,
            submitted_at TEXT,
            late BOOLEAN NOT NULL DEFAULT 0,
            lateness_seconds INTEGER NOT NULL DEFAULT 0,
            score REAL,
            workflow_state TEXT NOT NULL DEFAULT '',
            fetched_at REAL NOT NULL,
            PRIMARY KEY (canvas_user_id, canvas_assignment_id)
        )
    """)

    # --- Grade tables ---

    sdb.execute("""
        CREATE TABLE IF NOT EXISTS canvas_grades (
            canvas_user_id INTEGER NOT NULL,
            canvas_assignment_id INTEGER NOT NULL,
            score REAL,
            posted_grade TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (canvas_user_id, canvas_assignment_id)
        )
    """)

    # --- Synced shadow tables (last-known Canvas state) ---

    sdb.execute("""
        CREATE TABLE IF NOT EXISTS _canvas_assignments_synced (
            canvas_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            points_possible REAL NOT NULL DEFAULT 0,
            due_at TEXT,
            published BOOLEAN NOT NULL DEFAULT 0
        )
    """)
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS _canvas_grades_synced (
            canvas_user_id INTEGER NOT NULL,
            canvas_assignment_id INTEGER NOT NULL,
            posted_grade TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (canvas_user_id, canvas_assignment_id)
        )
    """)


# ---------------------------------------------------------------------------
# Meta helpers
# ---------------------------------------------------------------------------


def save_meta(key: str, value: str) -> None:
    """Store a key-value pair in the meta table."""
    sdb = get_db()
    sdb.table("meta").insert({"key": key, "value": value}, pk="key", replace=True)  # pyright: ignore[reportUnknownMemberType]


def get_meta(key: str, sdb: sqlite_utils.Database | None = None) -> str | None:
    """Retrieve a value from the meta table, or None if not found."""
    c = sdb or get_db()
    try:
        row = c.table("meta").get(key)  # pyright: ignore[reportUnknownMemberType]
        return row["value"]  # pyright: ignore[reportReturnType]
    except sqlite_utils.db.NotFoundError:
        return None


# ---------------------------------------------------------------------------
# Canvas Students (source)
# ---------------------------------------------------------------------------


def save_canvas_students(students: list[CanvasStudent]) -> int:
    """Upsert Canvas students into the source table."""
    if not students:
        return 0
    sdb = get_db()
    sdb.table("canvas_students").insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "canvas_id": s.canvas_id,
                "name": s.name,
                "sortable_name": s.sortable_name,
                "email": s.email,
                "login_id": s.login_id,
                "sis_user_id": s.sis_user_id,
                "sis_section_id": s.sis_section_id,
            }
            for s in students
        ],
        pk="canvas_id",
        replace=True,
    )
    return len(students)


def load_canvas_student_ids() -> set[int]:
    """Return every canvas_id in the Canvas roster."""
    sdb = get_db()
    rows = sdb.execute("SELECT canvas_id FROM canvas_students").fetchall()
    return {int(r[0]) for r in rows}


# ---------------------------------------------------------------------------
# Canvas Assignments (source)
# ---------------------------------------------------------------------------


def save_canvas_assignments(assignments: list[CanvasAssignment]) -> int:
    """Save Canvas assignments from domain models."""
    if not assignments:
        return 0
    sdb = get_db()
    sdb.table("canvas_assignments").insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "canvas_id": a.canvas_id,
                "name": a.name,
                "points_possible": a.points_possible,
                "due_at": a.due_at,
                "published": a.published,
                "assignment_group": a.assignment_group,
                "post_manually": a.post_manually,
            }
            for a in assignments
        ],
        pk="canvas_id",
        replace=True,
    )
    return len(assignments)


def load_canvas_assignment_ids() -> list[int]:
    """Return every Canvas assignment id, ascending."""
    sdb = get_db()
    rows = sdb.execute(
        "SELECT canvas_id FROM canvas_assignments ORDER BY canvas_id"
    ).fetchall()
    return [int(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# Canvas Submissions
# ---------------------------------------------------------------------------


def save_canvas_submissions(subs: list[CanvasSubmission]) -> int:
    """Upsert Canvas submissions."""
    if not subs:
        return 0
    now = time.time()
    sdb = get_db()
    sdb.table("canvas_submissions").insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "canvas_user_id": s.canvas_user_id,
                "canvas_assignment_id": s.canvas_assignment_id,
                "submitted": s.submitted,
                "submitted_at": s.submitted_at,
                "late": s.late,
                "lateness_seconds": s.lateness_seconds,
                "score": s.score,
                "workflow_state": s.workflow_state,
                "fetched_at": now,
            }
            for s in subs
        ],
        pk=("canvas_user_id", "canvas_assignment_id"),
        replace=True,
    )
    return len(subs)


# ---------------------------------------------------------------------------
# Canvas Grades
# ---------------------------------------------------------------------------


def upsert_canvas_grade(
    sdb: sqlite_utils.Database,
    canvas_user_id: int,
    canvas_assignment_id: int,
    posted_grade: str,
) -> str:
    """Insert or update a single canvas grade, returning the previous value.

    Returns:
        Previous posted_grade (empty string if row didn't exist).
    """
    tbl = sdb.table("canvas_grades")
    try:
        old_row = tbl.get((canvas_user_id, canvas_assignment_id))  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        old_value: str = old_row["posted_grade"]  # pyright: ignore[reportUnknownMemberType,reportIndexIssue]
    except sqlite_utils.db.NotFoundError:
        old_value = ""

    tbl.insert(  # pyright: ignore[reportUnknownMemberType]
        {
            "canvas_user_id": canvas_user_id,
            "canvas_assignment_id": canvas_assignment_id,
            "posted_grade": posted_grade,
            "updated_at": time.time(),
        },
        pk=("canvas_user_id", "canvas_assignment_id"),
        replace=True,
    )
    return old_value


def get_assignment_groups(sdb: sqlite_utils.Database) -> list[str]:
    """Return distinct non-empty assignment groups, sorted alphabetically."""
    if "canvas_assignments" not in sdb.table_names():
        return []
    return sorted(
        {
            row["assignment_group"]
            for row in sdb.table("canvas_assignments").rows_where(
                "assignment_group != ''"
            )  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        }
    )


def save_canvas_grades(grades: list[CanvasGrade]) -> int:
    """Upsert Canvas grades."""
    if not grades:
        return 0
    now = time.time()
    sdb = get_db()
    sdb.table("canvas_grades").insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "canvas_user_id": g.canvas_user_id,
                "canvas_assignment_id": g.canvas_assignment_id,
                "score": g.score,
                "posted_grade": g.posted_grade,
                "updated_at": now,
            }
            for g in grades
        ],
        pk=("canvas_user_id", "canvas_assignment_id"),
        replace=True,
    )
    return len(grades)


def load_canvas_grades(canvas_assignment_id: int | None = None) -> list[CanvasGrade]:
    """Load Canvas grades."""
    sdb = get_db()
    if canvas_assignment_id:
        rows = sdb.execute(
            "SELECT canvas_user_id, canvas_assignment_id, score, posted_grade "
            "FROM canvas_grades WHERE canvas_assignment_id = ? ORDER BY canvas_user_id",
            [canvas_assignment_id],
        ).fetchall()
    else:
        rows = sdb.execute(
            "SELECT canvas_user_id, canvas_assignment_id, score, posted_grade "
            "FROM canvas_grades ORDER BY canvas_assignment_id, canvas_user_id"
        ).fetchall()
    return [
        CanvasGrade(
            canvas_user_id=r[0],
            canvas_assignment_id=r[1],
            score=r[2],
            posted_grade=r[3],
        )
        for r in rows
    ]
