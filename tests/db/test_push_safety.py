"""Tests for holding back unapproved pushes (commitment C1)."""

from __future__ import annotations

__docformat__ = "google"

import json

import pytest

from cass.db import exceeds_points, hold_back_unapproved
from cass.db.sync import HELD_CONFLICT, HELD_NOT_COMPARED, HELD_OVER_POINTS


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
            SimpleNamespace(user_id=1, grade="8", score=8.0),
            SimpleNamespace(user_id=2, grade="8", score=8.0),
        ]
        changes = {
            grade_key(7, 1): {"posted_grade": {"baseline": "8", "current": "9"}},
            grade_key(7, 2): {"posted_grade": {"baseline": "8", "current": "95"}},
        }
        rows = {r["canvas_user_id"]: r for r in preview_grades(conn, changes, client)}
        assert rows[1]["over_points"] is False
        assert rows[2]["over_points"] is True
        assert rows[2]["points_possible"] == 10
