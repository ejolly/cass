"""Integration tests using real_db derived from a pulled snapshot.

Every DB query used by the CLI or viewer is exercised here against a
realistic dataset to catch SQL errors, JOIN mismatches, and edge cases
(NULL timestamps, etc.).
"""

from __future__ import annotations

__docformat__ = "google"

import math

import pytest

from cass import db
from cass.db import (
    get_column_names,
    get_primary_keys,
    get_tables,
    is_editable,
    update_cell,
)
from cass.viewer.actions import pending_count, track_change
from cass.viewer.grid import (
    build_column_defs,
    build_gradebook_view,
    get_table_rows,
)


def _sample_canvas_assignment_id(real_db) -> int:
    row = real_db.execute(
        "SELECT canvas_id FROM canvas_assignments ORDER BY canvas_id LIMIT 1"
    ).fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# Schema & table structure
# ---------------------------------------------------------------------------


class TestSchema:
    def test_all_tables_present(self, real_db):
        tables = {t["name"] for t in get_tables(real_db)}
        # Viewer excludes meta and shadow tables
        expected = {
            "canvas_students",
            "canvas_assignments",
            "canvas_submissions",
            "canvas_grades",
        }
        assert expected <= tables

    def test_excluded_tables_hidden(self, real_db):
        tables = {t["name"] for t in get_tables(real_db)}
        assert "_canvas_assignments_synced" not in tables
        assert "_canvas_grades_synced" not in tables
        assert "meta" not in tables

    def test_schema_version(self, real_db):
        version = db.get_meta("schema_version", real_db)
        assert version is not None
        assert int(version) >= 16

    def test_course_name(self, real_db):
        course_name = db.get_meta("course_name", real_db)
        assert course_name

    def test_row_counts(self, real_db):
        # These core tables should always have data after a pull
        for table in ("canvas_students", "canvas_assignments", "canvas_submissions"):
            actual = real_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual > 0, f"{table}: expected rows but got 0"


# ---------------------------------------------------------------------------
# Enriched queries (db.py)
# ---------------------------------------------------------------------------


class TestEnrichedQueries:
    """Every ENRICHED_QUERIES entry must execute without error and return
    the expected column set."""

    def test_canvas_submissions_query(self, real_db):
        rows = db.get_enriched_rows(real_db, "canvas_submissions")
        assert len(rows) > 0
        expected_cols = {
            "canvas_user_id",
            "canvas_assignment_id",
            "student",
            "assignment_name",
            "assignment_group",
            "submitted_at",
            "due_at",
            "score",
            "workflow_state",
            "late",
        }
        assert set(rows[0].keys()) == expected_cols

    def test_canvas_students_query(self, real_db):
        rows = db.get_enriched_rows(real_db, "canvas_students")
        assert len(rows) > 0
        assert set(rows[0].keys()) == {"student", "email", "canvas_id"}
        # Should be sorted by sortable_name
        names = [r["student"] for r in rows]
        assert names == sorted(names)

    def test_canvas_assignments_query(self, real_db):
        rows = db.get_enriched_rows(real_db, "canvas_assignments")
        assert len(rows) > 0
        assert "assignment_group" in rows[0]
        assert "canvas_id" in rows[0]

    def test_fallback_select_star(self, real_db):
        """Tables without enriched queries should fall back to SELECT *."""
        rows = db.get_enriched_rows(real_db, "meta")
        assert len(rows) >= 2

    def test_invalid_table_name_rejected(self, real_db):
        with pytest.raises(ValueError, match="Invalid table name"):
            db.get_enriched_rows(real_db, "drop table students; --")


# ---------------------------------------------------------------------------
# Viewer grid introspection
# ---------------------------------------------------------------------------


class TestGridIntrospection:
    def test_get_tables_returns_visible(self, real_db):
        tables = get_tables(real_db)
        names = {t["name"] for t in tables}
        assert "canvas_assignments" in names
        assert "canvas_students" in names
        # Excluded tables should not appear
        assert "_canvas_assignments_synced" not in names
        assert "meta" not in names

    def test_primary_keys(self, real_db):
        assert get_primary_keys(real_db, "canvas_students") == ["canvas_id"]
        pk = get_primary_keys(real_db, "canvas_grades")
        assert set(pk) == {"canvas_user_id", "canvas_assignment_id"}

    def test_column_names(self, real_db):
        cols = get_column_names(real_db, "canvas_students")
        assert "canvas_id" in cols
        assert "name" in cols
        assert "sortable_name" in cols

    def test_editable_tables(self, real_db):
        assert is_editable(real_db, "canvas_assignments")
        assert is_editable(real_db, "canvas_grades")

    def test_readonly_tables(self, real_db):
        assert not is_editable(real_db, "canvas_submissions")


# ---------------------------------------------------------------------------
# get_table_rows (sanitized enriched data)
# ---------------------------------------------------------------------------


class TestGetTableRows:
    @pytest.mark.parametrize("table", list(db.ENRICHED_QUERIES.keys()))
    def test_enriched_table_rows(self, real_db, table):
        rows = get_table_rows(real_db, table)
        assert isinstance(rows, list)

    def test_sanitized_values(self, real_db):
        """NaN/Inf/datetime values should be sanitized for JSON."""
        rows = get_table_rows(real_db, "canvas_assignments")
        for row in rows:
            for val in row.values():
                if isinstance(val, float):
                    assert not math.isnan(val)
                    assert not math.isinf(val)

    def test_meta_table_rows(self, real_db):
        rows = get_table_rows(real_db, "meta")
        keys = {r["key"] for r in rows}
        assert "schema_version" in keys
        assert "course_name" in keys


# ---------------------------------------------------------------------------
# Column definitions (AG Grid)
# ---------------------------------------------------------------------------


class TestColumnDefs:
    @pytest.mark.parametrize(
        "table",
        [
            "canvas_students",
            "canvas_assignments",
            "canvas_submissions",
            "canvas_grades",
        ],
    )
    def test_build_column_defs(self, real_db, table):
        """Column defs should build without error for every table."""
        defs = build_column_defs(real_db, table)
        assert len(defs) > 0
        # Every def should have a field
        for d in defs:
            assert "field" in d

    def test_editable_columns_marked(self, real_db):
        defs = build_column_defs(real_db, "canvas_assignments")
        editable_fields = [d["field"] for d in defs if d.get("editable")]
        assert "name" in editable_fields
        assert "points_possible" in editable_fields
        assert "published" in editable_fields

    def test_pk_columns_not_editable(self, real_db):
        defs = build_column_defs(real_db, "canvas_assignments")
        hidden_pk = [d for d in defs if d["field"] == "canvas_id"]
        assert hidden_pk
        assert hidden_pk[0]["hide"] is True

    def test_readonly_table_no_editable(self, real_db):
        defs = build_column_defs(real_db, "canvas_submissions")
        editable = [d for d in defs if d.get("editable")]
        assert len(editable) == 0

    def test_assignment_group_select_editor(self, real_db):
        defs = build_column_defs(real_db, "canvas_assignments")
        ag_def = next(d for d in defs if d["field"] == "assignment_group")
        assert ag_def["cellEditor"] == "agSelectCellEditor"
        assert "values" in ag_def["cellEditorParams"]


# ---------------------------------------------------------------------------
# Gradebook pivot views
# ---------------------------------------------------------------------------


class TestGradebookView:
    def test_canvas_gradebook_falls_back_to_submission_scores(self, db_conn):
        db_conn.execute(
            "INSERT INTO canvas_students (canvas_id, name, sortable_name, email) "
            "VALUES (100, 'Alice Smith', 'Smith, Alice', 'alice@test.edu')"
        )
        db_conn.execute(
            "INSERT INTO canvas_assignments "
            "(canvas_id, name, points_possible, due_at, published, assignment_group) "
            "VALUES (1, 'Homework 1', 10.0, '', 1, 'Assignments')"
        )
        db_conn.execute(
            "INSERT INTO canvas_submissions "
            "(canvas_user_id, canvas_assignment_id, submitted, submitted_at, late, "
            "lateness_seconds, score, workflow_state, fetched_at) "
            "VALUES (100, 1, 1, NULL, 0, 0, 9.0, 'graded', 0)"
        )

        row_data, _ = build_gradebook_view(db_conn)

        assert row_data == [
            {
                "_student_name": "Smith, Alice",
                "_canvas_user_id": 100,
                "_a1": "9",
            }
        ]

    def test_canvas_gradebook_cli_viewer_parity(self, real_db):
        headers, matrix_rows = db.build_canvas_gradebook_matrix(real_db)
        row_data, col_defs = build_gradebook_view(real_db)

        assignment_headers: list[str] = []
        for col_def in col_defs:
            if "children" in col_def:
                assignment_headers.extend(
                    child["headerName"] for child in col_def["children"]
                )
            elif col_def.get("field", "").startswith("_a"):
                assignment_headers.append(col_def["headerName"])

        assert headers == ["Student", *assignment_headers]
        assert len(matrix_rows) == len(row_data)
        assert matrix_rows[0][0] == row_data[0]["_student_name"]

    def test_canvas_gradebook_builds(self, real_db):
        row_data, col_defs = build_gradebook_view(real_db)
        assert len(row_data) > 0
        assert len(col_defs) > 1  # student col + assignment cols

    def test_canvas_gradebook_has_student_names(self, real_db):
        row_data, _ = build_gradebook_view(real_db)
        for row in row_data:
            assert "_student_name" in row
            assert "_canvas_user_id" in row
            assert row["_student_name"]  # non-empty

    def test_canvas_gradebook_has_grade_cells(self, real_db):
        row_data, _ = build_gradebook_view(real_db)
        # At least some cells should have grade values
        grade_cells = []
        for row in row_data:
            for key, val in row.items():
                if key.startswith("_a") and key != "_canvas_user_id" and val:
                    grade_cells.append(val)
        assert len(grade_cells) > 0

    def test_canvas_gradebook_col_groups(self, real_db):
        _, col_defs = build_gradebook_view(real_db)
        # Should have grouped columns (assignment_group headers)
        group_headers = [d for d in col_defs if "children" in d]
        assert len(group_headers) >= 1


# ---------------------------------------------------------------------------
# Cell updates
# ---------------------------------------------------------------------------


class TestCellUpdate:
    def test_update_single_pk(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        result = update_cell(
            real_db,
            "canvas_assignments",
            {"canvas_id": canvas_id},
            "name",
            "Renamed HW",
        )
        assert result["ok"]
        row = real_db.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [canvas_id],
        ).fetchone()
        assert row is not None
        assert row[0] == "Renamed HW"

    def test_update_invalid_column(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        result = update_cell(
            real_db,
            "canvas_assignments",
            {"canvas_id": canvas_id},
            "nonexistent_col",
            "val",
        )
        assert not result["ok"]
        assert "Unknown column" in str(result["error"])

    def test_update_wrong_pk_columns(self, real_db):
        result = update_cell(
            real_db,
            "canvas_assignments",
            {"wrong_pk": 1},
            "name",
            "val",
        )
        assert not result["ok"]
        assert "Expected PK" in str(result["error"])

    def test_update_invalid_table_name(self, real_db):
        with pytest.raises(ValueError, match="Invalid SQL"):
            update_cell(
                real_db,
                "robert'; DROP TABLE students;--",
                {"id": 1},
                "name",
                "val",
            )


# ---------------------------------------------------------------------------
# Pending change tracking
# ---------------------------------------------------------------------------


class TestPendingChanges:
    def test_track_pushable_change(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        pending = {}
        track_change(
            pending,
            "canvas_assignments",
            {"canvas_id": canvas_id},
            "name",
            "Original",
            "Renamed",
        )
        assert "canvas_assignments" in pending
        assert pending_count(pending) == 1

    def test_track_non_pushable_ignored(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        pending = {}
        track_change(
            pending,
            "canvas_assignments",
            {"canvas_id": canvas_id},
            "assignment_group",
            "Homeworks",
            "Labs",
        )
        assert pending_count(pending) == 0

    def test_revert_removes_pending(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        pending = {}
        pk = {"canvas_id": canvas_id}
        track_change(pending, "canvas_assignments", pk, "name", "Original", "Renamed")
        assert pending_count(pending) == 1
        # Revert back to original
        track_change(pending, "canvas_assignments", pk, "name", "Original", "Original")
        assert pending_count(pending) == 0

    def test_track_assignment_change(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        pending = {}
        track_change(
            pending,
            "canvas_assignments",
            {"canvas_id": canvas_id},
            "name",
            "HW1",
            "Homework 1",
        )
        assert pending_count(pending) == 1
        pk_key = str(canvas_id)
        assert pending["canvas_assignments"][pk_key]["name"]["baseline"] == "HW1"
        assert pending["canvas_assignments"][pk_key]["name"]["current"] == "Homework 1"


# ---------------------------------------------------------------------------
# Synced shadow tables & get_pending_changes
# ---------------------------------------------------------------------------


class TestSyncedShadowTables:
    def test_snapshot_creates_synced_data(self, real_db):
        synced = real_db.execute(
            "SELECT COUNT(*) FROM _canvas_assignments_synced"
        ).fetchone()[0]
        actual = real_db.execute("SELECT COUNT(*) FROM canvas_assignments").fetchone()[
            0
        ]
        assert synced == actual

    def test_no_pending_changes_initially(self, real_db):
        pending = db.get_pending_changes(real_db)
        assert pending == {}

    def test_pending_after_assignment_edit(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        real_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )
        pending = db.get_pending_changes(real_db)
        assert "canvas_assignments" in pending

    def test_mark_synced_assignments(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        real_db.execute(
            "UPDATE canvas_assignments SET name = 'New Name' WHERE canvas_id = ?",
            [canvas_id],
        )
        assert db.get_pending_changes(real_db) != {}
        db.mark_synced_assignments(real_db, [canvas_id])
        assert db.get_pending_changes(real_db) == {}

    def test_snapshot_resets_pending(self, real_db):
        canvas_id = _sample_canvas_assignment_id(real_db)
        real_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = ?",
            [canvas_id],
        )
        assert db.get_pending_changes(real_db) != {}
        db.snapshot_canvas_synced(real_db)
        assert db.get_pending_changes(real_db) == {}


# ---------------------------------------------------------------------------
# upsert_canvas_grade
# ---------------------------------------------------------------------------


class TestUpsertCanvasGrade:
    def test_insert_new_grade(self, real_db):
        # Use a user/assignment combo that doesn't exist
        old = db.upsert_canvas_grade(real_db, 9999, 9999, "5/5")
        assert old == ""
        row = real_db.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = 9999 AND canvas_assignment_id = 9999"
        ).fetchone()
        assert row[0] == "5/5"


# ---------------------------------------------------------------------------
# Assignment groups
# ---------------------------------------------------------------------------


class TestAssignmentGroups:
    def test_get_assignment_groups(self, real_db):
        groups = db.get_assignment_groups(real_db)
        assert len(groups) > 0
        assert groups == sorted(groups)


# ---------------------------------------------------------------------------
# Edge cases in real data
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_null_due_at_handled(self, real_db):
        rows = db.get_enriched_rows(real_db, "canvas_assignments")
        assert len(rows) > 0

    def test_null_submitted_at_handled(self, real_db):
        rows = db.get_enriched_rows(real_db, "canvas_submissions")
        assert len(rows) > 0
