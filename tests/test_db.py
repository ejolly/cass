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
    rows = db_conn.execute(
        "SELECT github_username, name FROM gh_students ORDER BY github_username"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "alice-gh"
    assert rows[0][1] == "Alice Smith"


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
    rows = db_conn.execute(
        "SELECT name, email, sis_user_id FROM canvas_students ORDER BY name"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "Alice Smith"
    assert rows[0][1] == "alice@ucsd.edu"
    assert rows[0][2] == "A12345"
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


# --- Synced shadow tables ---


def test_snapshot_canvas_synced(db_conn):
    """snapshot_canvas_synced copies canvas data to shadow tables."""
    from cass.models import CanvasAssignment

    db.save_canvas_assignments(
        [CanvasAssignment(id=1, name="HW1", points_possible=10.0, published=True)]
    )
    db.save_canvas_grades(
        [
            CanvasGrade(
                canvas_user_id=100, canvas_assignment_id=1, score=8.0, posted_grade="8"
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


def test_get_pending_changes_empty(db_conn):
    """No pending changes when main and synced tables match."""
    from cass.models import CanvasAssignment

    db.save_canvas_assignments(
        [CanvasAssignment(id=1, name="HW1", points_possible=10.0, published=True)]
    )
    db.save_canvas_grades(
        [
            CanvasGrade(
                canvas_user_id=100, canvas_assignment_id=1, score=8.0, posted_grade="8"
            )
        ]
    )
    db.snapshot_canvas_synced(db_conn)

    pending = db.get_pending_changes(db_conn)
    assert pending == {}


def test_get_pending_changes_assignment_edit(db_conn):
    """Editing an assignment name shows as pending."""
    from cass.models import CanvasAssignment

    db.save_canvas_assignments(
        [CanvasAssignment(id=1, name="HW1", points_possible=10.0, published=True)]
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


def test_get_pending_changes_grade_edit(db_conn):
    """Editing a grade shows as pending."""
    db.save_canvas_grades(
        [
            CanvasGrade(
                canvas_user_id=100, canvas_assignment_id=1, score=8.0, posted_grade="8"
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


def test_mark_synced_assignments(db_conn):
    """mark_synced_assignments updates the shadow after push."""
    from cass.models import CanvasAssignment

    db.save_canvas_assignments(
        [CanvasAssignment(id=1, name="HW1", points_possible=10.0, published=True)]
    )
    db.snapshot_canvas_synced(db_conn)

    # Edit + mark synced
    db_conn.execute(
        "UPDATE canvas_assignments SET name = 'Homework 1' WHERE canvas_id = 1"
    )
    assert db.get_pending_changes(db_conn) != {}

    db.mark_synced_assignments(db_conn, [1])
    assert db.get_pending_changes(db_conn) == {}


def test_mark_synced_grades(db_conn):
    """mark_synced_grades updates the shadow after push."""
    db.save_canvas_grades(
        [
            CanvasGrade(
                canvas_user_id=100, canvas_assignment_id=1, score=8.0, posted_grade="8"
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
