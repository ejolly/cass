"""Tests for cass.viewer — NiceGUI viewer backend logic."""

import json

import duckdb
import pytest

from cass.viewer.nicegui_app import (
    get_tables,
    is_editable,
    pending_count,
    track_change,
)


@pytest.fixture
def viewer_conn():
    """In-memory DuckDB with test tables (including one without a PK)."""
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE students ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  email TEXT,"
        "  excluded BOOLEAN DEFAULT false"
        ")"
    )
    conn.execute(
        "CREATE TABLE assignments ("
        "  slug TEXT PRIMARY KEY,"
        "  title TEXT,"
        "  points_possible DOUBLE"
        ")"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE logs (message TEXT, ts DOUBLE)")
    conn.execute(
        "INSERT INTO students VALUES (100, 'Alice Smith', 'alice@test.edu', false)"
    )
    conn.execute("INSERT INTO students VALUES (200, 'Bob Jones', 'bob@test.edu', true)")
    conn.execute("INSERT INTO assignments VALUES ('hw-01', 'Homework 1', 10.0)")
    conn.execute(
        "CREATE TABLE canvas_assignments ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  points_possible DOUBLE,"
        "  due_at TEXT,"
        "  published BOOLEAN DEFAULT true"
        ")"
    )
    conn.execute(
        "CREATE TABLE canvas_students ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  email TEXT"
        ")"
    )
    yield conn
    conn.close()


# --- Unit tests ---


def testget_tables_excludes_meta(viewer_conn):
    tables = get_tables(viewer_conn)
    names = [t["name"] for t in tables]
    assert "meta" not in names
    assert "students" in names
    assert "assignments" in names
    assert "logs" in names


def testget_tables_types(viewer_conn):
    tables = get_tables(viewer_conn)
    by_name = {t["name"]: t["type"] for t in tables}
    assert by_name["students"] == "table"
    assert by_name["logs"] == "table"


def test_editable_table(viewer_conn):
    """Only canvas tables (not submissions) are editable."""
    assert is_editable(viewer_conn, "canvas_assignments") is True
    assert is_editable(viewer_conn, "canvas_students") is True
    assert is_editable(viewer_conn, "students") is False
    assert is_editable(viewer_conn, "assignments") is False


def test_no_pk_not_editable(viewer_conn):
    """Tables without a primary key are not editable."""
    assert is_editable(viewer_conn, "logs") is False


# --- Grade editing and change tracking ---


def test_canvas_grades_editable(viewer_conn):
    """canvas_grades table should be editable (not in _READ_ONLY_TABLES)."""
    viewer_conn.execute(
        "CREATE TABLE IF NOT EXISTS canvas_grades ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  score DOUBLE,"
        "  posted_grade TEXT NOT NULL DEFAULT '',"
        "  updated_at DOUBLE NOT NULL,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    assert is_editable(viewer_conn, "canvas_grades") is True


def test_canvas_submissions_readonly(viewer_conn):
    """canvas_submissions should remain read-only."""
    viewer_conn.execute(
        "CREATE TABLE IF NOT EXISTS canvas_submissions ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  submitted BOOLEAN DEFAULT false,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    assert is_editable(viewer_conn, "canvas_submissions") is False


def testtrack_change_grade():
    """Track changes for canvas_grades (pushable column: posted_grade)."""
    pending: dict = {}
    pk = {"canvas_user_id": 100, "canvas_assignment_id": 42}
    track_change(pending, "canvas_grades", pk, "posted_grade", "8", "9")

    assert pending_count(pending) == 1
    assert "canvas_grades" in pending
    pk_key = json.dumps(pk, sort_keys=True)
    assert pk_key in pending["canvas_grades"]
    assert pending["canvas_grades"][pk_key]["posted_grade"]["current"] == "9"


def testtrack_change_grade_revert():
    """Reverting a grade change to baseline removes it from pending."""
    pending: dict = {}
    pk = {"canvas_user_id": 100, "canvas_assignment_id": 42}
    track_change(pending, "canvas_grades", pk, "posted_grade", "8", "9")
    assert pending_count(pending) == 1

    # Revert back to baseline
    track_change(pending, "canvas_grades", pk, "posted_grade", "8", "8")
    assert pending_count(pending) == 0
    assert "canvas_grades" not in pending


def testtrack_change_ignores_non_pushable():
    """Changes to non-pushable columns (like score) are not tracked."""
    pending: dict = {}
    pk = {"canvas_user_id": 100, "canvas_assignment_id": 42}
    track_change(pending, "canvas_grades", pk, "score", 8.0, 9.0)
    assert pending_count(pending) == 0
