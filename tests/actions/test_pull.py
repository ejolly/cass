"""Tests for the Canvas-only pull flow."""

from __future__ import annotations

__docformat__ = "google"

import json
import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest
from rich.console import Console

from cass import db
from cass.actions.config import load_config, reset_config
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasStudentResponse,
    CanvasSubmissionResponse,
)
from cass.db.core import _connection
from cass.db.schema import CanvasGrade, CanvasSubmission

_MOCK_STUDENTS = [
    CanvasStudentResponse(id=100, name="Alice Smith", email="a@t.edu"),
    CanvasStudentResponse(id=200, name="Bob Jones", email="b@t.edu"),
]
_MOCK_ASSIGNMENTS = [
    CanvasAssignmentResponse(id=42, name="HW 01", points_possible=10.0),
]
_MOCK_SUBMISSIONS = [
    CanvasSubmission(
        canvas_user_id=100,
        canvas_assignment_id=42,
        submitted=True,
        submitted_at=datetime(2026, 1, 15, 12, 0, 0),
        late=False,
        lateness_seconds=0,
        score=9.0,
        workflow_state="graded",
    ),
]


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_config()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    (tmp_path / "cass.toml").write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    return load_config()


@pytest.fixture
def canvas_api():
    """Patch every Canvas call the pull flow makes."""
    with (
        patch(
            "cass.actions.pull.canvas_api.fetch_course_name",
            return_value="Test Course 101",
        ),
        patch(
            "cass.actions.pull.canvas_api.fetch_students_with_sections",
            return_value=(_MOCK_STUDENTS, {}),
        ),
        patch(
            "cass.actions.pull.canvas_api.fetch_canvas_assignments",
            return_value=(_MOCK_ASSIGNMENTS, {42: "Homework"}),
        ),
        patch(
            "cass.actions.pull.canvas_api.fetch_canvas_submissions",
            return_value=_MOCK_SUBMISSIONS,
        ) as fetch_submissions,
    ):
        yield fetch_submissions


class TestPullAll:
    def test_blocks_when_canvas_grades_pending(self, cfg, db_conn):
        db_conn.execute("INSERT INTO canvas_grades VALUES (100, 42, 9.0, '10', 1.0)")
        db_conn.execute("INSERT INTO _canvas_grades_synced VALUES (100, 42, '9')")

        from cass.actions.pull import pull_all

        with pytest.raises(RuntimeError, match=r"cass push.*cass revert"):
            pull_all(cfg)

    def test_populates_canvas_tables(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        progress: list[tuple[str, str]] = []
        pull_all(cfg, on_progress=lambda s, d: progress.append((s, d)))

        assert db_conn["canvas_students"].count == 2
        assert db_conn["canvas_assignments"].count == 1
        assert db_conn["canvas_submissions"].count == 1
        assert db.get_meta("course_name", db_conn) == "Test Course 101"
        assert {step for step, _ in progress} >= {
            "students",
            "assignments",
            "submissions",
            "done",
        }

    def test_submissions_use_roster_and_assignment_ids(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg)

        canvas_api.assert_called_once_with(1, 42, {100, 200})

    def test_persists_after_reopen(self, cfg, tmp_path, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg)

        reopened = db.open_db(tmp_path)
        assert reopened["canvas_students"].count == 2
        assert reopened["canvas_submissions"].count == 1
        _connection(reopened).close()

    def test_snapshots_synced_state(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg)

        assert db_conn["_canvas_assignments_synced"].count == 1
        assert db.pull_block_reason(db_conn) is None

    def test_no_callback(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        pull_all(cfg, on_progress=None)


class TestPullSteps:
    def test_pull_submissions_without_assignments_warns(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_submissions

        console = Console(record=True, width=120)
        pull_submissions(cfg, console)

        assert "No assignments" in console.export_text()
        canvas_api.assert_not_called()

    def test_steps_compose(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import (
            pull_assignments,
            pull_students,
            pull_submissions,
        )

        console = Console(record=True, width=120)
        pull_students(cfg, console)
        pull_assignments(cfg, console)
        pull_submissions(cfg, console)

        assert db_conn["canvas_students"].count == 2
        assert db_conn["canvas_assignments"].count == 1
        assert db_conn["canvas_submissions"].count == 1


GRADE_KEY = json.dumps({"canvas_assignment_id": 42, "canvas_user_id": 100})


def pulled(entered_grade: str, score: float | None = None) -> list[CanvasSubmission]:
    """Alice's submission as a pull returns it."""
    return [
        CanvasSubmission(
            canvas_user_id=100,
            canvas_assignment_id=42,
            score=score,
            entered_grade=entered_grade,
        )
    ]


def stored_grades(conn) -> tuple[str | None, str | None]:
    """Alice's working grade and its baseline, None where the row is missing."""
    values = []
    for table in ("canvas_grades", "_canvas_grades_synced"):
        row = conn.execute(
            f"SELECT posted_grade FROM {table} "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 42"
        ).fetchone()
        values.append(row[0] if row else None)
    return values[0], values[1]


def set_baselined_grade(conn, grade: str) -> None:
    """Store a grade for Alice with the same baseline."""
    db.upsert_canvas_grade(conn, 100, 42, grade)
    db.mark_synced_grades(conn, [(100, 42)])


class TestPullGrades:
    def test_pull_stores_entered_grade_and_baseline(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        canvas_api.return_value = pulled("B+", 8.5)
        pull_all(cfg)

        assert stored_grades(db_conn) == ("B+", "B+")
        assert db.load_canvas_grades()[0].score == 8.5
        assert db.get_pending_changes(db_conn) == {}
        assert db.get_meta("grade_baselines") == "1"

    def test_edit_after_pull_is_pending_and_blocks_pull(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        canvas_api.return_value = pulled("8")
        pull_all(cfg)
        db.upsert_canvas_grade(db_conn, 100, 42, "9")

        pending = db.get_pending_changes(db_conn)
        assert pending["canvas_grades"][GRADE_KEY]["posted_grade"] == {
            "baseline": "8",
            "current": "9",
        }
        assert db.pull_block_reason(db_conn) is not None

    def test_first_grade_on_ungraded_submission_is_pending(
        self, cfg, db_conn, canvas_api
    ):
        from cass.actions.pull import pull_all

        canvas_api.return_value = pulled("")
        pull_all(cfg)
        db.upsert_canvas_grade(db_conn, 100, 42, "9")

        pending = db.get_pending_changes(db_conn)
        assert pending["canvas_grades"][GRADE_KEY]["posted_grade"] == {
            "baseline": "",
            "current": "9",
        }

    def test_upgrade_keeps_differing_grade_as_conflict(self, cfg, db_conn, canvas_api):
        set_baselined_grade(db_conn, "9")

        kept = db.save_pulled_grades(
            [CanvasGrade(canvas_user_id=100, canvas_assignment_id=42, posted_grade="5")]
        )

        assert kept == [(100, 42)]
        assert stored_grades(db_conn) == ("9", None)

    @pytest.mark.parametrize(("local", "canvas"), [("", "5"), ("5", "5")])
    def test_upgrade_takes_canvas_when_local_is_blank_or_equal(
        self, db_conn, local, canvas
    ):
        set_baselined_grade(db_conn, local)

        kept = db.save_pulled_grades(
            [
                CanvasGrade(
                    canvas_user_id=100, canvas_assignment_id=42, posted_grade=canvas
                )
            ]
        )

        assert kept == []
        assert stored_grades(db_conn) == (canvas, canvas)

    def test_full_pull_names_kept_grade_and_stays_blocked(
        self, cfg, db_conn, canvas_api
    ):
        from cass.actions.pull import pull_all

        set_baselined_grade(db_conn, "9")
        canvas_api.return_value = pulled("5")
        progress: list[tuple[str, str]] = []
        pull_all(cfg, on_progress=lambda s, d: progress.append((s, d)))

        (notice,) = [detail for step, detail in progress if step == "kept"]
        assert "Alice Smith — HW 01" in notice
        assert "5" in notice
        assert "cass push" in notice
        assert "cass revert" in notice
        assert stored_grades(db_conn) == ("9", None)
        assert db.pull_block_reason(db_conn) is not None
        assert db.get_meta("grade_baselines") == "1"

    def test_second_pull_takes_canvas_value(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        db.save_meta("grade_baselines", "1")
        set_baselined_grade(db_conn, "9")
        canvas_api.return_value = pulled("5")
        pull_all(cfg)

        assert stored_grades(db_conn) == ("5", "5")

    def test_edit_made_while_pulling_is_not_overwritten(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all

        canvas_api.return_value = pulled("8")
        pull_all(cfg)

        def edit_then_return(*args):
            db.upsert_canvas_grade(db_conn, 100, 42, "9")
            return pulled("8")

        canvas_api.side_effect = edit_then_return
        with pytest.raises(RuntimeError, match="Pull blocked"):
            pull_all(cfg)

        assert stored_grades(db_conn) == ("9", "8")

    def test_edit_made_just_before_grades_are_saved_is_kept(self, cfg, db_conn):
        set_baselined_grade(db_conn, "8")
        db.upsert_canvas_grade(db_conn, 100, 42, "9")
        with pytest.raises(RuntimeError, match="Pull blocked"):
            db.save_pulled_grades(
                [
                    CanvasGrade(
                        canvas_user_id=100, canvas_assignment_id=42, posted_grade="8"
                    )
                ]
            )
        assert stored_grades(db_conn) == ("9", "8")

    def test_pending_check_runs_under_the_write_lock(self, tmp_path, cfg, monkeypatch):
        """Another process cannot save an edit between the check and the write."""
        db.reset()
        conn = db.get_db(tmp_path)
        other = sqlite3.connect(str(tmp_path / "cass.db"), timeout=0)
        attempts = []

        def check(sdb):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute(
                    "INSERT INTO canvas_grades VALUES (100, 42, NULL, '9', 1.0)"
                )
            attempts.append(sdb)

        monkeypatch.setattr("cass.db.sync.pull_block_reason", check)
        db.save_pulled_grades(
            [CanvasGrade(canvas_user_id=100, canvas_assignment_id=42, posted_grade="8")]
        )
        db.save_pulled_assignments([db.CanvasAssignment(canvas_id=42, name="HW")])
        assert len(attempts) == 2
        assert stored_grades(conn) == ("8", "8")
        other.close()
        db.reset()

    @pytest.mark.parametrize("failing_write", ["INSERT", "DELETE"])
    def test_failed_save_rolls_back_both_tables(self, db_conn, failing_write):
        set_baselined_grade(db_conn, "9")
        db_conn.execute(
            f"CREATE TRIGGER fail BEFORE {failing_write} ON _canvas_grades_synced "
            "BEGIN SELECT RAISE(ABORT, 'disk trouble'); END"
        )
        grades = [
            CanvasGrade(canvas_user_id=u, canvas_assignment_id=42, posted_grade="5")
            for u in (100, 200)
        ]
        with pytest.raises(sqlite3.Error, match="disk trouble"):
            db.save_pulled_grades(grades)
        assert db_conn["canvas_grades"].count == 1
        assert db_conn["_canvas_grades_synced"].count == 1
        assert stored_grades(db_conn) == ("9", "9")

    def test_assignment_edit_made_while_pulling_is_not_overwritten(
        self, cfg, db_conn, canvas_api
    ):
        from cass.actions.pull import pull_all, pull_assignments

        pull_all(cfg)

        def edit_then_return(*args):
            db.update_cell(
                db_conn, "canvas_assignments", {"canvas_id": 42}, "name", "Edited"
            )
            return _MOCK_ASSIGNMENTS, {}

        with (
            patch(
                "cass.actions.pull.canvas_api.fetch_canvas_assignments",
                side_effect=edit_then_return,
            ),
            pytest.raises(RuntimeError, match="Pull blocked"),
        ):
            pull_assignments(cfg, Console(quiet=True))

        pending = db.get_pending_changes(db_conn)["canvas_assignments"]["42"]
        assert pending == {"name": {"baseline": "HW 01", "current": "Edited"}}

    def test_partial_pull_stores_grades_and_names_kept_ones(
        self, cfg, db_conn, canvas_api
    ):
        from cass.actions.pull import (
            pull_assignments,
            pull_students,
            pull_submissions,
        )

        console = Console(record=True, width=200)
        set_baselined_grade(db_conn, "9")
        canvas_api.return_value = pulled("5")
        pull_students(cfg, console)
        pull_assignments(cfg, console)
        pull_submissions(cfg, console)

        assert stored_grades(db_conn) == ("9", None)
        assert "Alice Smith — HW 01" in console.export_text()
        assert db.get_meta("grade_baselines") is None

    def test_pull_assignments_updates_baseline(self, cfg, db_conn, canvas_api):
        from cass.actions.pull import pull_all, pull_assignments

        pull_all(cfg)
        renamed = [CanvasAssignmentResponse(id=42, name="Renamed", points_possible=10)]
        with patch(
            "cass.actions.pull.canvas_api.fetch_canvas_assignments",
            return_value=(renamed, {}),
        ):
            pull_assignments(cfg, Console(quiet=True))

        assert db_conn["canvas_assignments"].get(42)["name"] == "Renamed"
        assert db.get_pending_changes(db_conn) == {}
        assert db.pull_block_reason(db_conn) is None

    def test_ungraded_submission_shows_dash_in_gradebook(
        self, cfg, db_conn, canvas_api
    ):
        from cass.actions.pull import pull_all

        canvas_api.return_value = pulled("")
        pull_all(cfg)

        _, rows = db.build_canvas_gradebook_matrix(db_conn)
        assert [row[1] for row in rows] == ["-", "-"]


def test_fetched_submissions_carry_entered_grade(monkeypatch):
    from cass.apis.canvas import matching

    class FakeClient:
        def __init__(self, course_id):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def list_submissions(self, assignment_id):
            return [
                CanvasSubmissionResponse(user_id=100, grade="7", entered_grade="8"),
                CanvasSubmissionResponse(user_id=200, grade=None),
            ]

    monkeypatch.setattr(matching, "CanvasClient", FakeClient)
    subs = matching.fetch_canvas_submissions(1, 42, {100, 200})
    assert [s.entered_grade for s in subs] == ["8", ""]
