"""Tests for cass.db — SQLite CRUD round-trips."""

__docformat__ = "google"

import sqlite_utils

from cass import db
from cass.actions.config import Config
from cass.db.core import _connection
from cass.db.schema import (
    CanvasAssignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
)


class TestCanvasStudents:
    def test_roundtrip(self, db_conn):
        canvas_students = [
            CanvasStudent(
                canvas_id=100,
                name="Alice Smith",
                email="alice@ucsd.edu",
                sis_user_id="A12345",
                sis_section_id="32146",
            ),
            CanvasStudent(canvas_id=200, name="Bob Jones", sis_section_id="32146"),
        ]
        assert db.save_canvas_students(canvas_students) == 2
        rows = list(
            db_conn.execute(
                "SELECT name, email, sis_user_id FROM canvas_students ORDER BY name"
            ).fetchall()
        )
        assert len(rows) == 2
        assert rows[0][0] == "Alice Smith"
        assert rows[0][1] == "alice@ucsd.edu"
        assert rows[0][2] == "A12345"
        # sis_section_id is stored in DB but not loaded into CanvasStudentResponse
        row = db_conn.execute(
            "SELECT sis_section_id FROM canvas_students WHERE canvas_id = 100"
        ).fetchone()
        assert row[0] == "32146"

    def test_load_ids(self, db_conn):
        db.save_canvas_students(
            [
                CanvasStudent(canvas_id=100, name="Alice"),
                CanvasStudent(canvas_id=200, name="Bob"),
            ]
        )
        assert db.load_canvas_student_ids() == {100, 200}


class TestCanvasAssignments:
    def test_load_ids_ordered(self, db_conn):
        db.save_canvas_assignments(
            [
                CanvasAssignment(canvas_id=43, name="Quiz 1"),
                CanvasAssignment(canvas_id=42, name="HW 01"),
            ]
        )
        assert db.load_canvas_assignment_ids() == [42, 43]


class TestSubmissions:
    def test_canvas_roundtrip(self, db_conn):
        subs = [
            CanvasSubmission(
                canvas_user_id=100,
                canvas_assignment_id=42,
                submitted=True,
                score=8.0,
                workflow_state="graded",
            ),
            CanvasSubmission(
                canvas_user_id=200,
                canvas_assignment_id=42,
                submitted=False,
            ),
        ]
        assert db.save_canvas_submissions(subs) == 2


class TestGrades:
    def test_canvas_roundtrip(self, db_conn):
        grades = [
            CanvasGrade(
                canvas_user_id=100,
                canvas_assignment_id=42,
                score=8.0,
                posted_grade="8/10",
            ),
            CanvasGrade(
                canvas_user_id=200,
                canvas_assignment_id=42,
                score=None,
                posted_grade="-",
            ),
        ]
        assert db.save_canvas_grades(grades) == 2
        loaded = db.load_canvas_grades()
        assert len(loaded) == 2
        by_aid = db.load_canvas_grades(canvas_assignment_id=42)
        assert len(by_aid) == 2
        assert by_aid[0].posted_grade == "8/10"
        assert by_aid[0].score == 8.0
        assert by_aid[1].posted_grade == "-"


class TestDbPath:
    def test_local(self, tmp_path, monkeypatch):
        """db_path returns a local file path."""
        cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
        monkeypatch.setattr("cass.db.core.get_config", lambda: cfg)
        assert db.db_path() == str(tmp_path / "cass.db")

    def test_explicit_root(self, tmp_path):
        assert db.db_path(tmp_path) == str(tmp_path / "cass.db")


class TestGetDb:
    def test_reopens_closed_cached_connection(self, tmp_path, monkeypatch):
        cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
        monkeypatch.setattr("cass.db.core.get_config", lambda: cfg)
        monkeypatch.setattr("cass.db.core._db", None)
        monkeypatch.setattr("cass.db.core._db_path", None)

        first = db.get_db()
        _connection(first).close()

        reopened = db.get_db()

        assert reopened is not first
        assert reopened.execute("SELECT 1").fetchone() == (1,)
        _connection(reopened).close()

    def test_upgrade_drops_legacy_github_tables(self, tmp_path, monkeypatch):
        cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
        monkeypatch.setattr("cass.db.core.get_config", lambda: cfg)
        monkeypatch.setattr("cass.db.core._db", None)
        monkeypatch.setattr("cass.db.core._db_path", None)

        legacy = sqlite_utils.Database(str(tmp_path / "cass.db"))
        legacy.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        legacy.execute("INSERT INTO meta VALUES ('schema_version', '15')")
        legacy.execute("CREATE TABLE gh_students (github_username TEXT PRIMARY KEY)")
        legacy.execute("CREATE TABLE students (canvas_id INTEGER PRIMARY KEY)")
        legacy.conn.close()

        upgraded = db.open_db(tmp_path)

        names = set(upgraded.table_names())
        assert "gh_students" not in names
        assert "students" not in names
        assert db.get_meta("schema_version", upgraded) == "16"
        _connection(upgraded).close()


class TestSyncedShadowTables:
    def test_snapshot(self, db_conn):
        """snapshot_canvas_synced copies canvas data to shadow tables."""
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1, name="HW1", points_possible=10.0, published=True
                )
            ]
        )
        db.save_canvas_grades(
            [
                CanvasGrade(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    score=8.0,
                    posted_grade="8",
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)

        row = db_conn.execute(
            "SELECT name, points_possible "
            "FROM _canvas_assignments_synced WHERE canvas_id = 1"
        ).fetchone()
        assert row == ("HW1", 10.0)

        row = db_conn.execute(
            "SELECT posted_grade FROM _canvas_grades_synced "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 1"
        ).fetchone()
        assert row == ("8",)

    def test_pending_empty(self, db_conn):
        """No pending changes when main and synced tables match."""
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1, name="HW1", points_possible=10.0, published=True
                )
            ]
        )
        db.save_canvas_grades(
            [
                CanvasGrade(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    score=8.0,
                    posted_grade="8",
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)

        pending = db.get_pending_changes(db_conn)
        assert pending == {}

    def test_pull_blocking_tables(self, db_conn):
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1, name="HW1", points_possible=10.0, published=True
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)
        db_conn.execute(
            "UPDATE canvas_assignments SET name = 'Homework 1' WHERE canvas_id = 1"
        )

        assert db.get_pull_blocking_tables(db_conn) == ["canvas_assignments"]
        reason = db.pull_block_reason(db_conn)
        assert reason is not None
        assert "cass push" in reason
        assert "cass revert" in reason

    def test_pending_assignment_edit(self, db_conn):
        """Editing an assignment name shows as pending."""
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1, name="HW1", points_possible=10.0, published=True
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)

        # Simulate user editing the name
        db_conn.execute(
            "UPDATE canvas_assignments SET name = 'Homework 1' WHERE canvas_id = 1"
        )

        pending = db.get_pending_changes(db_conn)
        assert "canvas_assignments" in pending
        assert "1" in pending["canvas_assignments"]
        change = pending["canvas_assignments"]["1"]["name"]
        assert change["baseline"] == "HW1"
        assert change["current"] == "Homework 1"

    def test_pending_grade_edit(self, db_conn):
        """Editing a grade shows as pending."""
        db.save_canvas_grades(
            [
                CanvasGrade(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    score=8.0,
                    posted_grade="8",
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)

        # Simulate user editing the grade
        db_conn.execute(
            "UPDATE canvas_grades SET posted_grade = '9' "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 1"
        )

        pending = db.get_pending_changes(db_conn)
        assert "canvas_grades" in pending
        import json

        pk_key = json.dumps(
            {"canvas_assignment_id": 1, "canvas_user_id": 100}, sort_keys=True
        )
        assert pk_key in pending["canvas_grades"]
        assert pending["canvas_grades"][pk_key]["posted_grade"]["baseline"] == "8"
        assert pending["canvas_grades"][pk_key]["posted_grade"]["current"] == "9"

    def test_mark_assignments(self, db_conn):
        """mark_synced_assignments updates the shadow after push."""
        db.save_canvas_assignments(
            [
                CanvasAssignment(
                    canvas_id=1, name="HW1", points_possible=10.0, published=True
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)

        # Edit + mark synced
        db_conn.execute(
            "UPDATE canvas_assignments SET name = 'Homework 1' WHERE canvas_id = 1"
        )
        assert db.get_pending_changes(db_conn) != {}

        db.mark_synced_assignments(db_conn, [1])
        assert db.get_pending_changes(db_conn) == {}

    def test_mark_grades(self, db_conn):
        """mark_synced_grades updates the shadow after push."""
        db.save_canvas_grades(
            [
                CanvasGrade(
                    canvas_user_id=100,
                    canvas_assignment_id=1,
                    score=8.0,
                    posted_grade="8",
                )
            ]
        )
        db.snapshot_canvas_synced(db_conn)

        db_conn.execute(
            "UPDATE canvas_grades SET posted_grade = '9' "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 1"
        )
        assert db.get_pending_changes(db_conn) != {}

        db.mark_synced_grades(db_conn, [(100, 1)])
        assert db.get_pending_changes(db_conn) == {}


class TestGetDbInjectedConnection:
    def test_injected_connection_wins_without_config(self, db_conn, monkeypatch):
        """An injected connection is returned without consulting project config."""

        def no_config() -> None:
            raise SystemExit("No cass.toml found")

        monkeypatch.setattr("cass.db.core.get_config", no_config)
        assert db.get_db() is db_conn
