"""DuckDB database for cass — per-project, self-contained.

Schema v6: source-specific tables (gh_*, canvas_*) with proper keys,
master tables (students, assignments) as unified joins, and separate
grade tables for GH display and Canvas push.
"""

from __future__ import annotations

__docformat__ = "google"

import time
from collections.abc import Callable

import duckdb

from .config import get_config
from .models import (
    Assignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
    GHGrade,
    GHSubmission,
    GHStudentInfo,
    Student,
)

DB_FILENAME = "cass.duckdb"
_SCHEMA_VERSION = 7

_conn: duckdb.DuckDBPyConnection | None = None


def db_path() -> str:
    return str(get_config().root / DB_FILENAME)


def get_db() -> duckdb.DuckDBPyConnection:
    """Return the shared DuckDB connection, creating it on first call."""
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
            "gh_grades",
            "canvas_grades",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        for view in ("v_submissions", "v_grades"):
            conn.execute(f"DROP VIEW IF EXISTS {view}")

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        [str(_SCHEMA_VERSION)],
    )

    # --- Source tables ---

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gh_students (
            github_username TEXT PRIMARY KEY,
            github_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canvas_students (
            canvas_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sortable_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            login_id TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gh_assignments (
            slug TEXT PRIMARY KEY,
            gh_id INTEGER NOT NULL UNIQUE,
            title TEXT NOT NULL,
            deadline TIMESTAMPTZ,
            points_possible DOUBLE NOT NULL DEFAULT 1.0,
            accepted INTEGER NOT NULL DEFAULT 0,
            submissions_count INTEGER NOT NULL DEFAULT 0,
            passing_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canvas_assignments (
            canvas_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            points_possible DOUBLE NOT NULL DEFAULT 0,
            due_at TIMESTAMPTZ,
            published BOOLEAN NOT NULL DEFAULT false
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gh_submissions (
            github_username TEXT NOT NULL,
            assignment_slug TEXT NOT NULL,
            submitted BOOLEAN NOT NULL DEFAULT false,
            late BOOLEAN NOT NULL DEFAULT false,
            lateness_seconds INTEGER NOT NULL DEFAULT 0,
            repo_name TEXT NOT NULL DEFAULT '',
            commits_after_deadline INTEGER NOT NULL DEFAULT 0,
            commit_count INTEGER NOT NULL DEFAULT 0,
            passing BOOLEAN NOT NULL DEFAULT false,
            gh_autograder_score TEXT NOT NULL DEFAULT '',
            fetched_at DOUBLE NOT NULL,
            PRIMARY KEY (github_username, assignment_slug)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canvas_submissions (
            canvas_user_id INTEGER NOT NULL,
            canvas_assignment_id INTEGER NOT NULL,
            submitted BOOLEAN NOT NULL DEFAULT false,
            submitted_at TIMESTAMPTZ,
            late BOOLEAN NOT NULL DEFAULT false,
            lateness_seconds INTEGER NOT NULL DEFAULT 0,
            score DOUBLE,
            workflow_state TEXT NOT NULL DEFAULT '',
            fetched_at DOUBLE NOT NULL,
            PRIMARY KEY (canvas_user_id, canvas_assignment_id)
        )
    """)

    # --- Master tables ---

    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            canvas_id INTEGER PRIMARY KEY,
            github_username TEXT UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            excluded BOOLEAN NOT NULL DEFAULT false
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            gh_assignment_slug TEXT UNIQUE,
            canvas_assignment_id INTEGER UNIQUE,
            points_possible DOUBLE NOT NULL DEFAULT 0,
            deadline TIMESTAMPTZ
        )
    """)

    # --- Grade tables ---

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gh_grades (
            github_username TEXT NOT NULL,
            assignment_slug TEXT NOT NULL,
            grade TEXT NOT NULL,
            numeric_score DOUBLE,
            source TEXT NOT NULL DEFAULT 'auto',
            updated_at DOUBLE NOT NULL,
            PRIMARY KEY (github_username, assignment_slug)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canvas_grades (
            canvas_user_id INTEGER NOT NULL,
            canvas_assignment_id INTEGER NOT NULL,
            score DOUBLE,
            posted_grade TEXT NOT NULL DEFAULT '',
            updated_at DOUBLE NOT NULL,
            PRIMARY KEY (canvas_user_id, canvas_assignment_id)
        )
    """)


# ---------------------------------------------------------------------------
# GH Students (source)
# ---------------------------------------------------------------------------


def save_gh_students(students: list[GHStudentInfo]) -> int:
    """Upsert GitHub students into the source table."""
    conn = get_db()
    if not students:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO gh_students (github_username, github_id, name, email) "
        "VALUES (?, ?, ?, ?)",
        [
            (s.login.lower(), int(s.id) if s.id else 0, s.name, s.email)
            for s in students
        ],
    )
    return len(students)


def load_gh_students() -> list[GHStudentInfo]:
    """Load all GitHub students."""
    conn = get_db()
    rows = conn.execute(
        "SELECT github_username, github_id, name, email FROM gh_students "
        "ORDER BY github_username"
    ).fetchall()
    return [
        GHStudentInfo(login=r[0], id=str(r[1]), name=r[2], email=r[3]) for r in rows
    ]


# ---------------------------------------------------------------------------
# Canvas Students (source)
# ---------------------------------------------------------------------------


def save_canvas_students(students: list[CanvasStudent]) -> int:
    """Upsert Canvas students into the source table."""
    conn = get_db()
    if not students:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO canvas_students "
        "(canvas_id, name, sortable_name, email, login_id) VALUES (?, ?, ?, ?, ?)",
        [(s.id, s.name, s.sortable_name, s.email, s.login_id) for s in students],
    )
    return len(students)


def load_canvas_students() -> list[CanvasStudent]:
    """Load all Canvas students."""
    conn = get_db()
    rows = conn.execute(
        "SELECT canvas_id, name, sortable_name, email, login_id "
        "FROM canvas_students ORDER BY name"
    ).fetchall()
    return [
        CanvasStudent(id=r[0], name=r[1], sortable_name=r[2], email=r[3], login_id=r[4])
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Students (master)
# ---------------------------------------------------------------------------


def upsert_students(students: list[Student]) -> int:
    """Upsert into the master students table, preserving existing github_username mappings."""
    conn = get_db()
    if not students:
        return 0
    for s in students:
        existing = conn.execute(
            "SELECT github_username FROM students WHERE canvas_id = ?",
            [s.canvas_id],
        ).fetchone()
        gh = s.github_username
        if existing and existing[0] and not gh:
            gh = existing[0]  # preserve existing mapping
        conn.execute(
            "INSERT INTO students (canvas_id, github_username, name, email, excluded) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (canvas_id) DO UPDATE SET "
            "github_username = EXCLUDED.github_username, "
            "name = EXCLUDED.name, email = EXCLUDED.email, "
            "excluded = EXCLUDED.excluded",
            [s.canvas_id, gh or None, s.name, s.email, s.excluded],
        )
    return len(students)


def update_student_github(canvas_id: int, github_username: str) -> None:
    """Set the github_username for a student."""
    conn = get_db()
    conn.execute(
        "UPDATE students SET github_username = ? WHERE canvas_id = ?",
        [github_username.lower(), canvas_id],
    )


def load_students(include_excluded: bool = False) -> list[Student]:
    """Load the master student roster."""
    conn = get_db()
    where = "" if include_excluded else "WHERE excluded = false"
    rows = conn.execute(
        f"SELECT canvas_id, github_username, name, email, excluded "
        f"FROM students {where} ORDER BY lower(name)"
    ).fetchall()
    return [
        Student(
            canvas_id=r[0],
            github_username=r[1] or "",
            name=r[2],
            email=r[3],
            excluded=r[4],
        )
        for r in rows
    ]


def students_exist() -> bool:
    try:
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) FROM students").fetchone()
        return row is not None and row[0] > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GH Assignments (source)
# ---------------------------------------------------------------------------


def save_gh_assignments(assignments: list) -> int:
    """Save GitHub assignments from GHAssignment API types."""
    conn = get_db()
    if not assignments:
        return 0
    from datetime import datetime

    rows = []
    for a in assignments:
        deadline = None
        if a.deadline:
            try:
                deadline = datetime.fromisoformat(a.deadline.replace("Z", "+00:00"))
            except ValueError:
                pass
        rows.append(
            (
                a.slug,
                a.id,
                a.title,
                deadline,
                1.0,
                a.accepted,
                getattr(a, "submissions", 0),
                getattr(a, "passing", 0),
            )
        )
    for row in rows:
        conn.execute(
            "INSERT INTO gh_assignments "
            "(slug, gh_id, title, deadline, points_possible, accepted, "
            "submissions_count, passing_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (slug) DO UPDATE SET "
            "gh_id = EXCLUDED.gh_id, title = EXCLUDED.title, "
            "deadline = EXCLUDED.deadline, points_possible = EXCLUDED.points_possible, "
            "accepted = EXCLUDED.accepted, submissions_count = EXCLUDED.submissions_count, "
            "passing_count = EXCLUDED.passing_count",
            row,
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Canvas Assignments (source)
# ---------------------------------------------------------------------------


def save_canvas_assignments(
    assignments: list,
    slugify_fn: Callable[[str], str] | None = None,
) -> int:
    """Save Canvas assignments from CanvasAssignment API types."""
    conn = get_db()
    if not assignments:
        return 0
    from datetime import datetime

    if slugify_fn is None:
        from .canvas import _slugify

        slugify_fn = _slugify

    rows = []
    for a in assignments:
        due_at = None
        if a.due_at:
            try:
                due_at = datetime.fromisoformat(a.due_at.replace("Z", "+00:00"))
            except ValueError:
                pass
        rows.append(
            (
                a.id,
                a.name,
                slugify_fn(a.name),
                a.points_possible,
                due_at,
                a.published,
            )
        )
    conn.executemany(
        "INSERT OR REPLACE INTO canvas_assignments "
        "(canvas_id, name, slug, points_possible, due_at, published) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Assignments (master)
# ---------------------------------------------------------------------------


def upsert_assignments(assignments: list[Assignment]) -> int:
    """Upsert into the master assignments table."""
    conn = get_db()
    if not assignments:
        return 0
    for a in assignments:
        conn.execute(
            "INSERT INTO assignments "
            "(slug, title, gh_assignment_slug, canvas_assignment_id, "
            "points_possible, deadline) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (slug) DO UPDATE SET "
            "title = EXCLUDED.title, "
            "gh_assignment_slug = EXCLUDED.gh_assignment_slug, "
            "canvas_assignment_id = EXCLUDED.canvas_assignment_id, "
            "points_possible = EXCLUDED.points_possible, "
            "deadline = EXCLUDED.deadline",
            [
                a.slug,
                a.title,
                a.gh_assignment_slug or None,
                a.canvas_assignment_id or None,
                a.points_possible,
                a.deadline,
            ],
        )
    return len(assignments)


def load_assignments() -> list[Assignment]:
    """Load all master assignments."""
    conn = get_db()
    rows = conn.execute(
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
            deadline=r[5],
        )
        for r in rows
    ]


def load_assignment_mappings() -> dict[str, int]:
    """Return {gh_assignment_slug: canvas_assignment_id} for linked assignments."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gh_assignment_slug, canvas_assignment_id FROM assignments "
        "WHERE gh_assignment_slug IS NOT NULL AND canvas_assignment_id IS NOT NULL"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# GH Submissions
# ---------------------------------------------------------------------------


def save_gh_submissions(subs: list[GHSubmission]) -> int:
    """Upsert GitHub submissions."""
    conn = get_db()
    now = time.time()
    if not subs:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO gh_submissions "
        "(github_username, assignment_slug, submitted, late, lateness_seconds, "
        "repo_name, commits_after_deadline, commit_count, passing, "
        "gh_autograder_score, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                s.github_username,
                s.assignment_slug,
                s.submitted,
                s.late,
                s.lateness_seconds,
                s.repo_name,
                s.commits_after_deadline,
                s.commit_count,
                s.passing,
                s.gh_autograder_score,
                now,
            )
            for s in subs
        ],
    )
    return len(subs)


def load_gh_submissions(assignment_slug: str | None = None) -> list[GHSubmission]:
    """Load GitHub submissions."""
    conn = get_db()
    if assignment_slug:
        rows = conn.execute(
            "SELECT github_username, assignment_slug, submitted, late, "
            "lateness_seconds, repo_name, commits_after_deadline, commit_count, "
            "passing, gh_autograder_score FROM gh_submissions "
            "WHERE assignment_slug = ? ORDER BY github_username",
            [assignment_slug],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT github_username, assignment_slug, submitted, late, "
            "lateness_seconds, repo_name, commits_after_deadline, commit_count, "
            "passing, gh_autograder_score FROM gh_submissions "
            "ORDER BY assignment_slug, github_username"
        ).fetchall()
    return [
        GHSubmission(
            github_username=r[0],
            assignment_slug=r[1],
            submitted=r[2],
            late=r[3],
            lateness_seconds=r[4],
            repo_name=r[5],
            commits_after_deadline=r[6],
            commit_count=r[7],
            passing=r[8],
            gh_autograder_score=r[9],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Canvas Submissions
# ---------------------------------------------------------------------------


def save_canvas_submissions(subs: list[CanvasSubmission]) -> int:
    """Upsert Canvas submissions."""
    conn = get_db()
    now = time.time()
    if not subs:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO canvas_submissions "
        "(canvas_user_id, canvas_assignment_id, submitted, submitted_at, "
        "late, lateness_seconds, score, workflow_state, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                s.canvas_user_id,
                s.canvas_assignment_id,
                s.submitted,
                s.submitted_at,
                s.late,
                s.lateness_seconds,
                s.score,
                s.workflow_state,
                now,
            )
            for s in subs
        ],
    )
    return len(subs)


# ---------------------------------------------------------------------------
# GH Grades
# ---------------------------------------------------------------------------


def save_gh_grades(grades: list[GHGrade]) -> int:
    """Upsert GitHub grades."""
    conn = get_db()
    now = time.time()
    if not grades:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO gh_grades "
        "(github_username, assignment_slug, grade, numeric_score, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                g.github_username,
                g.assignment_slug,
                g.grade,
                g.numeric_score,
                g.source,
                now,
            )
            for g in grades
        ],
    )
    return len(grades)


def load_gh_grades(assignment_slug: str | None = None) -> list[GHGrade]:
    """Load GitHub grades."""
    conn = get_db()
    if assignment_slug:
        rows = conn.execute(
            "SELECT github_username, assignment_slug, grade, numeric_score, source "
            "FROM gh_grades WHERE assignment_slug = ? ORDER BY github_username",
            [assignment_slug],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT github_username, assignment_slug, grade, numeric_score, source "
            "FROM gh_grades ORDER BY assignment_slug, github_username"
        ).fetchall()
    return [
        GHGrade(
            github_username=r[0],
            assignment_slug=r[1],
            grade=r[2],
            numeric_score=r[3],
            source=r[4],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Canvas Grades
# ---------------------------------------------------------------------------


def save_canvas_grades(grades: list[CanvasGrade]) -> int:
    """Upsert Canvas grades."""
    conn = get_db()
    now = time.time()
    if not grades:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO canvas_grades "
        "(canvas_user_id, canvas_assignment_id, score, posted_grade, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (g.canvas_user_id, g.canvas_assignment_id, g.score, g.posted_grade, now)
            for g in grades
        ],
    )
    return len(grades)


def load_canvas_grades(canvas_assignment_id: int | None = None) -> list[CanvasGrade]:
    """Load Canvas grades."""
    conn = get_db()
    if canvas_assignment_id:
        rows = conn.execute(
            "SELECT canvas_user_id, canvas_assignment_id, score, posted_grade "
            "FROM canvas_grades WHERE canvas_assignment_id = ? ORDER BY canvas_user_id",
            [canvas_assignment_id],
        ).fetchall()
    else:
        rows = conn.execute(
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


# ---------------------------------------------------------------------------
# Raw query (for `cass query`)
# ---------------------------------------------------------------------------


def run_query(sql: str) -> duckdb.DuckDBPyRelation:
    conn = get_db()
    return conn.sql(sql)
