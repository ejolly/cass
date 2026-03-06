"""Tests for cass.db — DuckDB CRUD round-trips."""

from cass import db
from cass.config import Config
from cass.models import (
    Assignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
    GHGrade,
    GHStudentInfo,
    GHSubmission,
    Student,
)


# --- GH Students (source) ---


def test_gh_students_roundtrip(db_conn):
    gh_students = [
        GHStudentInfo(
            login="alice-gh", id="1", name="Alice Smith", email="alice@x.com"
        ),
        GHStudentInfo(login="bob-gh", id="2", name="Bob Jones"),
    ]
    assert db.save_gh_students(gh_students) == 2
    loaded = db.load_gh_students()
    assert len(loaded) == 2
    assert loaded[0].login == "alice-gh"
    assert loaded[0].name == "Alice Smith"


# --- Canvas Students (source) ---


def test_canvas_students_roundtrip(db_conn):
    canvas_students = [
        CanvasStudent(
            id=100, name="Alice Smith", email="alice@ucsd.edu", sis_user_id="A12345"
        ),
        CanvasStudent(id=200, name="Bob Jones"),
    ]
    sis_section_map = {100: "32146", 200: "32146"}
    assert (
        db.save_canvas_students(canvas_students, sis_section_map=sis_section_map) == 2
    )
    loaded = db.load_canvas_students()
    assert len(loaded) == 2
    assert loaded[0].name == "Alice Smith"
    assert loaded[0].email == "alice@ucsd.edu"
    assert loaded[0].sis_user_id == "A12345"
    # sis_section_id is stored in DB but not loaded into CanvasStudent
    row = db_conn.execute(
        "SELECT sis_section_id FROM canvas_students WHERE canvas_id = 100"
    ).fetchone()
    assert row[0] == "32146"


# --- Students (master) ---


def test_upsert_students(db_conn):
    students = [
        Student(canvas_id=100, name="Alice Smith", email="alice@ucsd.edu"),
        Student(canvas_id=200, name="Bob Jones"),
    ]
    assert db.upsert_students(students) == 2
    loaded = db.load_students(include_excluded=True)
    assert len(loaded) == 2
    assert loaded[0].canvas_id == 100
    assert loaded[0].name == "Alice Smith"


def test_upsert_preserves_github_mapping(db_conn):
    db.upsert_students([Student(canvas_id=100, name="Alice")])
    db.update_student_github(100, "alice-gh")

    # Re-upsert without github_username — should preserve the mapping
    db.upsert_students([Student(canvas_id=100, name="Alice Smith")])
    loaded = db.load_students()
    assert loaded[0].github_username == "alice-gh"
    assert loaded[0].name == "Alice Smith"


def test_students_exclude_filter(db_conn):
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


def test_students_exist(db_conn):
    assert db.students_exist() is False
    db.upsert_students([Student(canvas_id=100, name="Alice")])
    assert db.students_exist() is True


def test_update_student_github(db_conn):
    db.upsert_students([Student(canvas_id=100, name="Alice")])
    db.update_student_github(100, "Alice-GH")
    loaded = db.load_students()
    assert loaded[0].github_username == "alice-gh"  # lowercased


# --- Assignments (master) ---


def test_assignments_roundtrip(db_conn):
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


def test_load_assignment_mappings(db_conn):
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


# --- GH Submissions ---


def test_gh_submissions_roundtrip(db_conn):
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


# --- Canvas Submissions ---


def test_canvas_submissions_roundtrip(db_conn):
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


# --- GH Grades ---


def test_gh_grades_roundtrip(db_conn):
    grades = [
        GHGrade(
            github_username="alice",
            assignment_slug="hw-01",
            grade="1",
            numeric_score=1.0,
        ),
        GHGrade(
            github_username="bob",
            assignment_slug="hw-01",
            grade="0 (+1d 01:01)",
            numeric_score=0.0,
        ),
    ]
    assert db.save_gh_grades(grades) == 2
    loaded = db.load_gh_grades()
    assert len(loaded) == 2
    hw01 = db.load_gh_grades(assignment_slug="hw-01")
    assert len(hw01) == 2
    assert hw01[0].grade == "1"
    assert hw01[0].numeric_score == 1.0
    assert hw01[1].grade == "0 (+1d 01:01)"


# --- Canvas Grades ---


def test_canvas_grades_roundtrip(db_conn):
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


# --- db_path / is_remote ---


def test_db_path_local(tmp_path, monkeypatch):
    """db_path returns a local file path when no MotherDuck configured."""
    cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
    monkeypatch.setattr("cass.db.get_config", lambda: cfg)
    assert db.db_path() == str(tmp_path / "cass.duckdb")
    assert db.is_remote() is False


def test_db_path_motherduck(tmp_path, monkeypatch):
    """db_path returns md: connection string when MotherDuck configured."""
    cfg = Config(
        root=tmp_path,
        canvas_base_url="https://c.edu",
        canvas_course_id=1,
        motherduck_db="my_db",
    )
    monkeypatch.setattr("cass.db.get_config", lambda: cfg)
    assert db.db_path() == "md:my_db"
    assert db.is_remote() is True
