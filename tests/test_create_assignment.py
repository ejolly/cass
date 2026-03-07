"""Tests for the Create Assignment modal and its DB backend."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Generator
from unittest.mock import MagicMock

import duckdb
import msgspec
import pytest

from cass.models.canvas_api import CanvasAssignment, CanvasAssignmentGroup
from cass.viewer.create_assignment_modal import (
    create_local_assignment,
    push_new_assignment,
    replace_local_id,
    validate_assignment_fields,
)


@pytest.fixture
def ca_conn() -> Generator[duckdb.DuckDBPyConnection]:
    """In-memory DuckDB with canvas_assignments table."""
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
        "INSERT INTO canvas_assignments VALUES "
        "(101, 'Homework 1', 10.0, NULL, true, 'Assignments', false),"
        "(102, 'Homework 2', 20.0, NULL, true, 'Assignments', false)"
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidateAssignmentFields:
    def test_valid_minimal(self):
        errors = validate_assignment_fields(name="Quiz 1", points=10.0)
        assert errors == []

    def test_valid_zero_points(self):
        errors = validate_assignment_fields(name="Survey", points=0.0)
        assert errors == []

    def test_empty_name(self):
        errors = validate_assignment_fields(name="", points=10.0)
        assert any("name" in e.lower() for e in errors)

    def test_whitespace_only_name(self):
        errors = validate_assignment_fields(name="   ", points=10.0)
        assert any("name" in e.lower() for e in errors)

    def test_negative_points(self):
        errors = validate_assignment_fields(name="HW", points=-5.0)
        assert any("points" in e.lower() for e in errors)

    def test_none_points_treated_as_zero(self):
        errors = validate_assignment_fields(name="HW", points=None)
        assert errors == []

    def test_multiple_errors(self):
        errors = validate_assignment_fields(name="", points=-1.0)
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# DB function tests
# ---------------------------------------------------------------------------


class TestCreateLocalAssignment:
    def test_creates_assignment_with_negative_id(self, ca_conn):
        new_id = create_local_assignment(
            ca_conn, name="Final Exam", points_possible=100.0
        )
        assert new_id < 0

    def test_inserts_row(self, ca_conn):
        new_id = create_local_assignment(
            ca_conn, name="Final Exam", points_possible=100.0
        )
        row = ca_conn.execute(
            "SELECT name, points_possible, published, assignment_group "
            "FROM canvas_assignments WHERE canvas_id = ?",
            [new_id],
        ).fetchone()
        assert row is not None
        assert row[0] == "Final Exam"
        assert row[1] == 100.0
        assert row[2] is False  # default unpublished
        assert row[3] == ""

    def test_with_all_fields(self, ca_conn):
        new_id = create_local_assignment(
            ca_conn,
            name="Midterm",
            points_possible=50.0,
            due_at="2026-03-15T23:59",
            published=True,
            assignment_group="Exams",
        )
        row = ca_conn.execute(
            "SELECT name, points_possible, due_at, published, assignment_group "
            "FROM canvas_assignments WHERE canvas_id = ?",
            [new_id],
        ).fetchone()
        assert row[0] == "Midterm"
        assert row[1] == 50.0
        assert row[3] is True
        assert row[4] == "Exams"

    def test_sequential_negative_ids(self, ca_conn):
        id1 = create_local_assignment(ca_conn, name="A1", points_possible=10.0)
        id2 = create_local_assignment(ca_conn, name="A2", points_possible=10.0)
        assert id1 < 0
        assert id2 < 0
        assert id2 < id1  # each new one is more negative

    def test_defaults(self, ca_conn):
        new_id = create_local_assignment(ca_conn, name="Simple")
        row = ca_conn.execute(
            "SELECT points_possible, published, assignment_group "
            "FROM canvas_assignments WHERE canvas_id = ?",
            [new_id],
        ).fetchone()
        assert row[0] == 0.0
        assert row[1] is False
        assert row[2] == ""

    def test_empty_table(self):
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
        new_id = create_local_assignment(conn, name="First")
        assert new_id == -1
        conn.close()


# ---------------------------------------------------------------------------
# Replace local ID tests
# ---------------------------------------------------------------------------


class TestReplaceLocalId:
    def test_replaces_negative_id_with_real(self, ca_conn):
        local_id = create_local_assignment(ca_conn, name="New HW")
        assert local_id < 0
        replace_local_id(ca_conn, local_id, 999)
        # Old row gone
        old = ca_conn.execute(
            "SELECT * FROM canvas_assignments WHERE canvas_id = ?", [local_id]
        ).fetchone()
        assert old is None
        # New row present with same data
        new = ca_conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?", [999]
        ).fetchone()
        assert new is not None
        assert new[0] == "New HW"

    def test_preserves_all_fields(self, ca_conn):
        local_id = create_local_assignment(
            ca_conn,
            name="Exam",
            points_possible=50.0,
            published=True,
            assignment_group="Exams",
        )
        replace_local_id(ca_conn, local_id, 777)
        row = ca_conn.execute(
            "SELECT name, points_possible, published, assignment_group "
            "FROM canvas_assignments WHERE canvas_id = ?",
            [777],
        ).fetchone()
        assert row == ("Exam", 50.0, True, "Exams")


# ---------------------------------------------------------------------------
# Push new assignment tests (mocked Canvas client)
# ---------------------------------------------------------------------------


def _make_canvas_assignment(canvas_id: int, name: str) -> CanvasAssignment:
    """Build a CanvasAssignment for mock return."""
    return msgspec.convert(
        {"id": canvas_id, "name": name, "course_id": 1},
        CanvasAssignment,
        strict=False,
    )


class TestPushNewAssignment:
    def test_push_creates_and_replaces_id(self, ca_conn):
        local_id = create_local_assignment(ca_conn, name="Quiz 3", points_possible=25.0)
        mock_client = MagicMock()
        mock_client.create_assignment.return_value = _make_canvas_assignment(
            500, "Quiz 3"
        )
        mock_client.list_assignment_groups.return_value = []

        result = push_new_assignment(ca_conn, local_id, mock_client)

        assert result["ok"] is True
        assert result["canvas_id"] == 500
        mock_client.create_assignment.assert_called_once()
        # Local ID replaced in DB
        old = ca_conn.execute(
            "SELECT * FROM canvas_assignments WHERE canvas_id = ?", [local_id]
        ).fetchone()
        assert old is None
        new = ca_conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?", [500]
        ).fetchone()
        assert new[0] == "Quiz 3"

    def test_push_resolves_group_name_to_id(self, ca_conn):
        local_id = create_local_assignment(
            ca_conn,
            name="HW 5",
            points_possible=10.0,
            assignment_group="Homework",
        )
        mock_client = MagicMock()
        mock_client.create_assignment.return_value = _make_canvas_assignment(
            600, "HW 5"
        )
        mock_client.list_assignment_groups.return_value = [
            msgspec.convert(
                {"id": 42, "name": "Homework"}, CanvasAssignmentGroup, strict=False
            ),
            msgspec.convert(
                {"id": 43, "name": "Exams"}, CanvasAssignmentGroup, strict=False
            ),
        ]

        push_new_assignment(ca_conn, local_id, mock_client)

        call_kwargs = mock_client.create_assignment.call_args
        assert call_kwargs.kwargs.get("assignment_group_id") == 42

    def test_push_error_returns_failure(self, ca_conn):
        local_id = create_local_assignment(ca_conn, name="Bad HW")
        mock_client = MagicMock()
        mock_client.create_assignment.side_effect = RuntimeError("Canvas 403")
        mock_client.list_assignment_groups.return_value = []

        result = push_new_assignment(ca_conn, local_id, mock_client)

        assert result["ok"] is False
        assert "Canvas 403" in str(result["error"])
        # Local row should still exist (not deleted on failure)
        row = ca_conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?", [local_id]
        ).fetchone()
        assert row is not None
