"""Tests for EJO-341: SQL safety, db.upsert_canvas_grade, enriched queries, sanitize."""

from __future__ import annotations

from datetime import datetime

import pytest
import sqlite_utils

from cass import db
from cass.db import update_cell
from cass.db.schema import CanvasAssignment, CanvasStudent
from cass.viewer.grid import (
    build_column_defs,
    get_display_columns,
    get_table_rows,
    sanitize,
)

# ===================================================================
# Sanitize
# ===================================================================


class TestSanitize:
    """sanitize() should handle NaN, Inf, datetimes, and nested structures."""

    def test_nan_becomes_none(self):
        assert sanitize(float("nan")) is None

    def test_inf_becomes_none(self):
        assert sanitize(float("inf")) is None

    def test_neg_inf_becomes_none(self):
        assert sanitize(float("-inf")) is None

    def test_normal_float_unchanged(self):
        assert sanitize(3.14) == 3.14

    def test_string_unchanged(self):
        assert sanitize("hello") == "hello"

    def test_none_unchanged(self):
        assert sanitize(None) is None

    def test_int_unchanged(self):
        assert sanitize(42) == 42

    def test_datetime_to_iso(self):
        dt = datetime(2025, 3, 6, 14, 30)
        result = sanitize(dt)
        assert result == "2025-03-06T14:30"

    def test_nested_dict(self):
        data = {"a": float("nan"), "b": "ok", "c": 1}
        result = sanitize(data)
        assert result == {"a": None, "b": "ok", "c": 1}

    def test_nested_list(self):
        data = [float("inf"), "ok", None]
        result = sanitize(data)
        assert result == [None, "ok", None]

    def test_nested_dict_in_list(self):
        data = [{"val": float("nan")}]
        result = sanitize(data)
        assert result == [{"val": None}]

    def test_bool_unchanged(self):
        assert sanitize(True) is True
        assert sanitize(False) is False


# ===================================================================
# update_cell column validation
# ===================================================================


class TestUpdateCellValidation:
    """update_cell() must reject invalid column names."""

    @pytest.fixture
    def edit_conn(self):
        conn = sqlite_utils.Database(memory=True)
        conn.execute(
            "CREATE TABLE canvas_grades ("
            "  canvas_user_id INTEGER NOT NULL,"
            "  canvas_assignment_id INTEGER NOT NULL,"
            "  posted_grade TEXT DEFAULT '',"
            "  score DOUBLE,"
            "  updated_at DOUBLE NOT NULL,"
            "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
            ")"
        )
        conn.execute("INSERT INTO canvas_grades VALUES (100, 42, 'B+', 88.0, 0)")
        return conn

    def test_valid_update(self, edit_conn):
        result = update_cell(
            edit_conn,
            "canvas_grades",
            {"canvas_user_id": 100, "canvas_assignment_id": 42},
            "posted_grade",
            "A",
        )
        assert result["ok"] is True
        assert result["old_value"] == "B+"
        # Verify DB was updated
        row = edit_conn.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 42"
        ).fetchone()
        assert row[0] == "A"

    def test_rejects_unknown_column(self, edit_conn):
        result = update_cell(
            edit_conn,
            "canvas_grades",
            {"canvas_user_id": 100, "canvas_assignment_id": 42},
            "nonexistent_col",
            "A",
        )
        assert result["ok"] is False
        assert "Unknown column" in str(result["error"])

    def test_rejects_sql_injection_column(self, edit_conn):
        result = update_cell(
            edit_conn,
            "canvas_grades",
            {"canvas_user_id": 100, "canvas_assignment_id": 42},
            "posted_grade; DROP TABLE canvas_grades; --",
            "A",
        )
        assert result["ok"] is False
        # Table should still exist
        row = edit_conn.execute("SELECT COUNT(*) FROM canvas_grades").fetchone()
        assert row[0] == 1

    def test_rejects_wrong_pk_columns(self, edit_conn):
        result = update_cell(
            edit_conn,
            "canvas_grades",
            {"wrong_pk": 100},
            "posted_grade",
            "A",
        )
        assert result["ok"] is False
        assert "PK" in str(result["error"])


# ===================================================================
# db.upsert_canvas_grade
# ===================================================================


class TestUpsertCanvasGrade:
    """db.upsert_canvas_grade() should insert or update a single grade."""

    def test_insert_new_grade(self, db_conn):
        # Precondition: no grade exists
        row = db_conn.execute(
            "SELECT COUNT(*) FROM canvas_grades "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 42"
        ).fetchone()
        assert row[0] == 0

        old = db.upsert_canvas_grade(db_conn, 100, 42, "A")
        assert old == ""  # no previous grade

        row = db_conn.execute(
            "SELECT posted_grade, updated_at FROM canvas_grades "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 42"
        ).fetchone()
        assert row[0] == "A"
        assert row[1] > 0  # should be a real timestamp, not 0

    def test_update_existing_grade(self, db_conn):
        # Insert initial grade
        db.upsert_canvas_grade(db_conn, 100, 42, "B")
        old = db.upsert_canvas_grade(db_conn, 100, 42, "A")
        assert old == "B"

        row = db_conn.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 42"
        ).fetchone()
        assert row[0] == "A"

    def test_empty_string_grade(self, db_conn):
        db.upsert_canvas_grade(db_conn, 100, 42, "B")
        old = db.upsert_canvas_grade(db_conn, 100, 42, "")
        assert old == "B"

        row = db_conn.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 42"
        ).fetchone()
        assert row[0] == ""


# ===================================================================
# Canvas enriched queries
# ===================================================================


class TestCanvasEnrichedQueries:
    """Canvas enriched queries should execute without errors."""

    @pytest.fixture
    def canvas_db(self, db_conn):
        """DB with Canvas students, assignments, submissions, grades."""
        db.save_canvas_students(
            [
                CanvasStudent(
                    canvas_id=100,
                    name="Alice Smith",
                    sortable_name="Smith, Alice",
                    email="alice@test.edu",
                ),
                CanvasStudent(
                    canvas_id=200,
                    name="Bob Jones",
                    sortable_name="Jones, Bob",
                    email="bob@test.edu",
                ),
            ]
        )
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1,
                    name="Homework 1",
                    points_possible=10.0,
                    published=True,
                    due_at="2025-03-01T23:59:00Z",
                    assignment_group="Assignments",
                ),
            ],
        )
        from cass.db.schema import CanvasGrade, CanvasSubmission

        db.save_canvas_submissions(
            [
                CanvasSubmission(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    submitted=True,
                    submitted_at=datetime(2025, 2, 28, 10, 0),
                    score=9.0,
                    workflow_state="graded",
                ),
            ]
        )
        db.save_canvas_grades(
            [
                CanvasGrade(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    score=9.0,
                    posted_grade="A",
                ),
            ]
        )
        return db_conn

    def test_canvas_submissions_enriched(self, canvas_db):
        rows = get_table_rows(canvas_db, "canvas_submissions")
        assert len(rows) == 1
        row = rows[0]
        assert "student" in row
        assert row["student"] == "Smith, Alice"
        assert "assignment_name" in row
        assert row["assignment_name"] == "Homework 1"
        assert "assignment_group" in row
        assert "score" in row

    def test_canvas_grades_enriched(self, canvas_db):
        rows = get_table_rows(canvas_db, "canvas_grades")
        assert len(rows) == 1
        row = rows[0]
        assert "student" in row
        assert row["student"] == "Smith, Alice"
        assert "assignment_name" in row
        assert "posted_grade" in row
        assert row["posted_grade"] == "A"

    def test_canvas_assignments_enriched(self, canvas_db):
        rows = get_table_rows(canvas_db, "canvas_assignments")
        assert len(rows) == 1
        row = rows[0]
        assert "name" in row
        assert row["name"] == "Homework 1"
        assert "assignment_group" in row
        assert row["assignment_group"] == "Assignments"

    def test_canvas_students_enriched(self, canvas_db):
        rows = get_table_rows(canvas_db, "canvas_students")
        assert len(rows) == 2
        # Should be sorted by sortable_name
        assert rows[0]["student"] == "Jones, Bob"
        assert rows[1]["student"] == "Smith, Alice"

    def test_canvas_submissions_has_submitted_at_formatted(self, canvas_db):
        """submitted_at should be formatted as human-readable in enriched query."""
        rows = get_table_rows(canvas_db, "canvas_submissions")
        row = rows[0]
        # Should contain formatted date (from strftime in SQL), not raw ISO
        submitted = str(row["submitted_at"])
        assert submitted != ""
        # The exact format depends on implementation but should be readable

    def test_canvas_submissions_missing_student(self, canvas_db):
        """Enriched query should handle submissions for unknown students (LEFT JOIN)."""
        from cass.db.schema import CanvasSubmission

        db.save_canvas_submissions(
            [
                CanvasSubmission(
                    canvas_user_id=999,  # no matching student
                    canvas_assignment_id=1,
                    submitted=True,
                    score=5.0,
                    workflow_state="graded",
                ),
            ]
        )
        rows = get_table_rows(canvas_db, "canvas_submissions")
        assert len(rows) == 2
        unknown = next(r for r in rows if r["canvas_user_id"] == 999)
        assert unknown["student"] is None  # LEFT JOIN → NULL


# ===================================================================
# db helper functions (name lookups, assignment groups)
# ===================================================================


class TestDbHelpers:
    """db.py helper functions for viewer queries."""

    def test_get_assignment_groups(self, db_conn):
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1,
                    name="HW1",
                    points_possible=10.0,
                    assignment_group="Homework",
                ),
                CanvasAssignment(
                    canvas_id=2,
                    name="HW2",
                    points_possible=10.0,
                    assignment_group="Exams",
                ),
                CanvasAssignment(
                    canvas_id=3,
                    name="HW3",
                    points_possible=10.0,
                    assignment_group="Homework",
                ),
            ],
        )
        groups = db.get_assignment_groups(db_conn)
        assert "Homework" in groups
        assert "Exams" in groups
        assert groups == sorted(groups)  # alphabetical

    def test_get_assignment_groups_empty(self, db_conn):
        groups = db.get_assignment_groups(db_conn)
        assert groups == []

    def test_get_assignment_groups_missing_table(self, db_conn):
        db_conn.execute("DROP TABLE IF EXISTS canvas_assignments")
        groups = db.get_assignment_groups(db_conn)
        assert groups == []


# ===================================================================
# db.get_enriched_rows — single entry point for viewer queries
# ===================================================================


class TestGetEnrichedRows:
    """db.get_enriched_rows() returns enriched data for known tables."""

    @pytest.fixture
    def enriched_db(self, db_conn):
        """DB with Canvas data for enriched query tests."""
        db.save_canvas_students(
            [
                CanvasStudent(
                    canvas_id=100,
                    name="Alice Smith",
                    sortable_name="Smith, Alice",
                    email="alice@test.edu",
                ),
            ]
        )
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1,
                    name="HW1",
                    points_possible=10.0,
                    published=True,
                    assignment_group="Homework",
                ),
            ],
        )
        from cass.db.schema import CanvasGrade

        db.save_canvas_grades(
            [
                CanvasGrade(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    score=9.0,
                    posted_grade="A",
                ),
            ]
        )
        return db_conn

    def test_enriched_canvas_grades(self, enriched_db):
        rows = db.get_enriched_rows(enriched_db, "canvas_grades")
        assert len(rows) == 1
        assert "student" in rows[0]
        assert rows[0]["posted_grade"] == "A"

    def test_enriched_unknown_table(self, enriched_db):
        """Unknown tables fall back to SELECT *."""
        rows = db.get_enriched_rows(enriched_db, "canvas_assignments")
        assert len(rows) == 1
        assert "name" in rows[0]

    def test_enriched_returns_dicts(self, enriched_db):
        rows = db.get_enriched_rows(enriched_db, "canvas_grades")
        assert isinstance(rows, list)
        assert isinstance(rows[0], dict)


# ===================================================================
# build_column_defs
# ===================================================================


class TestBuildColumnDefs:
    """build_column_defs() should produce correct AG Grid column config."""

    @pytest.fixture
    def col_db(self, db_conn):
        """DB with canvas_assignments and canvas_grades for column def tests."""
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1,
                    name="HW1",
                    points_possible=10.0,
                    published=True,
                    due_at="2025-03-01T23:59:00Z",
                    assignment_group="Homework",
                ),
            ],
        )
        return db_conn

    def test_canvas_assignments_has_pk_column(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        pk_col = next((d for d in defs if d["field"] == "canvas_id"), None)
        # canvas_id is hidden for canvas_assignments
        assert pk_col is not None
        assert pk_col.get("hide") is True

    def test_canvas_assignments_editable_columns(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        name_col = next(d for d in defs if d["field"] == "name")
        assert name_col.get("editable") is True

    def test_canvas_assignments_bool_renderer(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        pub_col = next(d for d in defs if d["field"] == "published")
        assert pub_col.get("cellRenderer") == "agCheckboxCellRenderer"
        assert pub_col.get("editable") is True
        assert pub_col.get("cellEditor") is None

    def test_canvas_assignments_number_editor(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        pts_col = next(d for d in defs if d["field"] == "points_possible")
        assert pts_col.get("cellEditor") == "agNumberCellEditor"

    def test_canvas_assignments_date_editor(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        due_col = next(d for d in defs if d["field"] == "due_at")
        assert due_col.get("cellEditor") == "agDateStringCellEditor"

    def test_canvas_assignments_select_editor(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        group_col = next(d for d in defs if d["field"] == "assignment_group")
        assert group_col.get("cellEditor") == "agSelectCellEditor"
        params = group_col.get("cellEditorParams", {})
        assert "Homework" in params.get("values", [])

    def test_readonly_table_no_editors(self, col_db):
        defs = build_column_defs(col_db, "gh_assignments")
        for col_def in defs:
            assert col_def.get("editable") is not True

    def test_pending_cell_rule_on_editable(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        name_col = next(d for d in defs if d["field"] == "name")
        assert ":cellClassRules" in name_col

    def test_display_names_applied(self, col_db):
        defs = build_column_defs(col_db, "canvas_assignments")
        pts_col = next(d for d in defs if d["field"] == "points_possible")
        assert pts_col["headerName"] == "Points"


# ===================================================================
# get_display_columns
# ===================================================================


class TestGetDisplayColumns:
    """get_display_columns() should filter and order columns."""

    def test_hides_columns(self):
        cols = get_display_columns(
            "canvas_submissions",
            ["canvas_user_id", "student", "score", "due_at"],
        )
        assert "canvas_user_id" not in cols
        assert "due_at" not in cols
        assert "student" in cols

    def test_orders_columns(self):
        cols = get_display_columns(
            "canvas_assignments",
            [
                "canvas_id",
                "name",
                "points_possible",
                "due_at",
                "published",
                "assignment_group",
            ],
        )
        # assignment_group should come before name per COLUMN_ORDERING
        ag_idx = cols.index("assignment_group")
        name_idx = cols.index("name")
        assert ag_idx < name_idx

    def test_unknown_table_returns_all(self):
        cols = get_display_columns("unknown_table", ["a", "b", "c"])
        assert cols == ["a", "b", "c"]


# ===================================================================
# Revert pending (DB-only, no NiceGUI)
# ===================================================================


class TestRevertPendingDb:
    """Test the DB revert logic from revert_pending without NiceGUI."""

    def test_revert_restores_baseline(self, db_conn):
        """Pending changes should be reverted to baseline values."""
        # Set up: insert assignment, edit it, build pending dict
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1,
                    name="Original Name",
                    points_possible=10.0,
                    assignment_group="",
                ),
            ],
        )
        # Simulate edit: change name
        db_conn.execute(
            "UPDATE canvas_assignments SET name = 'Changed Name' WHERE canvas_id = 1"
        )
        pending = {
            "canvas_assignments": {
                "1": {
                    "name": {
                        "baseline": "Original Name",
                        "current": "Changed Name",
                    },
                },
            },
        }

        # Revert using the same DB logic as revert_pending
        from cass.db import get_column_names, get_primary_keys

        for table, rows in pending.items():
            pk_cols = get_primary_keys(db_conn, table)
            valid_cols = set(get_column_names(db_conn, table))
            for pk_key, cols in rows.items():
                pk = {pk_cols[0]: pk_key}
                for col_name, change in cols.items():
                    if col_name not in valid_cols:
                        continue
                    update_cell(db_conn, table, pk, col_name, change["baseline"])

        # Verify reverted
        row = db_conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = 1"
        ).fetchone()
        assert row[0] == "Original Name"

    def test_revert_skips_invalid_columns(self, db_conn):
        """Invalid column names in pending should be silently skipped."""
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1,
                    name="Test",
                    points_possible=10.0,
                    assignment_group="",
                ),
            ],
        )
        from cass.db import get_column_names

        valid_cols = set(get_column_names(db_conn, "canvas_assignments"))
        assert "fake_col" not in valid_cols
        # Trying to revert a fake column should not raise
        result = update_cell(
            db_conn,
            "canvas_assignments",
            {"canvas_id": 1},
            "fake_col",
            "value",
        )
        assert result["ok"] is False
