"""Integration tests using populated_db with anonymized real-world data.

Every DB query used by the CLI or viewer is exercised here against a
realistic dataset to catch SQL errors, JOIN mismatches, and edge cases
(NULL timestamps, excluded students, unmatched GH users, etc.).
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
    build_gh_gradebook_view,
    build_gradebook_view,
    get_table_rows,
)

# ---------------------------------------------------------------------------
# Schema & table structure
# ---------------------------------------------------------------------------


class TestSchema:
    def test_all_tables_present(self, populated_db):
        tables = {t["name"] for t in get_tables(populated_db)}
        # Viewer excludes meta, canvas_students, gh_grades, and shadow tables
        expected = {
            "canvas_assignments",
            "canvas_submissions",
            "canvas_grades",
            "gh_students",
            "gh_assignments",
            "gh_submissions",
            "students",
            "assignments",
        }
        assert expected <= tables

    def test_excluded_tables_hidden(self, populated_db):
        tables = {t["name"] for t in get_tables(populated_db)}
        assert "_canvas_assignments_synced" not in tables
        assert "_canvas_grades_synced" not in tables
        assert "meta" not in tables
        assert "canvas_students" not in tables
        assert "gh_grades" not in tables

    def test_schema_version(self, populated_db):
        assert db.get_meta("schema_version", populated_db) == "13"

    def test_course_name(self, populated_db):
        assert (
            db.get_meta("course_name", populated_db)
            == "TEST 101 - Intro to Testing [WI26]"
        )

    def test_row_counts(self, populated_db):
        counts = {
            "canvas_students": 15,
            "gh_students": 18,
            "students": 15,
            "canvas_assignments": 5,
            "gh_assignments": 8,
            "assignments": 13,
            "canvas_grades": 75,
            "canvas_submissions": 75,
            "gh_submissions": 141,
            "gh_grades": 141,
        }
        for table, expected in counts.items():
            actual = populated_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == expected, f"{table}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Enriched queries (db.py)
# ---------------------------------------------------------------------------


class TestEnrichedQueries:
    """Every ENRICHED_QUERIES entry must execute without error and return
    the expected column set."""

    def test_canvas_submissions_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "canvas_submissions")
        assert len(rows) == 75
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

    def test_canvas_students_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "canvas_students")
        assert len(rows) == 15
        assert set(rows[0].keys()) == {"student", "email", "canvas_id"}
        # Should be sorted by sortable_name
        names = [r["student"] for r in rows]
        assert names == sorted(names)

    def test_canvas_assignments_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "canvas_assignments")
        assert len(rows) == 5
        assert "assignment_group" in rows[0]
        assert "canvas_id" in rows[0]

    def test_canvas_grades_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "canvas_grades")
        assert len(rows) == 75
        expected_cols = {
            "canvas_user_id",
            "canvas_assignment_id",
            "student",
            "assignment_name",
            "assignment_group",
            "score",
            "posted_grade",
            "updated_at",
        }
        assert set(rows[0].keys()) == expected_cols

    def test_gh_students_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "gh_students")
        assert len(rows) == 18
        expected_cols = {"excluded", "student", "github_username", "email", "github_id"}
        assert set(rows[0].keys()) == expected_cols
        # Should include both excluded and non-excluded
        excluded = [r for r in rows if r["excluded"]]
        assert len(excluded) >= 2

    def test_gh_students_name_formatting(self, populated_db):
        """Matched students use Canvas sortable_name; unmatched use 'Last, First'."""
        rows = db.get_enriched_rows(populated_db, "gh_students")
        by_username = {r["github_username"]: r for r in rows}
        # Matched student should have Canvas sortable_name format
        matched = by_username["alice-a"]
        assert ", " in str(matched["student"])
        # Unmatched student with a name should get "Last, First" format
        instructor = by_username["instructor"]
        assert instructor["student"] == "User, Instructor"

    def test_gh_assignments_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "gh_assignments")
        assert len(rows) == 8
        # Some have deadlines, some don't
        with_deadline = [r for r in rows if r["deadline"]]
        without_deadline = [r for r in rows if not r["deadline"]]
        assert len(with_deadline) >= 1
        assert len(without_deadline) >= 1

    def test_gh_submissions_query(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "gh_submissions")
        # Should exclude hidden students
        assert len(rows) < 141
        expected_cols = {
            "github_username",
            "assignment_slug",
            "last_commit_at",
            "student",
            "assignment_name",
            "commit_count",
            "commit_url",
            "late",
            "repo_url",
            "last_commit_sha",
        }
        assert set(rows[0].keys()) == expected_cols

    def test_gh_submissions_excludes_hidden(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "gh_submissions")
        usernames = {r["github_username"] for r in rows}
        # excluded students should not appear
        assert "extra-student" not in usernames
        assert "dropped-student" not in usernames

    def test_gh_submissions_has_urls(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "gh_submissions")
        for row in rows:
            if row["last_commit_sha"]:
                assert str(row["commit_url"]).startswith("https://github.com/")
                assert "/commit/" in str(row["commit_url"])
            assert str(row["repo_url"]).startswith("https://github.com/")

    def test_fallback_select_star(self, populated_db):
        """Tables without enriched queries should fall back to SELECT *."""
        rows = db.get_enriched_rows(populated_db, "meta")
        assert len(rows) == 2

    def test_invalid_table_name_rejected(self, populated_db):
        with pytest.raises(ValueError, match="Invalid table name"):
            db.get_enriched_rows(populated_db, "drop table students; --")


# ---------------------------------------------------------------------------
# Viewer grid introspection
# ---------------------------------------------------------------------------


class TestGridIntrospection:
    def test_get_tables_returns_visible(self, populated_db):
        tables = get_tables(populated_db)
        names = {t["name"] for t in tables}
        assert "canvas_assignments" in names
        assert "gh_assignments" in names
        # Excluded tables should not appear
        assert "_canvas_assignments_synced" not in names
        assert "canvas_students" not in names
        assert "meta" not in names

    def test_primary_keys(self, populated_db):
        assert get_primary_keys(populated_db, "canvas_students") == ["canvas_id"]
        pk = get_primary_keys(populated_db, "canvas_grades")
        assert set(pk) == {"canvas_user_id", "canvas_assignment_id"}

    def test_column_names(self, populated_db):
        cols = get_column_names(populated_db, "students")
        assert "canvas_id" in cols
        assert "github_username" in cols
        assert "name" in cols

    def test_editable_tables(self, populated_db):
        assert is_editable(populated_db, "canvas_assignments")
        assert is_editable(populated_db, "canvas_grades")
        assert is_editable(populated_db, "gh_students")

    def test_readonly_tables(self, populated_db):
        assert not is_editable(populated_db, "canvas_submissions")
        assert not is_editable(populated_db, "gh_submissions")
        assert not is_editable(populated_db, "gh_grades")


# ---------------------------------------------------------------------------
# get_table_rows (sanitized enriched data)
# ---------------------------------------------------------------------------


class TestGetTableRows:
    @pytest.mark.parametrize("table", list(db.ENRICHED_QUERIES.keys()))
    def test_enriched_table_rows(self, populated_db, table):
        rows = get_table_rows(populated_db, table)
        assert len(rows) > 0

    def test_sanitized_values(self, populated_db):
        """NaN/Inf/datetime values should be sanitized for JSON."""
        rows = get_table_rows(populated_db, "canvas_assignments")
        for row in rows:
            for val in row.values():
                if isinstance(val, float):
                    assert not math.isnan(val)
                    assert not math.isinf(val)

    def test_meta_table_rows(self, populated_db):
        rows = get_table_rows(populated_db, "meta")
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
            "gh_students",
            "gh_assignments",
            "gh_submissions",
            "students",
            "assignments",
        ],
    )
    def test_build_column_defs(self, populated_db, table):
        """Column defs should build without error for every table."""
        defs = build_column_defs(populated_db, table)
        assert len(defs) > 0
        # Every def should have a field
        for d in defs:
            assert "field" in d

    def test_editable_columns_marked(self, populated_db):
        defs = build_column_defs(populated_db, "canvas_assignments")
        editable_fields = [d["field"] for d in defs if d.get("editable")]
        assert "name" in editable_fields
        assert "points_possible" in editable_fields
        assert "published" in editable_fields

    def test_pk_columns_not_editable(self, populated_db):
        # canvas_assignments has canvas_id hidden; use gh_students which shows PK
        defs = build_column_defs(populated_db, "gh_students")
        pk_defs = [d for d in defs if "(PK)" in d.get("headerName", "")]
        assert len(pk_defs) > 0
        for d in pk_defs:
            assert not d.get("editable")

    def test_readonly_table_no_editable(self, populated_db):
        defs = build_column_defs(populated_db, "canvas_submissions")
        editable = [d for d in defs if d.get("editable")]
        assert len(editable) == 0

    def test_assignment_group_select_editor(self, populated_db):
        defs = build_column_defs(populated_db, "canvas_assignments")
        ag_def = next(d for d in defs if d["field"] == "assignment_group")
        assert ag_def["cellEditor"] == "agSelectCellEditor"
        assert "values" in ag_def["cellEditorParams"]

    def test_link_columns_have_renderer(self, populated_db):
        defs = build_column_defs(populated_db, "gh_submissions")
        repo_def = next(d for d in defs if d["field"] == "repo_url")
        assert ":cellRenderer" in repo_def


# ---------------------------------------------------------------------------
# Gradebook pivot views
# ---------------------------------------------------------------------------


class TestGradebookView:
    def test_canvas_gradebook_builds(self, populated_db):
        row_data, col_defs = build_gradebook_view(populated_db)
        assert len(row_data) == 15  # one per canvas student
        assert len(col_defs) > 1  # student col + assignment cols

    def test_canvas_gradebook_has_student_names(self, populated_db):
        row_data, _ = build_gradebook_view(populated_db)
        for row in row_data:
            assert "_student_name" in row
            assert "_canvas_user_id" in row
            assert row["_student_name"]  # non-empty

    def test_canvas_gradebook_has_grade_cells(self, populated_db):
        row_data, _ = build_gradebook_view(populated_db)
        # At least some cells should have grade values
        grade_cells = []
        for row in row_data:
            for key, val in row.items():
                if key.startswith("_a") and key != "_canvas_user_id" and val:
                    grade_cells.append(val)
        assert len(grade_cells) > 0

    def test_canvas_gradebook_col_groups(self, populated_db):
        _, col_defs = build_gradebook_view(populated_db)
        # Should have grouped columns (assignment_group headers)
        group_headers = [d for d in col_defs if "children" in d]
        # We have Homeworks and Labs groups
        assert len(group_headers) >= 2

    def test_gh_gradebook_builds(self, populated_db):
        row_data, col_defs = build_gh_gradebook_view(populated_db)
        assert len(row_data) > 0
        assert len(col_defs) > 1

    def test_gh_gradebook_excludes_hidden(self, populated_db):
        row_data, _ = build_gh_gradebook_view(populated_db)
        usernames = {r["_github_username"] for r in row_data}
        assert "extra-student" not in usernames
        assert "dropped-student" not in usernames

    def test_gh_gradebook_cells_format(self, populated_db):
        row_data, _ = build_gh_gradebook_view(populated_db)
        # Cells should be "X/Y" format or empty
        for row in row_data:
            for key, val in row.items():
                is_grade_cell = (
                    key.startswith("_a")
                    and key != "_github_username"
                    and key != "_student_name"
                )
                if is_grade_cell and val:
                    parts = val.split("/")
                    assert len(parts) == 2, f"Bad cell format: {val}"
                    # Values can be negative (before = count - after)
                    assert parts[0].lstrip("-").isdigit()
                    assert parts[1].lstrip("-").isdigit()

    def test_gh_gradebook_includes_unmatched(self, populated_db):
        """Students in submissions but not in gh_students should appear."""
        row_data, _ = build_gh_gradebook_view(populated_db)
        usernames = {r["_github_username"] for r in row_data}
        # 'instructor' is unmatched but not excluded and has submissions
        assert "instructor" in usernames


# ---------------------------------------------------------------------------
# Cell updates
# ---------------------------------------------------------------------------


class TestCellUpdate:
    def test_update_single_pk(self, populated_db):
        result = update_cell(
            populated_db,
            "canvas_assignments",
            {"canvas_id": 2000},
            "name",
            "Renamed HW",
        )
        assert result["ok"]
        # Verify
        row = populated_db.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = 2000"
        ).fetchone()
        assert row[0] == "Renamed HW"

    def test_update_composite_pk(self, populated_db):
        result = update_cell(
            populated_db,
            "canvas_grades",
            {"canvas_user_id": 1000, "canvas_assignment_id": 2000},
            "posted_grade",
            "9/10",
        )
        assert result["ok"]
        assert result["old_value"] is not None

    def test_update_invalid_column(self, populated_db):
        result = update_cell(
            populated_db,
            "canvas_assignments",
            {"canvas_id": 2000},
            "nonexistent_col",
            "val",
        )
        assert not result["ok"]
        assert "Unknown column" in str(result["error"])

    def test_update_wrong_pk_columns(self, populated_db):
        result = update_cell(
            populated_db,
            "canvas_assignments",
            {"wrong_pk": 1},
            "name",
            "val",
        )
        assert not result["ok"]
        assert "Expected PK" in str(result["error"])

    def test_update_invalid_table_name(self, populated_db):
        with pytest.raises(ValueError, match="Invalid SQL"):
            update_cell(
                populated_db,
                "robert'; DROP TABLE students;--",
                {"id": 1},
                "name",
                "val",
            )


# ---------------------------------------------------------------------------
# Pending change tracking
# ---------------------------------------------------------------------------


class TestPendingChanges:
    def test_track_pushable_change(self, populated_db):
        pending = {}
        track_change(
            pending,
            "canvas_grades",
            {"canvas_user_id": 1000, "canvas_assignment_id": 2000},
            "posted_grade",
            "10/10",
            "9/10",
        )
        assert "canvas_grades" in pending
        assert pending_count(pending) == 1

    def test_track_non_pushable_ignored(self, populated_db):
        pending = {}
        track_change(
            pending,
            "canvas_grades",
            {"canvas_user_id": 1000, "canvas_assignment_id": 2000},
            "score",
            10.0,
            9.0,
        )
        assert pending_count(pending) == 0

    def test_revert_removes_pending(self, populated_db):
        pending = {}
        pk = {"canvas_user_id": 1000, "canvas_assignment_id": 2000}
        track_change(pending, "canvas_grades", pk, "posted_grade", "10/10", "9/10")
        assert pending_count(pending) == 1
        # Revert back to original
        track_change(pending, "canvas_grades", pk, "posted_grade", "10/10", "10/10")
        assert pending_count(pending) == 0

    def test_track_assignment_change(self, populated_db):
        pending = {}
        track_change(
            pending,
            "canvas_assignments",
            {"canvas_id": 2000},
            "name",
            "HW1",
            "Homework 1",
        )
        assert pending_count(pending) == 1
        pk_key = "2000"
        assert pending["canvas_assignments"][pk_key]["name"]["baseline"] == "HW1"
        assert pending["canvas_assignments"][pk_key]["name"]["current"] == "Homework 1"


# ---------------------------------------------------------------------------
# Synced shadow tables & get_pending_changes
# ---------------------------------------------------------------------------


class TestSyncedShadowTables:
    def test_snapshot_creates_synced_data(self, populated_db):
        count = populated_db.execute(
            "SELECT COUNT(*) FROM _canvas_assignments_synced"
        ).fetchone()[0]
        assert count == 5

        count = populated_db.execute(
            "SELECT COUNT(*) FROM _canvas_grades_synced"
        ).fetchone()[0]
        assert count == 75

    def test_no_pending_changes_initially(self, populated_db):
        pending = db.get_pending_changes(populated_db)
        assert pending == {}

    def test_pending_after_grade_edit(self, populated_db):
        populated_db.execute(
            "UPDATE canvas_grades SET posted_grade = '5/10' "
            "WHERE canvas_user_id = 1000 AND canvas_assignment_id = 2000"
        )
        pending = db.get_pending_changes(populated_db)
        assert "canvas_grades" in pending
        assert len(pending["canvas_grades"]) == 1

    def test_pending_after_assignment_edit(self, populated_db):
        populated_db.execute(
            "UPDATE canvas_assignments SET name = 'Renamed' WHERE canvas_id = 2000"
        )
        pending = db.get_pending_changes(populated_db)
        assert "canvas_assignments" in pending

    def test_mark_synced_clears_pending(self, populated_db):
        # Make a change
        populated_db.execute(
            "UPDATE canvas_grades SET posted_grade = '5/10' "
            "WHERE canvas_user_id = 1000 AND canvas_assignment_id = 2000"
        )
        assert db.get_pending_changes(populated_db) != {}
        # Mark as synced
        db.mark_synced_grades(populated_db, [(1000, 2000)])
        assert db.get_pending_changes(populated_db) == {}

    def test_mark_synced_assignments(self, populated_db):
        populated_db.execute(
            "UPDATE canvas_assignments SET name = 'New Name' WHERE canvas_id = 2000"
        )
        assert db.get_pending_changes(populated_db) != {}
        db.mark_synced_assignments(populated_db, [2000])
        assert db.get_pending_changes(populated_db) == {}

    def test_snapshot_resets_pending(self, populated_db):
        populated_db.execute(
            "UPDATE canvas_grades SET posted_grade = '5/10' "
            "WHERE canvas_user_id = 1000 AND canvas_assignment_id = 2000"
        )
        assert db.get_pending_changes(populated_db) != {}
        # Re-snapshot = re-pull
        db.snapshot_canvas_synced(populated_db)
        assert db.get_pending_changes(populated_db) == {}


# ---------------------------------------------------------------------------
# upsert_canvas_grade
# ---------------------------------------------------------------------------


class TestUpsertCanvasGrade:
    def test_update_existing_grade(self, populated_db):
        old = db.upsert_canvas_grade(populated_db, 1000, 2000, "9/10")
        assert old != ""  # had a previous grade
        row = populated_db.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = 1000 AND canvas_assignment_id = 2000"
        ).fetchone()
        assert row[0] == "9/10"

    def test_insert_new_grade(self, populated_db):
        # Use a user/assignment combo that doesn't exist
        old = db.upsert_canvas_grade(populated_db, 9999, 9999, "5/5")
        assert old == ""
        row = populated_db.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = 9999 AND canvas_assignment_id = 9999"
        ).fetchone()
        assert row[0] == "5/5"


# ---------------------------------------------------------------------------
# Assignment groups
# ---------------------------------------------------------------------------


class TestAssignmentGroups:
    def test_get_assignment_groups(self, populated_db):
        groups = db.get_assignment_groups(populated_db)
        assert "Homeworks" in groups
        assert "Labs" in groups
        assert groups == sorted(groups)


# ---------------------------------------------------------------------------
# Edge cases in real data
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_null_deadlines_handled(self, populated_db):
        """Assignments without deadlines should not crash queries."""
        rows = db.get_enriched_rows(populated_db, "gh_assignments")
        null_deadline = [r for r in rows if not r["deadline"]]
        assert len(null_deadline) >= 1

    def test_null_due_at_handled(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "canvas_assignments")
        null_due = [r for r in rows if r["due_at"] is None]
        assert len(null_due) >= 1

    def test_null_submitted_at_handled(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "canvas_submissions")
        null_sub = [r for r in rows if not r["submitted_at"]]
        assert len(null_sub) >= 1

    def test_excluded_students_in_gh(self, populated_db):
        rows = db.get_enriched_rows(populated_db, "gh_students")
        excluded = [r for r in rows if r["excluded"]]
        assert len(excluded) >= 2

    def test_unmatched_gh_student(self, populated_db):
        """GH student not linked to any Canvas student."""
        rows = db.get_enriched_rows(populated_db, "gh_students")
        by_user = {r["github_username"]: r for r in rows}
        # 'instructor' is in gh_students but not in students table
        assert "instructor" in by_user

    def test_canvas_only_assignments(self, populated_db):
        """Assignments linked only to Canvas (no GH slug)."""
        rows = populated_db.execute(
            "SELECT slug FROM assignments WHERE canvas_assignment_id IS NOT NULL "
            "AND gh_assignment_slug IS NULL"
        ).fetchall()
        assert len(rows) >= 1

    def test_gh_only_assignments(self, populated_db):
        """Assignments linked only to GH (no Canvas ID)."""
        rows = populated_db.execute(
            "SELECT slug FROM assignments WHERE gh_assignment_slug IS NOT NULL "
            "AND canvas_assignment_id IS NULL"
        ).fetchall()
        assert len(rows) >= 1

    def test_submission_user_not_in_roster(self, populated_db):
        """GH submissions can have users not in gh_students (e.g. dropped)."""
        orphans = populated_db.execute(
            "SELECT DISTINCT gs.github_username FROM gh_submissions gs "
            "LEFT JOIN gh_students gst ON gs.github_username = gst.github_username "
            "WHERE gst.github_username IS NULL"
        ).fetchall()
        assert len(orphans) >= 1
        rows = db.get_enriched_rows(populated_db, "gh_submissions")
        assert len(rows) > 0  # should not crash
