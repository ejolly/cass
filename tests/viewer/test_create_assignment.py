"""Tests for the Create Assignment modal and its DB backend."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

import msgspec
import pytest
import sqlite_utils

from cass.actions.assignments import push_new_assignment, validate_assignment_fields
from cass.apis.canvas.schema import CanvasAssignmentGroup, CanvasAssignmentResponse
from cass.db import (
    create_local_assignment,
    get_pending_changes,
    init_schema,
    replace_local_id,
    update_cell,
    upsert_canvas_grade,
)


@pytest.fixture
def ca_conn() -> sqlite_utils.Database:
    """In-memory database with two assignments and two students."""
    conn = sqlite_utils.Database(memory=True)
    init_schema(conn)
    conn.execute(
        "INSERT INTO canvas_assignments "
        "(canvas_id, name, points_possible, published, assignment_group) VALUES "
        "(101, 'Homework 1', 10.0, true, 'Assignments'),"
        "(102, 'Homework 2', 20.0, true, 'Assignments')"
    )
    conn["canvas_students"].insert_all(
        {"canvas_id": uid, "name": name, "sortable_name": name}
        for uid, name in ((1, "Ada"), (2, "Bo"))
    )
    return conn


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
        assert not row[2]  # default unpublished
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
        assert row[3]  # published
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
        assert not row[1]
        assert row[2] == ""

    def test_empty_table(self):
        conn = sqlite_utils.Database(memory=True)
        conn.execute(
            "CREATE TABLE canvas_assignments ("
            "  canvas_id INTEGER PRIMARY KEY,"
            "  name TEXT NOT NULL,"
            "  points_possible DOUBLE NOT NULL DEFAULT 0,"
            "  due_at TEXT,"
            "  published BOOLEAN NOT NULL DEFAULT false,"
            "  assignment_group TEXT NOT NULL DEFAULT '',"
            "  post_manually BOOLEAN NOT NULL DEFAULT false"
            ")"
        )
        new_id = create_local_assignment(conn, name="First")
        assert new_id == -1


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


def _make_canvas_assignment(canvas_id: int, name: str) -> CanvasAssignmentResponse:
    """Build a CanvasAssignmentResponse for mock return."""
    return msgspec.convert(
        {"id": canvas_id, "name": name, "course_id": 1},
        CanvasAssignmentResponse,
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

    def test_edit_after_create_is_pending(self, ca_conn):
        local_id = create_local_assignment(ca_conn, name="Quiz 3")
        mock_client = MagicMock()
        mock_client.create_assignment.return_value = _make_canvas_assignment(
            500, "Quiz 3"
        )
        push_new_assignment(ca_conn, local_id, mock_client)
        assert get_pending_changes(ca_conn) == {}

        update_cell(
            ca_conn, "canvas_assignments", {"canvas_id": 500}, "name", "Quiz 3b"
        )
        assert get_pending_changes(ca_conn)["canvas_assignments"]["500"] == {
            "name": {"baseline": "Quiz 3", "current": "Quiz 3b"}
        }

    @staticmethod
    def create(conn, local_id: int) -> dict[str, object]:
        client = MagicMock()
        client.create_assignment.return_value = _make_canvas_assignment(500, "Quiz 3")
        return push_new_assignment(conn, local_id, client)

    @staticmethod
    def baselines(conn) -> list[tuple]:
        return conn.execute(
            "SELECT canvas_user_id, canvas_assignment_id, posted_grade "
            "FROM _canvas_grades_synced ORDER BY 2, 1"
        ).fetchall()

    def test_grade_typed_after_create_has_blank_baseline(self, ca_conn):
        assert self.create(ca_conn, create_local_assignment(ca_conn, name="Quiz 3"))[
            "ok"
        ]
        assert self.baselines(ca_conn) == [(1, 500, ""), (2, 500, "")]
        assert get_pending_changes(ca_conn) == {}
        assert ca_conn["canvas_grades"].count == 0

        upsert_canvas_grade(ca_conn, 1, 500, "9")
        (change,) = get_pending_changes(ca_conn)["canvas_grades"].values()
        assert change["posted_grade"] == {"baseline": "", "current": "9"}

    def test_grade_typed_before_create_stays_pending(self, ca_conn):
        local_id = create_local_assignment(ca_conn, name="Quiz 3")
        upsert_canvas_grade(ca_conn, 1, local_id, "9")
        assert self.create(ca_conn, local_id)["ok"]
        assert get_pending_changes(ca_conn)["canvas_grades"] == {
            '{"canvas_assignment_id": 500, "canvas_user_id": 1}': {
                "posted_grade": {"baseline": "", "current": "9"}
            }
        }

    def test_existing_baseline_is_kept(self, ca_conn):
        ca_conn["_canvas_grades_synced"].insert(
            {"canvas_user_id": 1, "canvas_assignment_id": 500, "posted_grade": "7"}
        )
        self.create(ca_conn, create_local_assignment(ca_conn, name="Quiz 3"))
        assert self.baselines(ca_conn) == [(1, 500, "7"), (2, 500, "")]

    def test_failed_id_change_rolls_back(self, ca_conn):
        local_id = create_local_assignment(ca_conn, name="Quiz 3")
        upsert_canvas_grade(ca_conn, 1, local_id, "9")
        ca_conn.execute(
            "CREATE TRIGGER fail BEFORE INSERT ON _canvas_grades_synced "
            "BEGIN SELECT RAISE(ABORT, 'no baselines'); END"
        )
        result = self.create(ca_conn, local_id)
        assert (result["ok"], result["error"]) == (False, "no baselines")
        ids = [row["canvas_id"] for row in ca_conn["canvas_assignments"].rows]
        assert sorted(ids) == [local_id, 101, 102]
        assert [r["canvas_assignment_id"] for r in ca_conn["canvas_grades"].rows] == [
            local_id
        ]

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
