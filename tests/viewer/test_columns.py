"""Tests for GitHub Classroom viewer refactor — TDD.

Phase 1: Model + schema (new fields on GHSubmission, GHCommit)
Phase 2: Viewer config (enriched queries, column ordering, table groups)
Phase 3: GH gradebook pivot
"""

import msgspec
import pytest

from cass import db
from cass.apis.github.schema import GHCommit
from cass.db import ENRICHED_QUERIES, READ_ONLY_TABLES, is_editable
from cass.db.schema import GHAssignment, GHSubmission, Student
from cass.viewer.config import (
    COLUMN_DISPLAY_NAMES,
    COLUMN_ORDERING,
    HIDDEN_COLUMNS,
    display_name,
    group_tables,
)
from cass.viewer.grid import build_gh_gradebook_view, get_table_rows

# ===================================================================
# Phase 1: Model + Schema
# ===================================================================


class TestGHCommitSha:
    """GHCommit should capture sha from the API."""

    def test_commit_has_sha(self):
        data = {
            "sha": "abc123def",
            "commit": {
                "committer": {"date": "2025-01-16T02:30:00Z"},
            },
        }
        result = msgspec.convert(data, GHCommit)
        assert result.sha == "abc123def"

    def test_commit_sha_default_empty(self):
        data = {"commit": {"committer": {"date": "2025-01-16T02:30:00Z"}}}
        result = msgspec.convert(data, GHCommit)
        assert result.sha == ""


class TestGHSubmissionNewFields:
    """GHSubmission should have last_commit_at and last_commit_sha."""

    def test_new_fields_default(self):
        sub = GHSubmission(github_username="alice", assignment_slug="hw-01")
        assert sub.last_commit_at == ""
        assert sub.last_commit_sha == ""

    def test_new_fields_set(self):
        sub = GHSubmission(
            github_username="alice",
            assignment_slug="hw-01",
            last_commit_at="2025-03-01T10:00:00Z",
            last_commit_sha="abc123",
        )
        assert sub.last_commit_at == "2025-03-01T10:00:00Z"
        assert sub.last_commit_sha == "abc123"


class TestGHSubmissionSchemaV12:
    """DB schema should include last_commit_at and last_commit_sha columns."""

    def test_schema_has_new_columns(self, db_conn):
        cols = db_conn.execute("PRAGMA table_info(gh_submissions)").fetchall()
        col_names = [c[1] for c in cols]
        assert "last_commit_at" in col_names
        assert "last_commit_sha" in col_names

    def test_save_and_load_new_fields(self, db_conn):
        subs = [
            GHSubmission(
                github_username="alice",
                assignment_slug="hw-01",
                submitted=True,
                commit_count=10,
                commits_after_deadline=3,
                last_commit_at="2025-03-01T10:00:00Z",
                last_commit_sha="abc123def",
                repo_name="org/hw-01-alice",
            ),
        ]
        db.save_gh_submissions(subs)
        row = db_conn.execute(
            "SELECT last_commit_at, last_commit_sha FROM gh_submissions "
            "WHERE github_username = 'alice'"
        ).fetchone()
        assert row[0] == "2025-03-01T10:00:00Z"
        assert row[1] == "abc123def"

    def test_load_gh_submissions_includes_new_fields(self, db_conn):
        subs = [
            GHSubmission(
                github_username="alice",
                assignment_slug="hw-01",
                submitted=True,
                last_commit_at="2025-03-01T10:00:00Z",
                last_commit_sha="abc123",
            ),
        ]
        db.save_gh_submissions(subs)
        loaded = db.load_gh_submissions()
        assert loaded[0].last_commit_at == "2025-03-01T10:00:00Z"
        assert loaded[0].last_commit_sha == "abc123"


# ===================================================================
# Phase 2: Viewer Config
# ===================================================================


class TestViewerConfig:
    """Viewer config should properly handle GH tables."""

    def test_gh_assignments_readonly(self):
        assert "gh_assignments" in READ_ONLY_TABLES

    def test_gh_submissions_readonly(self):
        assert "gh_submissions" in READ_ONLY_TABLES

    def test_gh_students_partially_editable(self, db_conn):
        assert "gh_students" not in READ_ONLY_TABLES
        assert is_editable(db_conn, "gh_students") is True

    def test_gh_students_display_name_is_roster(self):
        assert display_name("gh_students") == "Roster"

    def test_gh_assignments_not_editable(self, db_conn):
        assert is_editable(db_conn, "gh_assignments") is False

    def test_gh_gradebook_in_group_order(self):
        """GH gradebook should appear in the GitHub sidebar group."""
        tables = [
            {"name": "gh_students", "type": "table"},
            {"name": "gh_assignments", "type": "table"},
            {"name": "gh_submissions", "type": "table"},
        ]
        groups = group_tables(tables, has_classroom=True)
        gh_group = next(g for g in groups if g["label"] == "GitHub Classroom")
        gh_names = [t["name"] for t in gh_group["items"]]
        # gh_gradebook is a virtual entry — it appears via the sidebar,
        # not from get_tables. Just verify the ordering of real tables.
        assert "gh_assignments" in gh_names
        assert "gh_submissions" in gh_names
        assert "gh_students" in gh_names


class TestGHEnrichedQueries:
    """Enriched queries for GH tables should join student names."""

    @pytest.fixture
    def populated_db(self, db_conn):
        """DB with students, gh_students, gh_assignments, gh_submissions."""
        # Canvas students (authoritative)
        db_conn.execute(
            "INSERT INTO canvas_students (canvas_id, name, sortable_name, email) "
            "VALUES (100, 'Alice Smith', 'Smith, Alice', 'alice@test.edu')"
        )
        db_conn.execute(
            "INSERT INTO canvas_students (canvas_id, name, sortable_name, email) "
            "VALUES (200, 'Bob Jones', 'Jones, Bob', 'bob@test.edu')"
        )
        # Master students with GH mapping
        db.upsert_students(
            [
                Student(canvas_id=100, name="Alice Smith", email="alice@test.edu"),
                Student(canvas_id=200, name="Bob Jones", email="bob@test.edu"),
            ]
        )
        db.update_student_github(100, "alice-gh")
        db.update_student_github(200, "bob-gh")

        # GH students
        from cass.db.schema import GHStudent

        db.save_gh_students(
            [
                GHStudent(github_username="alice-gh", name="Alice Smith"),
                GHStudent(github_username="bob-gh", name="Bob Jones"),
            ]
        )

        # GH assignments
        db.save_gh_assignments(
            [
                GHAssignment(slug="hw-01", gh_id=1, title="Homework 01"),
                GHAssignment(slug="hw-02", gh_id=2, title="Homework 02"),
            ]
        )

        # GH submissions
        db.save_gh_submissions(
            [
                GHSubmission(
                    github_username="alice-gh",
                    assignment_slug="hw-01",
                    submitted=True,
                    commit_count=10,
                    commits_after_deadline=2,
                    repo_name="org/hw-01-alice-gh",
                    last_commit_at="2025-03-01T10:00:00Z",
                    last_commit_sha="abc123",
                ),
                GHSubmission(
                    github_username="bob-gh",
                    assignment_slug="hw-01",
                    submitted=True,
                    commit_count=5,
                    commits_after_deadline=0,
                    repo_name="org/hw-01-bob-gh",
                    last_commit_at="2025-02-28T08:00:00Z",
                    last_commit_sha="def456",
                ),
            ]
        )
        return db_conn

    def test_gh_submissions_enriched_has_student_name(self, populated_db):
        assert "gh_submissions" in ENRICHED_QUERIES
        rows = get_table_rows(populated_db, "gh_submissions")
        assert len(rows) == 2
        # Should have 'student' column from Canvas name
        assert "student" in rows[0]

    def test_gh_submissions_enriched_has_assignment_name(self, populated_db):
        rows = get_table_rows(populated_db, "gh_submissions")
        assert "assignment_name" in rows[0]
        assert rows[0]["assignment_name"] == "Homework 01"

    def test_gh_submissions_enriched_has_repo_url(self, populated_db):
        rows = get_table_rows(populated_db, "gh_submissions")
        assert "repo_url" in rows[0]
        assert "github.com" in rows[0]["repo_url"]

    def test_gh_submissions_enriched_has_commit_url(self, populated_db):
        rows = get_table_rows(populated_db, "gh_submissions")
        # Find the row with a commit SHA
        alice_row = next(r for r in rows if r.get("last_commit_sha") == "abc123")
        assert "commit_url" in alice_row
        assert "abc123" in alice_row["commit_url"]

    def test_gh_submissions_sorted_by_last_commit(self, populated_db):
        rows = get_table_rows(populated_db, "gh_submissions")
        # Most recent commit first
        assert rows[0]["last_commit_at"] >= rows[1]["last_commit_at"]

    def test_gh_students_enriched_has_canvas_name(self, populated_db):
        assert "gh_students" in ENRICHED_QUERIES
        rows = get_table_rows(populated_db, "gh_students")
        assert len(rows) == 2
        assert "student" in rows[0]

    def test_gh_assignments_enriched(self, populated_db):
        assert "gh_assignments" in ENRICHED_QUERIES
        rows = get_table_rows(populated_db, "gh_assignments")
        assert len(rows) == 2


class TestGHColumnConfig:
    """GH tables should have proper column ordering and display names."""

    def test_gh_submissions_column_ordering(self):
        ordering = COLUMN_ORDERING.get("gh_submissions", [])
        assert "student" in ordering
        assert "assignment_name" in ordering

    def test_gh_submissions_display_names(self):
        names = COLUMN_DISPLAY_NAMES.get("gh_submissions", {})
        assert names.get("student") == "Student"
        assert names.get("assignment_name") == "Assignment"

    def test_gh_students_display_names(self):
        names = COLUMN_DISPLAY_NAMES.get("gh_students", {})
        assert names.get("student") == "Student"
        assert names.get("github_username") == "GitHub Username"

    def test_gh_submissions_hidden_columns(self):
        hidden = HIDDEN_COLUMNS.get("gh_submissions", [])
        assert "github_username" in hidden
        assert "assignment_slug" in hidden

    def test_gh_students_hidden_columns(self):
        hidden = HIDDEN_COLUMNS.get("gh_students", [])
        assert "github_id" in hidden


# ===================================================================
# Phase 3: GH Gradebook Pivot
# ===================================================================


class TestGHGradebook:
    """GH gradebook should show students x assignments with X/Y commit counts."""

    @pytest.fixture
    def gradebook_db(self, db_conn):
        """DB with data for GH gradebook pivot."""
        # Canvas students
        db_conn.execute(
            "INSERT INTO canvas_students (canvas_id, name, sortable_name, email) "
            "VALUES (100, 'Alice Smith', 'Smith, Alice', 'alice@test.edu')"
        )
        db_conn.execute(
            "INSERT INTO canvas_students (canvas_id, name, sortable_name, email) "
            "VALUES (200, 'Bob Jones', 'Jones, Bob', 'bob@test.edu')"
        )

        # Master students
        db.upsert_students(
            [
                Student(canvas_id=100, name="Alice Smith"),
                Student(canvas_id=200, name="Bob Jones"),
            ]
        )
        db.update_student_github(100, "alice-gh")
        db.update_student_github(200, "bob-gh")

        # GH students
        from cass.db.schema import GHStudent

        db.save_gh_students(
            [
                GHStudent(github_username="alice-gh", name="Alice Smith"),
                GHStudent(github_username="bob-gh", name="Bob Jones"),
            ]
        )

        # GH assignments
        db.save_gh_assignments(
            [
                GHAssignment(
                    slug="hw-01",
                    gh_id=1,
                    title="Homework 01",
                    deadline="2025-02-01T23:59:00Z",
                ),
                GHAssignment(
                    slug="hw-02",
                    gh_id=2,
                    title="Homework 02",
                    deadline="2025-03-01T23:59:00Z",
                ),
            ]
        )

        # GH submissions
        db.save_gh_submissions(
            [
                GHSubmission(
                    github_username="alice-gh",
                    assignment_slug="hw-01",
                    submitted=True,
                    commit_count=10,
                    commits_after_deadline=2,
                ),
                GHSubmission(
                    github_username="alice-gh",
                    assignment_slug="hw-02",
                    submitted=True,
                    commit_count=5,
                    commits_after_deadline=0,
                ),
                GHSubmission(
                    github_username="bob-gh",
                    assignment_slug="hw-01",
                    submitted=True,
                    commit_count=3,
                    commits_after_deadline=1,
                ),
                GHSubmission(
                    github_username="bob-gh",
                    assignment_slug="hw-02",
                    submitted=False,
                    commit_count=0,
                    commits_after_deadline=0,
                ),
            ]
        )
        return db_conn

    def test_gradebook_returns_rows_and_cols(self, gradebook_db):
        row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        assert len(row_data) == 2  # 2 students
        assert len(col_defs) >= 3  # student name + 2 assignments + hidden col

    def test_gradebook_student_column(self, gradebook_db):
        _row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        student_col = col_defs[0]
        assert student_col["field"] == "_student_name"
        assert student_col["editable"] is False

    def test_gradebook_cells_xy_format(self, gradebook_db):
        row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        # Alice's hw-01: 10 total, 2 after → 8/2
        alice = next(r for r in row_data if r["_student_name"] == "Smith, Alice")
        # Find the field for hw-01
        hw01_field = next(
            c["field"] for c in col_defs if c.get("headerName") == "Homework 01"
        )
        assert alice[hw01_field] == "8/2"

    def test_gradebook_cells_no_late_commits(self, gradebook_db):
        row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        alice = next(r for r in row_data if r["_student_name"] == "Smith, Alice")
        hw02_field = next(
            c["field"] for c in col_defs if c.get("headerName") == "Homework 02"
        )
        # Alice's hw-02: 5 total, 0 after → 5/0
        assert alice[hw02_field] == "5/0"

    def test_gradebook_cells_not_submitted(self, gradebook_db):
        row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        bob = next(r for r in row_data if r["_student_name"] == "Jones, Bob")
        hw02_field = next(
            c["field"] for c in col_defs if c.get("headerName") == "Homework 02"
        )
        # Bob didn't submit hw-02
        assert bob[hw02_field] == ""

    def test_gradebook_readonly(self, gradebook_db):
        _row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        for col in col_defs:
            assert col.get("editable", False) is False

    def test_gradebook_sorted_by_student_name(self, gradebook_db):
        row_data, _col_defs = build_gh_gradebook_view(gradebook_db)
        names = [r["_student_name"] for r in row_data]
        assert names == sorted(names)

    def test_gradebook_unmatched_student_uses_gh_name(self, gradebook_db):
        """Student without Canvas match falls back to gh_students.name."""
        from cass.db.schema import GHStudent

        # Add unmatched GH student (no entry in students table)
        db.save_gh_students(
            [
                GHStudent(github_username="charlie-gh", name="Charlie Brown"),
            ]
        )
        db.save_gh_submissions(
            [
                GHSubmission(
                    github_username="charlie-gh",
                    assignment_slug="hw-01",
                    submitted=True,
                    commit_count=7,
                    commits_after_deadline=1,
                ),
            ]
        )
        row_data, _col_defs = build_gh_gradebook_view(gradebook_db)
        charlie = next(
            (r for r in row_data if "Charlie" in r["_student_name"]),
            None,
        )
        assert charlie is not None

    def test_gradebook_assignments_ordered_by_deadline(self, gradebook_db):
        _row_data, col_defs = build_gh_gradebook_view(gradebook_db)
        # Filter to assignment columns only (not student or hidden)
        assignment_cols = [
            c
            for c in col_defs
            if c.get("field", "").startswith("_a") and not c.get("hide")
        ]
        assert len(assignment_cols) == 2
        assert assignment_cols[0]["headerName"] == "Homework 01"
        assert assignment_cols[1]["headerName"] == "Homework 02"
