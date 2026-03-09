"""SQLite database for cass — connection, schema, meta, and CRUD.

Schema v15: source-specific tables (gh_*, canvas_*) with proper keys,
master tables (students, assignments) as unified joins, and Canvas
grade tables for manual push workflows. Synced shadow tables
(_canvas_assignments_synced, _canvas_grades_synced) provide persistent
change tracking between local edits and Canvas state.
"""

from __future__ import annotations

__docformat__ = "google"

import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import sqlite_utils

from ..actions.config import CONFIG_FILENAME, get_config, read_config_data
from .catalog import CANVAS_WORKING_TABLES
from .schema import (
    Assignment,
    CanvasAssignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
    GHAssignment,
    GHStudent,
    GHSubmission,
    Student,
)

DB_FILENAME = "cass.db"
_SCHEMA_VERSION = 15
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Tables excluded from the viewer entirely
EXCLUDED_TABLES = {
    "meta",
    "canvas_students",
    "_canvas_assignments_synced",
    "_canvas_grades_synced",
}

# Tables shown in the viewer but not editable
READ_ONLY_TABLES = {
    "canvas_submissions",
    "gh_submissions",
    "gh_assignments",
    "assignments",
    "students",
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


def _has_classroom_url_config(root: Path | None = None) -> bool:
    """Return whether the resolved project config includes a Classroom URL."""
    if root is None:
        try:
            return get_config().has_classroom_url
        except SystemExit:
            return False

    cfg_path = root / CONFIG_FILENAME
    if not cfg_path.exists():
        return False
    classroom = read_config_data(cfg_path).get("classroom", {})
    return bool(classroom.get("url", "") and classroom.get("url_id", 0))


def _has_classroom_config(root: Path | None = None) -> bool:
    """Return whether the resolved project config includes full Classroom settings."""
    if root is None:
        try:
            return get_config().has_classroom
        except SystemExit:
            return False

    cfg_path = root / CONFIG_FILENAME
    if not cfg_path.exists():
        return False
    classroom = read_config_data(cfg_path).get("classroom", {})
    return bool(classroom.get("url", "") and classroom.get("gh_id", 0))


def _reconcile_project_data(
    sdb: sqlite_utils.Database,
    *,
    root: Path | None = None,
) -> None:
    """Ensure source-specific tables match the active project configuration."""
    if not _has_classroom_url_config(root):
        clear_github_data(sdb)


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
    _reconcile_project_data(sdb, root=root)
    return sdb


def get_db(root: Path | None = None) -> sqlite_utils.Database:
    """Return the shared Database, creating it on first call."""
    global _db, _db_path
    target_path = db_path(root)
    if _db is not None and (_db_path is None or _db_path == target_path):
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
        CREATE TABLE IF NOT EXISTS gh_students (
            github_username TEXT PRIMARY KEY,
            github_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            excluded BOOLEAN NOT NULL DEFAULT 0
        )
    """)
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
        CREATE TABLE IF NOT EXISTS gh_assignments (
            slug TEXT PRIMARY KEY,
            gh_id INTEGER NOT NULL UNIQUE,
            title TEXT NOT NULL,
            deadline TEXT,
            points_possible REAL NOT NULL DEFAULT 1.0,
            accepted INTEGER NOT NULL DEFAULT 0,
            submissions_count INTEGER NOT NULL DEFAULT 0,
            passing_count INTEGER NOT NULL DEFAULT 0,
            starter_code_repo TEXT NOT NULL DEFAULT '',
            submittable_files TEXT NOT NULL DEFAULT ''
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
        CREATE TABLE IF NOT EXISTS gh_submissions (
            github_username TEXT NOT NULL,
            assignment_slug TEXT NOT NULL,
            submitted BOOLEAN NOT NULL DEFAULT 0,
            late BOOLEAN NOT NULL DEFAULT 0,
            lateness_seconds INTEGER NOT NULL DEFAULT 0,
            repo_name TEXT NOT NULL DEFAULT '',
            commits_after_deadline INTEGER NOT NULL DEFAULT 0,
            commit_count INTEGER NOT NULL DEFAULT 0,
            passing BOOLEAN NOT NULL DEFAULT 0,
            gh_autograder_score TEXT NOT NULL DEFAULT '',
            last_commit_at TEXT NOT NULL DEFAULT '',
            last_commit_sha TEXT NOT NULL DEFAULT '',
            fetched_at REAL NOT NULL,
            PRIMARY KEY (github_username, assignment_slug)
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

    # --- Master tables ---

    sdb.execute("""
        CREATE TABLE IF NOT EXISTS students (
            canvas_id INTEGER PRIMARY KEY,
            github_username TEXT UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            excluded BOOLEAN NOT NULL DEFAULT 0
        )
    """)
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            gh_assignment_slug TEXT UNIQUE,
            canvas_assignment_id INTEGER UNIQUE,
            points_possible REAL NOT NULL DEFAULT 0,
            deadline TEXT
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
# GH Students (source)
# ---------------------------------------------------------------------------


def save_gh_students(students: list[GHStudent]) -> int:
    """Upsert GitHub students into the source table."""
    if not students:
        return 0
    sdb = get_db()
    sdb.table("gh_students").insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "github_username": s.github_username,
                "github_id": s.github_id,
                "name": s.name,
                "email": s.email,
            }
            for s in students
        ],
        pk="github_username",
        replace=True,
    )
    return len(students)


def load_gh_student_handles() -> set[str]:
    """Return the set of github_username values from the GH Classroom roster."""
    sdb = get_db()
    return {
        row["github_username"]
        for row in sdb.table("gh_students").rows_where("excluded = 0")  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    }


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


# ---------------------------------------------------------------------------
# Students (master)
# ---------------------------------------------------------------------------


def upsert_students(students: list[Student]) -> int:
    """Upsert into master students table, preserving existing github_username."""
    sdb = get_db()
    if not students:
        return 0
    tbl = sdb.table("students")
    for s in students:
        gh = s.github_username
        try:
            existing = tbl.get(s.canvas_id)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            existing_gh: str = existing["github_username"]  # pyright: ignore[reportAssignmentType]
            if existing_gh and not gh:
                gh = existing_gh  # preserve existing mapping
        except sqlite_utils.db.NotFoundError:
            pass
        tbl.insert(  # pyright: ignore[reportUnknownMemberType]
            {
                "canvas_id": s.canvas_id,
                "github_username": gh or None,
                "name": s.name,
                "email": s.email,
                "excluded": s.excluded,
            },
            pk="canvas_id",
            replace=True,
        )
    return len(students)


def update_student_github(canvas_id: int, github_username: str) -> None:
    """Set the github_username for a student."""
    sdb = get_db()
    sdb.table("students").update(  # pyright: ignore[reportUnknownMemberType]
        canvas_id, {"github_username": github_username.lower()}
    )


def load_students(include_excluded: bool = False) -> list[Student]:
    """Load the master student roster."""
    sdb = get_db()
    where = "" if include_excluded else "WHERE excluded = 0"
    rows = sdb.execute(
        f"SELECT canvas_id, github_username, name, email, excluded "
        f"FROM students {where} ORDER BY lower(name)"
    ).fetchall()
    return [
        Student(
            canvas_id=r[0],
            github_username=r[1] or "",
            name=r[2],
            email=r[3],
            excluded=bool(r[4]),
        )
        for r in rows
    ]


def students_exist() -> bool:
    try:
        sdb = get_db()
        return sdb.table("students").count > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GH Assignments (source)
# ---------------------------------------------------------------------------


def save_gh_assignments(assignments: list[GHAssignment]) -> int:
    """Save GitHub assignments from domain models.

    Uses INSERT ... ON CONFLICT DO UPDATE to preserve user-edited columns
    (e.g. submittable_files) that the API doesn't provide.
    """
    if not assignments:
        return 0
    sdb = get_db()
    sql = (
        "INSERT INTO gh_assignments "
        "(slug, gh_id, title, deadline, points_possible, accepted, "
        "submissions_count, passing_count, starter_code_repo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (slug) DO UPDATE SET "
        "gh_id = excluded.gh_id, title = excluded.title, "
        "deadline = excluded.deadline, points_possible = excluded.points_possible, "
        "accepted = excluded.accepted, "
        "submissions_count = excluded.submissions_count, "
        "passing_count = excluded.passing_count, "
        "starter_code_repo = excluded.starter_code_repo"
    )
    for a in assignments:
        sdb.execute(
            sql,
            [
                a.slug,
                a.gh_id,
                a.title,
                a.deadline or None,
                a.points_possible,
                a.accepted,
                a.submissions_count,
                a.passing_count,
                a.starter_code_repo,
            ],
        )
    _commit(sdb)
    return len(assignments)


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


# ---------------------------------------------------------------------------
# Assignments (master)
# ---------------------------------------------------------------------------


def upsert_assignments(assignments: list[Assignment]) -> int:
    """Upsert into the master assignments table."""
    # Clear unique foreign keys that are being reassigned to different slugs,
    # otherwise the UNIQUE constraints on gh_assignment_slug / canvas_assignment_id
    # fire when a new slug claims a value already owned by a different row.
    sdb = get_db()
    gh_map = {a.gh_assignment_slug: a.slug for a in assignments if a.gh_assignment_slug}
    cv_map = {
        a.canvas_assignment_id: a.slug for a in assignments if a.canvas_assignment_id
    }

    tbl = sdb.table("assignments")
    for row in tbl.rows:  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        slug = row["slug"]  # pyright: ignore[reportUnknownMemberType]
        gh_slug = row["gh_assignment_slug"]  # pyright: ignore[reportUnknownMemberType]
        cv_id = row["canvas_assignment_id"]  # pyright: ignore[reportUnknownMemberType]
        # Null out gh_assignment_slug if another slug is claiming it
        if gh_slug and gh_slug in gh_map and gh_map[gh_slug] != slug:
            tbl.update(slug, {"gh_assignment_slug": None})  # pyright: ignore[reportUnknownMemberType]
        # Null out canvas_assignment_id if another slug is claiming it
        if cv_id and cv_id in cv_map and cv_map[cv_id] != slug:
            tbl.update(slug, {"canvas_assignment_id": None})  # pyright: ignore[reportUnknownMemberType]
    _commit(sdb)

    if not assignments:
        return 0
    tbl.insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "slug": a.slug,
                "title": a.title,
                "gh_assignment_slug": a.gh_assignment_slug or None,
                "canvas_assignment_id": a.canvas_assignment_id or None,
                "points_possible": a.points_possible,
                "deadline": a.deadline,
            }
            for a in assignments
        ],
        pk="slug",
        replace=True,
    )
    return len(assignments)


def _parse_datetime(value: object) -> datetime | None:
    """Parse a datetime from SQLite (stored as ISO string) or pass through."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def load_assignments() -> list[Assignment]:
    """Load all master assignments."""
    sdb = get_db()
    rows = sdb.execute(
        "SELECT slug, title, gh_assignment_slug, canvas_assignment_id, "
        "points_possible, deadline FROM assignments ORDER BY slug"
    ).fetchall()
    return [
        Assignment(
            slug=r[0],
            title=r[1],
            gh_assignment_slug=r[2] or "",
            canvas_assignment_id=r[3] or 0,
            points_possible=r[4],
            deadline=_parse_datetime(r[5]),
        )
        for r in rows
    ]


def load_assignment_mappings() -> dict[str, int]:
    """Return {gh_assignment_slug: canvas_assignment_id} for linked assignments."""
    sdb = get_db()
    rows = sdb.execute(
        "SELECT gh_assignment_slug, canvas_assignment_id FROM assignments "
        "WHERE gh_assignment_slug IS NOT NULL AND canvas_assignment_id IS NOT NULL"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# GH Submissions
# ---------------------------------------------------------------------------


def save_gh_submissions(subs: list[GHSubmission]) -> int:
    """Upsert GitHub submissions."""
    if not subs:
        return 0
    now = time.time()
    sdb = get_db()
    sdb.table("gh_submissions").insert_all(  # pyright: ignore[reportUnknownMemberType]
        [
            {
                "github_username": s.github_username,
                "assignment_slug": s.assignment_slug,
                "submitted": s.submitted,
                "late": s.late,
                "lateness_seconds": s.lateness_seconds,
                "repo_name": s.repo_name,
                "commits_after_deadline": s.commits_after_deadline,
                "commit_count": s.commit_count,
                "passing": s.passing,
                "gh_autograder_score": s.gh_autograder_score,
                "last_commit_at": s.last_commit_at,
                "last_commit_sha": s.last_commit_sha,
                "fetched_at": now,
            }
            for s in subs
        ],
        pk=("github_username", "assignment_slug"),
        replace=True,
    )
    return len(subs)


def load_gh_submissions(assignment_slug: str | None = None) -> list[GHSubmission]:
    """Load GitHub submissions."""
    sdb = get_db()
    _cols = (
        "github_username, assignment_slug, submitted, late, "
        "lateness_seconds, repo_name, commits_after_deadline, commit_count, "
        "passing, gh_autograder_score, last_commit_at, last_commit_sha"
    )
    if assignment_slug:
        rows = sdb.execute(
            f"SELECT {_cols} FROM gh_submissions "
            "WHERE assignment_slug = ? ORDER BY github_username",
            [assignment_slug],
        ).fetchall()
    else:
        rows = sdb.execute(
            f"SELECT {_cols} FROM gh_submissions "
            "ORDER BY assignment_slug, github_username"
        ).fetchall()
    return [
        GHSubmission(
            github_username=r[0],
            assignment_slug=r[1],
            submitted=bool(r[2]),
            late=bool(r[3]),
            lateness_seconds=r[4],
            repo_name=r[5],
            commits_after_deadline=r[6],
            commit_count=r[7],
            passing=bool(r[8]),
            gh_autograder_score=r[9],
            last_commit_at=r[10] or "",
            last_commit_sha=r[11] or "",
        )
        for r in rows
    ]


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


def clear_github_data(sdb: sqlite_utils.Database | None = None) -> None:
    """Remove GitHub Classroom source data and stale assignment links."""
    conn = sdb or get_db()
    for table in ("gh_submissions", "gh_assignments", "gh_students"):
        if table in conn.table_names():
            conn.table(table).delete_where()  # pyright: ignore[reportUnknownMemberType]
    if "assignments" in conn.table_names():
        conn.execute("UPDATE assignments SET gh_assignment_slug = NULL")
    _commit(conn)
