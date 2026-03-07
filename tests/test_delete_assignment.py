"""Tests for the Delete Assignment modal and its DB backend."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Generator
from unittest.mock import MagicMock

import duckdb
import pytest

from cass.viewer.delete_assignment_modal import (
    delete_assignment_from_canvas,
    delete_local_assignment,
    list_assignments_for_select,
    purge_pending_for_assignment,
)


@pytest.fixture
def da_conn() -> Generator[duckdb.DuckDBPyConnection]:
    """In-memory DuckDB with canvas_assignments + related tables."""
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE canvas_assignments ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  points_possible DOUBLE NOT NULL DEFAULT 0,"
        "  due_at TIMESTAMPTZ,"
        "  published BOOLEAN NOT NULL DEFAULT false,"
        "  assignment_group TEXT NOT NULL DEFAULT '',"
        "  post_manually BOOLEAN NOT NULL DEFAULT false"
        ")"
    )
    conn.execute(
        "CREATE TABLE canvas_submissions ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  submitted BOOLEAN NOT NULL DEFAULT false,"
        "  submitted_at TEXT,"
        "  late BOOLEAN NOT NULL DEFAULT false,"
        "  lateness_seconds INTEGER NOT NULL DEFAULT 0,"
        "  score DOUBLE,"
        "  workflow_state TEXT NOT NULL DEFAULT '',"
        "  fetched_at DOUBLE NOT NULL,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE canvas_grades ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  score DOUBLE,"
        "  posted_grade TEXT NOT NULL DEFAULT '',"
        "  updated_at DOUBLE NOT NULL,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE _canvas_grades_synced ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  posted_grade TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE _canvas_assignments_synced ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  points_possible DOUBLE,"
        "  due_at TIMESTAMPTZ,"
        "  published BOOLEAN,"
        "  assignment_group TEXT,"
        "  post_manually BOOLEAN"
        ")"
    )

    # Seed data
    conn.execute(
        "INSERT INTO canvas_assignments VALUES "
        "(101, 'Homework 1', 10.0, NULL, true, 'Assignments', false),"
        "(102, 'Homework 2', 20.0, NULL, true, 'Assignments', false),"
        "(103, 'Final Exam', 100.0, NULL, true, 'Exams', false)"
    )
    conn.execute(
        "INSERT INTO canvas_grades VALUES "
        "(1, 101, 9.0, '9', 1000.0),"
        "(2, 101, 8.0, '8', 1000.0),"
        "(1, 102, 18.0, '18', 1000.0)"
    )
    conn.execute(
        "INSERT INTO canvas_submissions VALUES "
        "(1, 101, true, '2026-01-15', false, 0, 9.0, 'graded', 1000.0),"
        "(2, 101, true, '2026-01-16', false, 0, 8.0, 'graded', 1000.0)"
    )
    conn.execute("INSERT INTO _canvas_grades_synced VALUES (1, 101, '9'),(2, 101, '8')")
    conn.execute(
        "INSERT INTO _canvas_assignments_synced "
        "SELECT * FROM canvas_assignments WHERE canvas_id = 101"
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# list_assignments_for_select
# ---------------------------------------------------------------------------


class TestListAssignmentsForSelect:
    def test_returns_id_name_pairs(self, da_conn):
        result = list_assignments_for_select(da_conn)
        assert isinstance(result, dict)
        assert 101 in result
        assert result[101] == "Homework 1"
        assert 103 in result
        assert result[103] == "Final Exam"

    def test_sorted_by_name(self, da_conn):
        result = list_assignments_for_select(da_conn)
        names = list(result.values())
        assert names == sorted(names)

    def test_empty_table(self):
        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE canvas_assignments ("
            "  canvas_id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        assert list_assignments_for_select(conn) == {}
        conn.close()


# ---------------------------------------------------------------------------
# delete_local_assignment
# ---------------------------------------------------------------------------


class TestDeleteLocalAssignment:
    def test_deletes_assignment_row(self, da_conn):
        delete_local_assignment(da_conn, 101)
        row = da_conn.execute(
            "SELECT * FROM canvas_assignments WHERE canvas_id = 101"
        ).fetchone()
        assert row is None

    def test_cascades_to_grades(self, da_conn):
        delete_local_assignment(da_conn, 101)
        grades = da_conn.execute(
            "SELECT * FROM canvas_grades WHERE canvas_assignment_id = 101"
        ).fetchall()
        assert grades == []

    def test_cascades_to_submissions(self, da_conn):
        delete_local_assignment(da_conn, 101)
        subs = da_conn.execute(
            "SELECT * FROM canvas_submissions WHERE canvas_assignment_id = 101"
        ).fetchall()
        assert subs == []

    def test_cascades_to_synced_tables(self, da_conn):
        delete_local_assignment(da_conn, 101)
        synced_grades = da_conn.execute(
            "SELECT * FROM _canvas_grades_synced WHERE canvas_assignment_id = 101"
        ).fetchall()
        synced_assign = da_conn.execute(
            "SELECT * FROM _canvas_assignments_synced WHERE canvas_id = 101"
        ).fetchall()
        assert synced_grades == []
        assert synced_assign == []

    def test_does_not_affect_other_assignments(self, da_conn):
        delete_local_assignment(da_conn, 101)
        # Assignment 102 untouched
        row = da_conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = 102"
        ).fetchone()
        assert row[0] == "Homework 2"
        # Grade for 102 untouched
        grade = da_conn.execute(
            "SELECT * FROM canvas_grades WHERE canvas_assignment_id = 102"
        ).fetchall()
        assert len(grade) == 1

    def test_nonexistent_id_is_noop(self, da_conn):
        count_before = da_conn.execute(
            "SELECT count(*) FROM canvas_assignments"
        ).fetchone()[0]
        delete_local_assignment(da_conn, 9999)
        count_after = da_conn.execute(
            "SELECT count(*) FROM canvas_assignments"
        ).fetchone()[0]
        assert count_before == count_after


# ---------------------------------------------------------------------------
# delete_assignment_from_canvas (mocked client)
# ---------------------------------------------------------------------------


class TestDeleteAssignmentFromCanvas:
    def test_deletes_from_canvas_and_locally(self, da_conn):
        mock_client = MagicMock()
        result = delete_assignment_from_canvas(da_conn, 101, mock_client)
        assert result["ok"] is True
        mock_client.delete_assignment.assert_called_once_with(101)
        # Local row gone
        row = da_conn.execute(
            "SELECT * FROM canvas_assignments WHERE canvas_id = 101"
        ).fetchone()
        assert row is None

    def test_local_only_skips_canvas_call(self, da_conn):
        """Negative IDs (local-only) should not call Canvas API."""
        da_conn.execute(
            "INSERT INTO canvas_assignments VALUES "
            "(-1, 'Local Only', 5.0, NULL, false, '', false)"
        )
        mock_client = MagicMock()
        result = delete_assignment_from_canvas(da_conn, -1, mock_client)
        assert result["ok"] is True
        mock_client.delete_assignment.assert_not_called()
        row = da_conn.execute(
            "SELECT * FROM canvas_assignments WHERE canvas_id = -1"
        ).fetchone()
        assert row is None

    def test_canvas_error_still_deletes_locally(self, da_conn):
        mock_client = MagicMock()
        mock_client.delete_assignment.side_effect = RuntimeError("Canvas 403")
        result = delete_assignment_from_canvas(da_conn, 101, mock_client)
        assert result["ok"] is False
        assert "Canvas 403" in str(result["error"])
        # Local row should still be deleted
        row = da_conn.execute(
            "SELECT * FROM canvas_assignments WHERE canvas_id = 101"
        ).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# purge_pending_for_assignment
# ---------------------------------------------------------------------------


class TestPurgePendingForAssignment:
    def test_removes_assignment_pending(self):
        pending = {
            "canvas_assignments": {
                "101": {"name": {"baseline": "Old", "current": "New"}},
                "102": {"name": {"baseline": "A", "current": "B"}},
            },
        }
        purge_pending_for_assignment(pending, 101)
        assert "101" not in pending.get("canvas_assignments", {})
        assert "102" in pending["canvas_assignments"]

    def test_removes_grade_pending(self):
        import json

        pk_key = json.dumps(
            {"canvas_assignment_id": 101, "canvas_user_id": 1}, sort_keys=True
        )
        other_pk = json.dumps(
            {"canvas_assignment_id": 102, "canvas_user_id": 1}, sort_keys=True
        )
        pending = {
            "canvas_grades": {
                pk_key: {"posted_grade": {"baseline": "8", "current": "9"}},
                other_pk: {"posted_grade": {"baseline": "18", "current": "20"}},
            },
        }
        purge_pending_for_assignment(pending, 101)
        assert pk_key not in pending.get("canvas_grades", {})
        assert other_pk in pending["canvas_grades"]

    def test_cleans_up_empty_tables(self):
        pending = {
            "canvas_assignments": {
                "101": {"name": {"baseline": "X", "current": "Y"}},
            },
        }
        purge_pending_for_assignment(pending, 101)
        assert "canvas_assignments" not in pending

    def test_noop_when_no_pending(self):
        pending: dict = {}
        purge_pending_for_assignment(pending, 101)
        assert pending == {}
