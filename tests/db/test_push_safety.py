"""Tests for holding back unapproved pushes (commitment C1)."""

from __future__ import annotations

__docformat__ = "google"

import json

import pytest

from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasCourse,
    CanvasGradingSchemeEntry,
    CanvasGradingStandard,
    CanvasSubmissionResponse,
)
from cass.apis.canvas.sync import accepts_grade, get_scheme_letters
from cass.db import CanvasGrade, exceeds_points, hold_back_unapproved
from cass.db.sync import (
    HELD_CLEAR,
    HELD_CONFLICT,
    HELD_NOT_ACCEPTED,
    HELD_NOT_COMPARED,
    HELD_OVER_POINTS,
)


def grade_key(aid: int, uid: int) -> str:
    """Return the pending-change key for a grade."""
    return json.dumps(
        {"canvas_assignment_id": aid, "canvas_user_id": uid}, sort_keys=True
    )


def grade_change(aid: int, uid: int, **extra: object) -> dict[str, object]:
    """Return a grade preview row."""
    return {
        "table": "canvas_grades",
        "canvas_assignment_id": aid,
        "canvas_user_id": uid,
        "name": f"Student {uid}",
        "column": "posted_grade",
        **extra,
    }


@pytest.fixture
def pending() -> dict:
    return {
        "canvas_assignments": {"7": {"name": {"baseline": "HW1", "current": "HW 1"}}},
        "canvas_grades": {
            grade_key(7, 1): {"posted_grade": {"baseline": "8", "current": "9"}},
            grade_key(7, 2): {"posted_grade": {"baseline": "8", "current": "95"}},
            grade_key(8, 1): {"posted_grade": {"baseline": "1", "current": "2"}},
        },
    }


class TestExceedsPoints:
    @pytest.mark.parametrize(
        ("grade", "points", "expected"),
        [
            ("11", 10.0, True),
            ("10", 10.0, False),
            (" 9.5 ", 10.0, False),
            ("101%", 10.0, True),
            ("100%", 10.0, False),
            ("A-", 10.0, False),
            ("complete", 10.0, False),
            ("5", None, False),
            ("1", 0.0, True),
            (None, 10.0, False),
        ],
    )
    def test_cases(self, grade, points, expected):
        assert exceeds_points(grade, points) is expected


class TestHoldBackUnapproved:
    def test_nothing_flagged_pushes_everything(self, pending):
        preview = {"changes": [grade_change(7, 1)]}
        to_push, held = hold_back_unapproved(pending, preview)
        assert to_push == pending
        assert held == []

    def test_conflict_is_held_unless_approved(self, pending):
        preview = {"changes": [grade_change(7, 1, conflict=True)]}
        to_push, held = hold_back_unapproved(pending, preview)
        assert grade_key(7, 1) not in to_push["canvas_grades"]
        assert grade_key(7, 2) in to_push["canvas_grades"]
        assert [h["held"] for h in held] == [HELD_CONFLICT]

        to_push, held = hold_back_unapproved(pending, preview, overwrite_conflicts=True)
        assert to_push == pending
        assert held == []

    def test_over_points_is_held_unless_approved(self, pending):
        preview = {"changes": [grade_change(7, 2, over_points=True)]}
        to_push, held = hold_back_unapproved(pending, preview)
        assert grade_key(7, 2) not in to_push["canvas_grades"]
        assert [h["held"] for h in held] == [HELD_OVER_POINTS]

        to_push, _ = hold_back_unapproved(pending, preview, allow_over_points=True)
        assert grade_key(7, 2) in to_push["canvas_grades"]

    def test_preview_error_holds_the_whole_assignment(self, pending):
        preview = {
            "changes": [
                {"table": "canvas_grades", "canvas_assignment_id": 7, "error": "x"}
            ]
        }
        to_push, held = hold_back_unapproved(
            pending, preview, overwrite_conflicts=True, allow_over_points=True
        )
        assert list(to_push["canvas_grades"]) == [grade_key(8, 1)]
        assert [h["held"] for h in held] == [HELD_NOT_COMPARED]

    def test_assignment_conflict_is_held(self, pending):
        preview = {
            "changes": [
                {
                    "table": "canvas_assignments",
                    "canvas_id": 7,
                    "name": "HW1",
                    "column": "name",
                    "conflict": True,
                }
            ]
        }
        to_push, held = hold_back_unapproved(pending, preview)
        assert "canvas_assignments" not in to_push
        assert len(held) == 1

    def test_does_not_mutate_pending(self, pending):
        before = json.dumps(pending, sort_keys=True)
        hold_back_unapproved(pending, {"changes": [grade_change(7, 1, conflict=True)]})
        assert json.dumps(pending, sort_keys=True) == before


class TestPreviewGradesFlagsOverPoints:
    def test_over_points_flag(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import sqlite_utils

        from cass import db
        from cass.db.sync import preview_grades

        conn = sqlite_utils.Database(memory=True)
        db.init_schema(conn)
        conn["canvas_assignments"].insert(
            {"canvas_id": 7, "name": "HW1", "points_possible": 10, "published": 1}
        )
        client = MagicMock()
        client.list_submissions.return_value = [
            SimpleNamespace(user_id=1, entered_grade="8", score=8.0),
            SimpleNamespace(user_id=2, entered_grade="8", score=8.0),
        ]
        client.get_assignment.return_value = CanvasAssignmentResponse(
            id=7, name="HW1", points_possible=10, grading_type="points"
        )
        changes = {
            grade_key(7, 1): {"posted_grade": {"baseline": "8", "current": "9"}},
            grade_key(7, 2): {"posted_grade": {"baseline": "8", "current": "95"}},
        }
        rows = {r["canvas_user_id"]: r for r in preview_grades(conn, changes, client)}
        assert rows[1]["over_points"] is False
        assert rows[2]["over_points"] is True
        assert rows[2]["points_possible"] == 10


class TestClearedGrades:
    @pytest.mark.parametrize(
        ("baseline", "current", "expected"),
        [
            ("8", "", True),
            ("8", None, True),
            ("8", "-", True),
            ("8", " ", True),
            ("", "", False),
            (None, "", False),
            ("8", "9", False),
            ("", "9", False),
        ],
    )
    def test_clears_grade(self, baseline, current, expected):
        from cass.db.sync import clears_grade

        assert clears_grade(baseline, current) is expected

    def test_extract_sends_clear_and_settles_blank_noops(self):
        from cass.db.sync import _extract_grade_data

        changes = {
            grade_key(7, 1): {"posted_grade": {"baseline": "8", "current": ""}},
            grade_key(7, 2): {"posted_grade": {"baseline": "", "current": "-"}},
            grade_key(7, 3): {"posted_grade": {"baseline": "8", "current": "9"}},
        }
        data, keys, noops = _extract_grade_data(changes)
        assert data == {7: {1: "", 3: "9"}}
        assert keys == {7: [grade_key(7, 1), grade_key(7, 3)]}
        assert noops == [grade_key(7, 2)]

    def test_clear_is_held_unless_approved(self, pending):
        preview = {"changes": [grade_change(7, 1, clears=True)]}
        to_push, held = hold_back_unapproved(pending, preview)
        assert grade_key(7, 1) not in to_push["canvas_grades"]
        assert held[0]["held"] == HELD_CLEAR

        to_push, held = hold_back_unapproved(pending, preview, allow_clears=True)
        assert grade_key(7, 1) in to_push["canvas_grades"]
        assert held == []

    def test_blank_grade_is_a_pending_clear(self):
        import sqlite_utils

        from cass import db

        conn = sqlite_utils.Database(memory=True)
        db.init_schema(conn)
        db.upsert_canvas_grade(conn, 1, 7, "8")
        db.snapshot_canvas_synced(conn)
        db.upsert_canvas_grade(conn, 1, 7, "")
        pending = db.get_pending_changes(conn)
        assert pending["canvas_grades"][grade_key(7, 1)]["posted_grade"] == {
            "baseline": "8",
            "current": "",
        }


class TestGradeBaselines:
    @staticmethod
    def preview(conn, *live) -> list[dict[str, object]]:
        """Preview pending grades against these live submissions."""
        from unittest.mock import MagicMock

        from cass import db

        client = MagicMock()
        client.list_submissions.return_value = list(live)
        client.get_assignment.return_value = CanvasAssignmentResponse(
            id=7, name="HW1", grading_type="points", points_possible=10
        )
        changes = db.get_pending_changes(conn)["canvas_grades"]
        return db.preview_grades(conn, changes, client)

    @staticmethod
    def baselined(conn, baseline: str, current: str) -> None:
        """Store student 1's grade on assignment 7 with a baseline, then edit it."""
        from cass import db

        db.upsert_canvas_grade(conn, 1, 7, baseline)
        db.mark_synced_grades(conn, [(1, 7)])
        db.upsert_canvas_grade(conn, 1, 7, current)

    def test_clear_after_pull_is_a_pending_clear(self, db_conn):
        from cass import db

        db.save_pulled_grades(
            [CanvasGrade(canvas_user_id=1, canvas_assignment_id=7, posted_grade="8")]
        )
        db.upsert_canvas_grade(db_conn, 1, 7, "")
        live = CanvasSubmissionResponse(user_id=1, entered_grade="8")
        (row,) = self.preview(db_conn, live)
        assert row["clears"] is True
        assert row["conflict"] is False

    @pytest.mark.parametrize("live_grade", [None, "5"])
    def test_grade_without_baseline_is_pending_conflict(self, db_conn, live_grade):
        from cass import db

        db.upsert_canvas_grade(db_conn, 1, 7, "9")
        pending = db.get_pending_changes(db_conn)
        assert pending["canvas_grades"][grade_key(7, 1)]["posted_grade"] == {
            "baseline": None,
            "current": "9",
        }
        live = CanvasSubmissionResponse(user_id=1, entered_grade=live_grade)
        (row,) = self.preview(db_conn, live)
        assert row["conflict"] is True

    def test_blank_grade_without_baseline_is_not_pending(self, db_conn):
        from cass import db

        db.upsert_canvas_grade(db_conn, 1, 7, "")
        assert db.get_pending_changes(db_conn) == {}

    def test_revert_without_baseline_removes_row(self, db_conn):
        from cass import db

        db.upsert_canvas_grade(db_conn, 1, 7, "9")
        db.upsert_canvas_grade(db_conn, 2, 7, "8")
        db.mark_synced_grades(db_conn, [(2, 7)])

        assert db.revert_changes(db_conn, db.get_pending_changes(db_conn)) == 1
        assert [g.canvas_user_id for g in db.load_canvas_grades()] == [2]
        assert db.get_pending_changes(db_conn) == {}

    def test_preview_ignores_late_deduction(self, db_conn):
        self.baselined(db_conn, "8", "9")
        live = CanvasSubmissionResponse(user_id=1, grade="7", entered_grade="8")
        (row,) = self.preview(db_conn, live)
        assert row["conflict"] is False
        assert row["live"] == "8"

    def test_first_grade_is_not_a_conflict_when_canvas_is_ungraded(self, db_conn):
        self.baselined(db_conn, "", "9")
        (row,) = self.preview(db_conn, CanvasSubmissionResponse(user_id=1))
        assert row["conflict"] is False

    def test_absent_submission_is_held_as_not_compared(self, db_conn):
        from cass import db

        self.baselined(db_conn, "", "9")
        db.upsert_canvas_grade(db_conn, 2, 7, "")
        db.mark_synced_grades(db_conn, [(2, 7)])
        db.upsert_canvas_grade(db_conn, 2, 7, "6")
        rows = self.preview(db_conn, CanvasSubmissionResponse(user_id=2))
        to_push, held = hold_back_unapproved(
            db.get_pending_changes(db_conn),
            {"changes": rows},
            overwrite_conflicts=True,
            allow_over_points=True,
            allow_clears=True,
        )
        assert [(h["canvas_user_id"], h["held"]) for h in held] == [
            (1, HELD_NOT_COMPARED)
        ]
        assert list(to_push["canvas_grades"]) == [grade_key(7, 2)]

    @pytest.mark.parametrize("typed", ["9O", "B+", "complete"])
    def test_unaccepted_grade_is_held_whatever_is_approved(self, db_conn, typed):
        from cass import db

        self.baselined(db_conn, "8", typed)
        rows = self.preview(
            db_conn, CanvasSubmissionResponse(user_id=1, entered_grade="8")
        )
        to_push, held = hold_back_unapproved(
            db.get_pending_changes(db_conn),
            {"changes": rows},
            overwrite_conflicts=True,
            allow_over_points=True,
            allow_clears=True,
        )
        assert to_push == {}
        assert [h["held"] for h in held] == [HELD_NOT_ACCEPTED]

    def test_cell_of_spaces_is_a_clear_needing_approval(self, db_conn):
        self.baselined(db_conn, "8", " ")
        (row,) = self.preview(
            db_conn, CanvasSubmissionResponse(user_id=1, entered_grade="8")
        )
        assert (row["current"], row["clears"], row["not_accepted"]) == ("", True, False)

    def test_spaces_around_a_grade_are_removed(self, db_conn):
        self.baselined(db_conn, "8", " 9 ")
        (row,) = self.preview(
            db_conn, CanvasSubmissionResponse(user_id=1, entered_grade="8")
        )
        assert (row["current"], row["not_accepted"]) == ("9", False)

    def test_unstripped_stored_grade_is_sent_stripped(self):
        from cass.db.sync import _extract_grade_data, has_grade

        assert has_grade(" ") is False
        changes = {
            grade_key(7, 1): {"posted_grade": {"baseline": "8", "current": " 9 "}}
        }
        assert _extract_grade_data(changes)[0] == {7: {1: "9"}}


class TestAcceptsGrade:
    LETTERS = frozenset({"A", "B+", "B", "F"})

    @pytest.mark.parametrize(
        ("grading_type", "accepted", "refused"),
        [
            (
                "points",
                "9 -3 +9 .5 9.5 95% 0",
                "9O abc B+ 9O% 1e1 9,5 nan inf 9. 1_0 \uff18",
            ),
            ("percent", "95% 9.5%", "95 abc B+ 9O 9O%"),
            ("letter_grade", "A b+ B+ 9 95%", "Z abc 9O complete pass"),
            ("gpa_scale", "A 3.0 95%", "Z complete"),
            ("pass_fail", "complete incomplete pass fail", "Complete abc 9 0 95% B+"),
            ("not_graded", "", "9 A complete"),
            ("", "", "9"),
        ],
    )
    def test_by_grading_type(self, grading_type, accepted, refused):
        for grade in accepted.split():
            assert accepts_grade(grade, grading_type, self.LETTERS, 10), grade
        for grade in refused.split():
            assert not accepts_grade(grade, grading_type, self.LETTERS, 10), grade

    @pytest.mark.parametrize("points_possible", [0, 0.0, None])
    @pytest.mark.parametrize(
        ("grading_type", "accepted", "refused"),
        [
            ("points", "5 0", "95%"),
            ("percent", "", "95% 0%"),
            ("letter_grade", "5", "95% A b+"),
            ("gpa_scale", "5", "95% A"),
            ("pass_fail", "complete", "95%"),
        ],
    )
    def test_without_points_possible(
        self, grading_type, accepted, refused, points_possible
    ):
        for grade in accepted.split():
            assert accepts_grade(grade, grading_type, self.LETTERS, points_possible)
        for grade in refused.split():
            assert not accepts_grade(grade, grading_type, self.LETTERS, points_possible)

    @pytest.mark.parametrize("grading_type", ["letter_grade", "gpa_scale"])
    def test_number_naming_a_scheme_entry_is_refused(self, grading_type):
        scheme = frozenset({"4", "3", "2", "1"})
        for grade in ("4", "3", "4.0", "+4"):
            assert not accepts_grade(grade, grading_type, scheme, 10), grade
        for grade in ("9", "3.5", "95%"):
            assert accepts_grade(grade, grading_type, scheme, 10), grade
        assert accepts_grade("4", "points", scheme, 10)

    @pytest.mark.parametrize(
        ("assignment_scheme", "course_scheme", "expected"),
        [(5, 6, {"Pass"}), (None, 6, {"High"}), (None, 99, set())],
    )
    def test_letters_come_from_the_grading_scheme(
        self, assignment_scheme, course_scheme, expected
    ):
        from unittest.mock import MagicMock

        client = MagicMock()
        client.get_course.return_value = CanvasCourse(
            id=1, name="C", grading_standard_id=course_scheme
        )
        client.list_grading_standards.return_value = [
            CanvasGradingStandard(
                id=i,
                title="S",
                grading_scheme=[CanvasGradingSchemeEntry(name=name, value=0.5)],
            )
            for i, name in ((5, "Pass"), (6, "High"))
        ]
        assignment = CanvasAssignmentResponse(
            id=7,
            name="HW",
            grading_type="letter_grade",
            grading_standard_id=assignment_scheme,
        )
        assert get_scheme_letters(client, assignment) == expected

    @pytest.mark.parametrize(
        ("assignment_scheme", "course_scheme"),
        [(None, None), (None, 0), (0, None), (0, 0)],
    )
    def test_no_visible_scheme_means_no_letters(self, assignment_scheme, course_scheme):
        from unittest.mock import MagicMock

        client = MagicMock()
        client.get_course.return_value = CanvasCourse(
            id=1, name="C", grading_standard_id=course_scheme
        )
        client.list_grading_standards.return_value = []
        assignment = CanvasAssignmentResponse(
            id=7,
            name="HW",
            grading_type="letter_grade",
            grading_standard_id=assignment_scheme,
        )
        letters = get_scheme_letters(client, assignment)
        assert letters == frozenset()
        assert not accepts_grade("B+", "letter_grade", letters, 10)
        assert not accepts_grade("9", "letter_grade", letters, 10)
        assert not accepts_grade("9", "gpa_scale", letters, 10)
        assert accepts_grade("95%", "letter_grade", letters, 10)
        assert not accepts_grade("95%", "letter_grade", letters, 0)

    def test_assignment_scheme_0_does_not_fall_back_to_the_course(self):
        """0 is a scheme cass cannot see, whatever the course sets."""
        from unittest.mock import MagicMock

        client = MagicMock()
        client.get_course.return_value = CanvasCourse(
            id=1, name="C", grading_standard_id=6
        )
        client.list_grading_standards.return_value = [
            CanvasGradingStandard(
                id=6,
                title="S",
                grading_scheme=[CanvasGradingSchemeEntry(name="High", value=0.5)],
            )
        ]
        assignment = CanvasAssignmentResponse(
            id=7, name="HW", grading_type="letter_grade", grading_standard_id=0
        )
        assert get_scheme_letters(client, assignment) == frozenset()


class TestPreviewUsesLivePoints:
    @staticmethod
    def preview(db_conn, grade: str, *, live: float | None, edit: float | None = None):
        """Preview a grade on an assignment pulled at 10 points."""
        from unittest.mock import MagicMock

        from cass import db

        db.save_pulled_assignments(
            [db.CanvasAssignment(canvas_id=7, name="HW1", points_possible=10)]
        )
        if edit is not None:
            db.update_cell(
                db_conn,
                "canvas_assignments",
                {"canvas_id": 7},
                "points_possible",
                edit,
            )
        db.upsert_canvas_grade(db_conn, 1, 7, grade)
        client = MagicMock()
        client.get_assignment.return_value = CanvasAssignmentResponse(
            id=7, name="HW1", grading_type="points", points_possible=live
        )
        client.list_submissions.return_value = [CanvasSubmissionResponse(user_id=1)]
        changes = db.get_pending_changes(db_conn)["canvas_grades"]
        (row,) = db.preview_grades(db_conn, changes, client)
        return row

    @pytest.mark.parametrize(("live", "over"), [(5, True), (20, False)])
    def test_points_changed_on_canvas_after_pull(self, db_conn, live, over):
        row = self.preview(db_conn, "15" if live == 20 else "8", live=live)
        assert row["over_points"] is over
        assert row["points_possible"] == live

    def test_percentage_held_when_live_points_are_zero(self, db_conn):
        assert self.preview(db_conn, "95%", live=0)["not_accepted"] is True

    def test_pending_points_edit_also_counts(self, db_conn):
        """push sends the points edit before the grades."""
        row = self.preview(db_conn, "8", live=10, edit=5)
        assert row["over_points"] is True
        assert row["points_possible"] == 5

    def test_percentage_held_when_points_edit_is_zero(self, db_conn):
        row = self.preview(db_conn, "95%", live=10, edit=0)
        assert row["not_accepted"] is True
