"""Tests for shared query datasets."""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime

from cass import db
from cass.db.schema import CanvasAssignment, CanvasStudent, CanvasSubmission


def _seed(db_conn) -> None:
    db.save_canvas_students(
        [
            CanvasStudent(
                canvas_id=100, name="Alice Smith", sortable_name="Smith, Alice"
            ),
            CanvasStudent(canvas_id=200, name="Bob Jones", sortable_name="Jones, Bob"),
        ]
    )
    db.save_canvas_assignments(
        [CanvasAssignment(canvas_id=42, name="HW 01", points_possible=10.0)]
    )
    db.save_canvas_submissions(
        [
            CanvasSubmission(
                canvas_user_id=100,
                canvas_assignment_id=42,
                submitted=True,
                submitted_at=datetime(2026, 1, 15, 12, 0, 0),
                score=9.0,
                workflow_state="graded",
            ),
            CanvasSubmission(
                canvas_user_id=200,
                canvas_assignment_id=42,
                submitted=True,
                late=True,
                lateness_seconds=3600,
                score=7.0,
                workflow_state="graded",
            ),
        ]
    )


class TestSubmissionsDataset:
    def test_columns(self, db_conn):
        _seed(db_conn)
        result = db.sql(db.build_submissions_query())
        assert result.columns == [
            "student",
            "assignment",
            "submitted",
            "submitted_at",
            "late",
            "lateness_seconds",
            "score",
            "workflow_state",
        ]

    def test_default_order_is_assignment_then_student(self, db_conn):
        _seed(db_conn)
        rows = db.sql(db.build_submissions_query()).fetchall()
        assert [r[0] for r in rows] == ["Jones, Bob", "Smith, Alice"]

    def test_where_and_limit(self, db_conn):
        _seed(db_conn)
        rows = db.sql(db.build_submissions_query(where="late = 1", limit=5)).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Jones, Bob"


class TestTableDatasets:
    def test_students_and_assignments_read_canvas_tables(self):
        assert db.TABLE_QUERY_DATASETS == {
            "students": "canvas_students",
            "assignments": "canvas_assignments",
        }
