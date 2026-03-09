"""Tests for cass.db — SQLite CRUD round-trips."""

__docformat__ = "google"

from cass import db
from cass.actions.config import Config
from cass.db.core import _connection
from cass.db.schema import (
    Assignment,
    CanvasAssignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
    GHAssignment,
    GHStudent,
    GHSubmission,
    Student,
)


class TestGHStudents:
    def test_roundtrip(self, db_conn):
        gh_students = [
            GHStudent(
                github_username="alice-gh",
                github_id=1,
                name="Alice Smith",
                email="alice@x.com",
            ),
            GHStudent(github_username="bob-gh", github_id=2, name="Bob Jones"),
        ]
        assert db.save_gh_students(gh_students) == 2
        rows = list(
            db_conn.execute(
                "SELECT github_username, name FROM gh_students ORDER BY github_username"
            ).fetchall()
        )
        assert len(rows) == 2
        assert rows[0][0] == "alice-gh"
        assert rows[0][1] == "Alice Smith"


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


class TestStudents:
    def test_upsert(self, db_conn):
        students = [
            Student(canvas_id=100, name="Alice Smith", email="alice@ucsd.edu"),
            Student(canvas_id=200, name="Bob Jones"),
        ]
        assert db.upsert_students(students) == 2
        loaded = db.load_students(include_excluded=True)
        assert len(loaded) == 2
        assert loaded[0].canvas_id == 100
        assert loaded[0].name == "Alice Smith"

    def test_upsert_preserves_github_mapping(self, db_conn):
        db.upsert_students([Student(canvas_id=100, name="Alice")])
        db.update_student_github(100, "alice-gh")

        # Re-upsert without github_username — should preserve the mapping
        db.upsert_students([Student(canvas_id=100, name="Alice Smith")])
        loaded = db.load_students()
        assert loaded[0].github_username == "alice-gh"
        assert loaded[0].name == "Alice Smith"

    def test_exclude_filter(self, db_conn):
        students = [
            Student(canvas_id=100, name="Alice", excluded=False),
            Student(canvas_id=200, name="Bob", excluded=True),
            Student(canvas_id=300, name="Charlie", excluded=False),
        ]
        db.upsert_students(students)
        all_students = db.load_students(include_excluded=True)
        assert len(all_students) == 3
        active = db.load_students(include_excluded=False)
        assert len(active) == 2
        assert all(not s.excluded for s in active)

    def test_exist(self, db_conn):
        assert db.students_exist() is False
        db.upsert_students([Student(canvas_id=100, name="Alice")])
        assert db.students_exist() is True

    def test_update_github(self, db_conn):
        db.upsert_students([Student(canvas_id=100, name="Alice")])
        db.update_student_github(100, "Alice-GH")
        loaded = db.load_students()
        assert loaded[0].github_username == "alice-gh"  # lowercased


class TestAssignments:
    def test_roundtrip(self, db_conn):
        assignments = [
            Assignment(
                slug="hw-01",
                title="Homework 01",
                gh_assignment_slug="hw-01",
                canvas_assignment_id=42,
                points_possible=1.0,
            ),
            Assignment(
                slug="quiz-1",
                title="Quiz 1",
                canvas_assignment_id=43,
                points_possible=50.0,
            ),
        ]
        assert db.upsert_assignments(assignments) == 2
        loaded = db.load_assignments()
        assert len(loaded) == 2
        assert loaded[0].slug == "hw-01"
        assert loaded[0].gh_assignment_slug == "hw-01"
        assert loaded[0].canvas_assignment_id == 42
        assert loaded[1].slug == "quiz-1"
        assert loaded[1].points_possible == 50.0

    def test_load_mappings(self, db_conn):
        assignments = [
            Assignment(
                slug="hw-01",
                title="HW 01",
                gh_assignment_slug="hw-01",
                canvas_assignment_id=42,
            ),
            Assignment(slug="quiz-1", title="Quiz 1", canvas_assignment_id=43),
        ]
        db.upsert_assignments(assignments)
        mappings = db.load_assignment_mappings()
        assert mappings == {"hw-01": 42}

    def test_gh_with_starter_code(self, db_conn):
        """save_gh_assignments stores starter_code_repo and preserves submittable_files."""  # noqa: E501
        assignments = [
            GHAssignment(
                slug="hw-01",
                gh_id=1,
                title="Homework 01",
                starter_code_repo="org/hw-01-starter",
            ),
        ]
        db.save_gh_assignments(assignments)
        row = db_conn.execute(
            "SELECT starter_code_repo, submittable_files "
            "FROM gh_assignments WHERE slug = 'hw-01'"
        ).fetchone()
        assert row[0] == "org/hw-01-starter"
        assert row[1] == ""  # default empty

        # Simulate user editing submittable_files
        db_conn.execute(
            "UPDATE gh_assignments SET submittable_files = 'homework.py,homework.qmd' "
            "WHERE slug = 'hw-01'"
        )

        # Re-save from API — should NOT overwrite submittable_files
        db.save_gh_assignments(assignments)
        row = db_conn.execute(
            "SELECT submittable_files FROM gh_assignments WHERE slug = 'hw-01'"
        ).fetchone()
        assert row[0] == "homework.py,homework.qmd"


class TestSubmissions:
    def test_gh_roundtrip(self, db_conn):
        subs = [
            GHSubmission(
                github_username="alice",
                assignment_slug="hw-01",
                submitted=True,
                commits_after_deadline=2,
                commit_count=15,
                passing=True,
                gh_autograder_score="10/10",
            ),
            GHSubmission(
                github_username="bob",
                assignment_slug="hw-01",
                submitted=True,
                late=True,
                lateness_seconds=3600,
            ),
        ]
        assert db.save_gh_submissions(subs) == 2
        loaded = db.load_gh_submissions()
        assert len(loaded) == 2
        hw01 = db.load_gh_submissions(assignment_slug="hw-01")
        assert len(hw01) == 2
        assert hw01[0].github_username == "alice"
        assert hw01[0].commits_after_deadline == 2
        assert hw01[0].passing is True
        assert hw01[1].github_username == "bob"
        assert hw01[1].late is True

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

    def test_open_db_clears_stale_github_data_without_classroom(
        self, tmp_path, monkeypatch
    ):
        cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
        monkeypatch.setattr("cass.db.core.get_config", lambda: cfg)
        monkeypatch.setattr("cass.db.core._db", None)
        monkeypatch.setattr("cass.db.core._db_path", None)

        db_file = db.open_db(tmp_path)
        db_file.execute(
            "INSERT INTO gh_students (github_username, github_id, name, email) "
            "VALUES ('alice-gh', 1, 'Alice Smith', 'alice@test.edu')"
        )
        db_file.execute(
            "INSERT INTO gh_assignments (slug, gh_id, title) "
            "VALUES ('hw-01', 1, 'Homework 01')"
        )
        db_file.execute(
            "INSERT INTO gh_submissions "
            "(github_username, assignment_slug, fetched_at) "
            "VALUES ('alice-gh', 'hw-01', 0.0)"
        )
        db_file.execute(
            "INSERT INTO assignments (slug, title, gh_assignment_slug) "
            "VALUES ('essay-01', 'Essay 01', 'hw-01')"
        )
        db_file.execute(
            "INSERT INTO assignments (slug, title, gh_assignment_slug) "
            "VALUES ('essay-02', 'Essay 02', 'hw-02')"
        )
        _connection(db_file).close()

        reopened = db.open_db(tmp_path)

        assert reopened["gh_students"].count == 0
        assert reopened["gh_assignments"].count == 0
        assert reopened["gh_submissions"].count == 0
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM assignments WHERE gh_assignment_slug IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        _connection(reopened).close()

    def test_open_db_preserves_github_data_with_partial_classroom(
        self, tmp_path, monkeypatch
    ):
        cfg = Config(
            root=tmp_path,
            classroom_url="https://classroom.github.com/classrooms/42-course",
            classroom_url_id=42,
            org="",
            canvas_base_url="https://c.edu",
            canvas_course_id=1,
        )
        monkeypatch.setattr("cass.db.core.get_config", lambda: cfg)
        monkeypatch.setattr("cass.db.core._db", None)
        monkeypatch.setattr("cass.db.core._db_path", None)
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 0\n"
            'org = ""\n\n'
            '[canvas]\nbase_url = "https://c.edu"\ncourse_id = 1\n'
        )

        db_file = db.open_db(tmp_path)
        db_file.execute(
            "INSERT INTO gh_students (github_username, github_id, name, email) "
            "VALUES ('alice-gh', 1, 'Alice Smith', 'alice@test.edu')"
        )
        _connection(db_file).commit()
        _connection(db_file).close()

        reopened = db.open_db(tmp_path)

        assert reopened["gh_students"].count == 1
        _connection(reopened).close()


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
