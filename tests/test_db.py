"""Tests for cass.db — DuckDB CRUD round-trips."""

import time

from cass import db
from cass.models import Assignment, Grade, Student, Submission


def test_students_roundtrip(db_conn):
    students = [
        Student(
            identifier="alice",
            github_username="alice-gh",
            github_id="1",
            name="Alice Smith",
            canvas_id="100",
        ),
        Student(
            identifier="bob",
            github_username="bob-gh",
            github_id="2",
            name="Bob Jones",
            canvas_id="200",
        ),
        Student(
            identifier="charlie",
            github_username="charlie-gh",
            github_id="3",
            name="Charlie Brown",
        ),
    ]
    assert db.save_students(students) == 3
    loaded = db.load_students(include_excluded=True)
    assert len(loaded) == 3
    # Sorted by lower(identifier)
    assert loaded[0].identifier == "alice"
    assert loaded[0].github_username == "alice-gh"
    assert loaded[0].name == "Alice Smith"
    assert loaded[0].canvas_id == "100"
    assert loaded[2].identifier == "charlie"


def test_students_exclude_filter(db_conn):
    students = [
        Student(identifier="alice", excluded=False),
        Student(identifier="bob", excluded=True),
        Student(identifier="charlie", excluded=False),
    ]
    db.save_students(students)
    all_students = db.load_students(include_excluded=True)
    assert len(all_students) == 3
    active = db.load_students(include_excluded=False)
    assert len(active) == 2
    assert all(not s.excluded for s in active)


def test_students_exist(db_conn):
    assert db.students_exist() is False
    db.save_students([Student(identifier="alice")])
    assert db.students_exist() is True


def test_assignments_roundtrip(db_conn):
    assignments = [
        Assignment(
            id="hw-01",
            source="github",
            title="Homework 01",
            slug="hw-01",
            points_possible=1.0,
            accepted=25,
        ),
        Assignment(
            id="quiz-1",
            source="canvas",
            title="Quiz 1",
            canvas_id=42,
            points_possible=50.0,
        ),
    ]
    assert db.save_assignments(assignments) == 2
    loaded = db.load_assignments()
    assert len(loaded) == 2
    # Sorted by id
    assert loaded[0].id == "hw-01"
    assert loaded[0].source == "github"
    assert loaded[0].accepted == 25
    assert loaded[1].id == "quiz-1"
    assert loaded[1].canvas_id == 42
    assert loaded[1].points_possible == 50.0


def test_submissions_roundtrip(db_conn):
    subs = [
        Submission(
            student_id="alice",
            assignment_id="hw-01",
            source="github",
            submitted=True,
            commits_after=2,
        ),
        Submission(
            student_id="bob",
            assignment_id="hw-01",
            source="github",
            submitted=True,
            late=True,
            lateness_seconds=3600,
        ),
        Submission(
            student_id="alice", assignment_id="hw-02", source="github", submitted=False
        ),
    ]
    assert db.save_submissions(subs) == 3
    all_subs = db.load_submissions()
    assert len(all_subs) == 3
    hw01 = db.load_submissions(assignment_id="hw-01")
    assert len(hw01) == 2
    assert hw01[0].student_id == "alice"
    assert hw01[0].commits_after == 2
    assert hw01[1].student_id == "bob"
    assert hw01[1].late is True


def test_grades_roundtrip(db_conn):
    grades = [
        Grade(student_id="alice", assignment_id="hw-01", grade="1", numeric=1.0),
        Grade(
            student_id="bob", assignment_id="hw-01", grade="0 (+1d 01:01)", numeric=0.0
        ),
        Grade(student_id="alice", assignment_id="hw-02", grade="1+ (3)", numeric=1.0),
    ]
    assert db.save_grades(grades) == 3
    all_grades = db.load_grades()
    assert len(all_grades) == 3
    hw01 = db.load_grades(assignment_id="hw-01")
    assert len(hw01) == 2
    assert hw01[0].grade == "1"
    assert hw01[0].numeric == 1.0
    assert hw01[1].grade == "0 (+1d 01:01)"


def test_cache_roundtrip(db_conn):
    db.cache_save("test-key", '{"data": 1}')
    # Fresh load
    result = db.cache_load("test-key", ttl_hours=1)
    assert result == '{"data": 1}'
    # Expired load — patch fetched_at to the past
    db_conn.execute(
        "UPDATE api_cache SET fetched_at = ? WHERE endpoint = ?",
        [time.time() - 7200, "test-key"],
    )
    result = db.cache_load("test-key", ttl_hours=1)
    assert result is None
