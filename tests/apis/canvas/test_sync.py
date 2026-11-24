"""Tests for Canvas sync logic — Tier 2B (mock CanvasClient, no UI).

Tests preview_assignments(), preview_grades(), canvas_preview(),
canvas_apply(), and helper functions.
"""

from __future__ import annotations

__docformat__ = "google"

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
import sqlite_utils

from cass import db
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasSubmissionResponse,
)
from cass.db import canvas_apply, canvas_preview
from cass.db.sync import HELD_NOT_COMPARED

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestSameInstant:
    def test_offset_and_utc_forms_match(self):
        from cass.apis.canvas.sync import same_instant

        assert same_instant("2026-10-01T23:59:00-07:00", "2026-10-02T06:59:00Z")

    def test_different_instants_differ(self):
        from cass.apis.canvas.sync import same_instant

        assert not same_instant("2026-10-01T23:59:00-07:00", "2026-10-01T23:59:00Z")

    def test_empty_and_none(self):
        from cass.apis.canvas.sync import same_instant

        assert same_instant("", None)
        assert not same_instant("2026-10-01T23:59:00Z", None)

    def test_unparseable_falls_back_to_string_compare(self):
        from cass.apis.canvas.sync import same_instant

        assert same_instant("soon", "soon")
        assert not same_instant("soon", "later")


class TestResolveGroupIds:
    def test_case_insensitive_and_missing(self):
        from cass.apis.canvas.schema import CanvasAssignmentGroup
        from cass.apis.canvas.sync import resolve_group_ids

        client = MagicMock()
        client.list_assignment_groups.return_value = [
            CanvasAssignmentGroup(id=9, name="Labs")
        ]
        ids, missing = resolve_group_ids(client, ["labs", "Homework", "LABS"])
        assert ids == {"labs": 9}
        assert missing == ["Homework"]

    def test_missing_names_differing_only_in_case_are_listed_once(self):
        from cass.apis.canvas.sync import resolve_group_ids

        client = MagicMock()
        client.list_assignment_groups.return_value = []
        _, missing = resolve_group_ids(client, ["Labs", "LABS", "labs"])
        assert missing == ["Labs"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_conn():
    """In-memory SQLite with schema for canvas sync tests."""
    conn = sqlite_utils.Database(memory=True)

    conn.execute(
        "CREATE TABLE canvas_assignments ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  points_possible DOUBLE,"
        "  due_at TEXT,"
        "  published BOOLEAN DEFAULT true,"
        "  post_manually BOOLEAN DEFAULT false"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_assignments VALUES "
        "(1, 'Homework 1', 10.0, '2026-02-01T23:59', true, false),"
        "(2, 'Homework 2', 20.0, '2026-02-15T23:59', true, false)"
    )

    conn.execute(
        "CREATE TABLE canvas_students ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  email TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_students VALUES "
        "(100, 'Alice Smith', 'alice@test.edu'),"
        "(200, 'Bob Jones', 'bob@test.edu')"
    )

    conn.execute(
        "CREATE TABLE canvas_grades ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  score DOUBLE,"
        "  posted_grade TEXT NOT NULL DEFAULT '',"
        "  updated_at TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_grades VALUES "
        "(100, 1, 9.0, '9', '2026-02-02T10:00'),"
        "(200, 1, 7.0, '7', '2026-02-02T11:00')"
    )

    # Shadow tables for synced state
    conn.execute(
        "CREATE TABLE _canvas_assignments_synced ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  points_possible DOUBLE,"
        "  due_at TEXT,"
        "  published BOOLEAN"
        ")"
    )
    conn.execute(
        "INSERT INTO _canvas_assignments_synced "
        "SELECT canvas_id, name, points_possible, due_at, published "
        "FROM canvas_assignments"
    )

    conn.execute(
        "CREATE TABLE _canvas_grades_synced ("
        "  canvas_user_id INTEGER,"
        "  canvas_assignment_id INTEGER,"
        "  posted_grade TEXT,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO _canvas_grades_synced "
        "SELECT canvas_user_id, canvas_assignment_id, posted_grade "
        "FROM canvas_grades"
    )

    return conn


def _make_assignment(
    id: int = 1,
    name: str = "Homework 1",
    points_possible: float = 10.0,
    due_at: str | None = "2026-02-01T23:59",
    published: bool = True,
    post_manually: bool | None = False,
) -> SimpleNamespace:
    """Create a mock CanvasAssignmentResponse-like object."""
    return SimpleNamespace(
        id=id,
        name=name,
        points_possible=points_possible,
        due_at=due_at,
        published=published,
        quiz_id=None,
        post_manually=post_manually,
    )


def _make_submission(
    user_id: int,
    grade: str | None = None,
    score: float | None = None,
) -> SimpleNamespace:
    """Create a mock CanvasSubmissionResponse-like object."""
    return SimpleNamespace(user_id=user_id, entered_grade=grade, score=score)


# ---------------------------------------------------------------------------
# preview_assignments tests
# ---------------------------------------------------------------------------


class TestPreviewAssignments:
    """Tests for preview_assignments()."""

    def test_no_conflicts(self, sync_conn):
        """Changes with matching live values have conflict=False."""
        from cass.db import preview_assignments

        client = MagicMock()
        client.get_assignment.return_value = _make_assignment(points_possible=10.0)

        table_changes = {
            "1": {
                "points_possible": {"baseline": 10.0, "current": 20.0},
            }
        }
        results = preview_assignments(sync_conn, table_changes, client)

        assert len(results) == 1
        r = results[0]
        assert r["table"] == "canvas_assignments"
        assert r["canvas_id"] == 1
        assert r["name"] == "Homework 1"
        assert r["column"] == "points_possible"
        assert r["baseline"] == 10.0
        assert r["current"] == 20.0
        assert r["live"] == 10.0
        assert r["conflict"] is False

    def test_conflict_detected(self, sync_conn):
        """Conflict flagged when live value differs from baseline."""
        from cass.db import preview_assignments

        client = MagicMock()
        # Live value (15.0) differs from baseline (10.0)
        client.get_assignment.return_value = _make_assignment(points_possible=15.0)

        table_changes = {
            "1": {
                "points_possible": {"baseline": 10.0, "current": 20.0},
            }
        }
        results = preview_assignments(sync_conn, table_changes, client)

        assert len(results) == 1
        assert results[0]["conflict"] is True
        assert results[0]["live"] == 15.0

    def test_multiple_columns(self, sync_conn):
        """Multiple column changes on one assignment produce multiple results."""
        from cass.db import preview_assignments

        client = MagicMock()
        client.get_assignment.return_value = _make_assignment()

        table_changes = {
            "1": {
                "name": {"baseline": "Homework 1", "current": "HW 1"},
                "points_possible": {"baseline": 10.0, "current": 15.0},
            }
        }
        results = preview_assignments(sync_conn, table_changes, client)
        assert len(results) == 2
        columns = {r["column"] for r in results}
        assert columns == {"name", "points_possible"}

    def test_api_error_returns_error_dict(self, sync_conn):
        """API failure returns an error dict instead of crashing."""
        from cass.db import preview_assignments

        client = MagicMock()
        client.get_assignment.side_effect = RuntimeError("API timeout")

        table_changes = {
            "1": {
                "name": {"baseline": "Homework 1", "current": "HW 1"},
            }
        }
        results = preview_assignments(sync_conn, table_changes, client)

        assert len(results) == 1
        assert "error" in results[0]
        assert results[0]["error"] == "API timeout"
        assert results[0]["name"] == "Homework 1"

    def test_multiple_assignments(self, sync_conn):
        """Changes across multiple assignments are all previewed."""
        from cass.db import preview_assignments

        client = MagicMock()
        client.get_assignment.side_effect = [
            _make_assignment(id=1, points_possible=10.0),
            _make_assignment(id=2, points_possible=20.0),
        ]

        table_changes = {
            "1": {"points_possible": {"baseline": 10.0, "current": 15.0}},
            "2": {"points_possible": {"baseline": 20.0, "current": 25.0}},
        }
        results = preview_assignments(sync_conn, table_changes, client)
        assert len(results) == 2
        ids = {r["canvas_id"] for r in results}
        assert ids == {1, 2}


# ---------------------------------------------------------------------------
# preview_grades tests
# ---------------------------------------------------------------------------


class TestPreviewGrades:
    """Tests for preview_grades()."""

    def _pk(self, uid: int, aid: int) -> str:
        return json.dumps(
            {"canvas_assignment_id": aid, "canvas_user_id": uid},
            sort_keys=True,
        )

    def test_no_conflicts(self, sync_conn):
        """Grade preview with matching live values."""
        from cass.db import preview_grades

        client = MagicMock()
        client.list_submissions.return_value = [
            _make_submission(user_id=100, grade="9", score=9.0),
        ]

        table_changes = {
            self._pk(100, 1): {
                "posted_grade": {"baseline": "9", "current": "10"},
            }
        }
        results = preview_grades(sync_conn, table_changes, client)

        assert len(results) == 1
        r = results[0]
        assert r["table"] == "canvas_grades"
        assert r["canvas_user_id"] == 100
        assert r["canvas_assignment_id"] == 1
        assert "Alice Smith" in str(r["name"])
        assert "Homework 1" in str(r["name"])
        assert r["conflict"] is False
        assert r["live"] == "9"  # posted_grade maps to .entered_grade

    def test_conflict_detected(self, sync_conn):
        """Conflict when live grade differs from baseline."""
        from cass.db import preview_grades

        client = MagicMock()
        client.list_submissions.return_value = [
            _make_submission(user_id=100, grade="8"),  # live=8, baseline=9
        ]

        table_changes = {
            self._pk(100, 1): {
                "posted_grade": {"baseline": "9", "current": "10"},
            }
        }
        results = preview_grades(sync_conn, table_changes, client)

        assert len(results) == 1
        assert results[0]["conflict"] is True
        assert results[0]["live"] == "8"

    def test_score_column_mapping(self, sync_conn):
        """Score column maps to live submission's score attribute."""
        from cass.db import preview_grades

        client = MagicMock()
        client.list_submissions.return_value = [
            _make_submission(user_id=100, score=9.0),
        ]

        table_changes = {
            self._pk(100, 1): {
                "score": {"baseline": 9.0, "current": 10.0},
            }
        }
        results = preview_grades(sync_conn, table_changes, client)

        assert len(results) == 1
        assert results[0]["live"] == 9.0

    def test_api_error_returns_error_dict(self, sync_conn):
        """API failure on list_submissions returns error dict."""
        from cass.db import preview_grades

        client = MagicMock()
        client.list_submissions.side_effect = RuntimeError("Connection refused")

        table_changes = {
            self._pk(100, 1): {
                "posted_grade": {"baseline": "9", "current": "10"},
            }
        }
        results = preview_grades(sync_conn, table_changes, client)

        assert len(results) == 1
        assert "error" in results[0]
        assert "Connection refused" in str(results[0]["error"])

    def test_batching_by_assignment(self, sync_conn):
        """Multiple students in same assignment batch into one API call."""
        from cass.db import preview_grades

        client = MagicMock()
        client.list_submissions.return_value = [
            _make_submission(user_id=100, grade="9"),
            _make_submission(user_id=200, grade="7"),
        ]

        table_changes = {
            self._pk(100, 1): {
                "posted_grade": {"baseline": "9", "current": "10"},
            },
            self._pk(200, 1): {
                "posted_grade": {"baseline": "7", "current": "8"},
            },
        }
        results = preview_grades(sync_conn, table_changes, client)

        assert len(results) == 2
        # Only one API call for assignment 1
        client.list_submissions.assert_called_once_with(1)

    def test_missing_student_name_fallback(self, sync_conn):
        """Unknown student ID falls back to 'User {uid}'."""
        from cass.db import preview_grades

        client = MagicMock()
        client.list_submissions.return_value = [
            _make_submission(user_id=999, grade="5"),
        ]

        table_changes = {
            self._pk(999, 1): {
                "posted_grade": {"baseline": "5", "current": "6"},
            }
        }
        results = preview_grades(sync_conn, table_changes, client)

        assert "User 999" in str(results[0]["name"])


# ---------------------------------------------------------------------------
# canvas_preview orchestrator tests
# ---------------------------------------------------------------------------


class TestCanvasPreview:
    """Tests for canvas_preview() orchestrator."""

    def test_empty_pending_returns_ok(self, sync_conn):
        """No pending changes returns ok with empty changes list."""
        result = canvas_preview(sync_conn, {})
        assert result["ok"] is True
        assert result["changes"] == []

    def test_combines_assignment_and_grade_previews(self, sync_conn):
        """Orchestrator combines both assignment and grade previews."""
        mock_client = MagicMock()
        mock_client.get_assignment.return_value = _make_assignment()
        mock_client.list_submissions.return_value = [
            _make_submission(user_id=100, grade="9"),
        ]

        pk_key = json.dumps(
            {"canvas_assignment_id": 1, "canvas_user_id": 100},
            sort_keys=True,
        )
        pending = {
            "canvas_assignments": {
                "1": {"name": {"baseline": "Homework 1", "current": "HW 1"}},
            },
            "canvas_grades": {
                pk_key: {"posted_grade": {"baseline": "9", "current": "10"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None
            result = canvas_preview(sync_conn, pending)

        assert result["ok"] is True
        changes = cast(list[dict[str, object]], result["changes"])
        assert len(changes) == 2
        tables = {c["table"] for c in changes}
        assert tables == {"canvas_assignments", "canvas_grades"}

    def test_has_conflicts_flag(self, sync_conn):
        """has_conflicts is True when any change has conflict."""
        mock_client = MagicMock()
        # Live differs from baseline → conflict
        mock_client.get_assignment.return_value = _make_assignment(points_possible=15.0)

        pending = {
            "canvas_assignments": {
                "1": {
                    "points_possible": {"baseline": 10.0, "current": 20.0},
                },
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None
            result = canvas_preview(sync_conn, pending)

        assert result["has_conflicts"] is True

    def test_has_errors_flag(self, sync_conn):
        """has_errors is True when any preview fails."""
        mock_client = MagicMock()
        mock_client.get_assignment.side_effect = RuntimeError("fail")

        pending = {
            "canvas_assignments": {
                "1": {"name": {"baseline": "HW1", "current": "HW 1"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None
            result = canvas_preview(sync_conn, pending)

        assert result["has_errors"] is True


# ---------------------------------------------------------------------------
# canvas_apply tests
# ---------------------------------------------------------------------------


class TestCanvasApply:
    """Tests for canvas_apply()."""

    def test_empty_pending_returns_ok(self, sync_conn):
        """No pending changes returns ok with empty results."""
        result = canvas_apply(sync_conn, {})
        assert result["ok"] is True
        assert result["results"] == []

    def test_assignment_push_success(self, sync_conn):
        """Successful assignment push clears pending and updates synced."""
        mock_client = MagicMock()
        mock_client.update_assignment.return_value = None

        pending = {
            "canvas_assignments": {
                "1": {"name": {"baseline": "Homework 1", "current": "HW 1"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None

            # Update the actual DB first (as the UI would have done)
            sync_conn.execute(
                "UPDATE canvas_assignments SET name = 'HW 1' WHERE canvas_id = 1"
            )

            result = canvas_apply(sync_conn, pending)

        assert result["ok"] is True
        results = cast(list[dict[str, object]], result["results"])
        assert len(results) == 1
        assert results[0]["ok"] is True

        # Pending should be cleared
        assert "canvas_assignments" not in pending

        # Synced shadow should be updated
        synced = sync_conn.execute(
            "SELECT name FROM _canvas_assignments_synced WHERE canvas_id = 1"
        ).fetchone()
        assert synced is not None
        assert synced[0] == "HW 1"

    def test_grade_push_success(self, sync_conn):
        """Successful grade push clears pending and updates synced."""
        mock_client = MagicMock()
        mock_client.get_assignment.return_value = _make_assignment()
        mock_progress = SimpleNamespace(id=42)
        mock_client.bulk_push_grades.return_value = mock_progress
        mock_client.wait_for_progress.return_value = None

        pk_key = json.dumps(
            {"canvas_assignment_id": 1, "canvas_user_id": 100},
            sort_keys=True,
        )
        pending = {
            "canvas_grades": {
                pk_key: {"posted_grade": {"baseline": "9", "current": "10"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None

            # Update DB
            sync_conn.execute(
                "UPDATE canvas_grades SET posted_grade = '10' "
                "WHERE canvas_user_id = 100 AND canvas_assignment_id = 1"
            )

            result = canvas_apply(sync_conn, pending)

        assert result["ok"] is True
        assert "canvas_grades" not in pending

        # Synced shadow updated
        synced = sync_conn.execute(
            "SELECT posted_grade FROM _canvas_grades_synced "
            "WHERE canvas_user_id = 100 AND canvas_assignment_id = 1"
        ).fetchone()
        assert synced is not None
        assert synced[0] == "10"

    def test_assignment_push_partial_failure(self, sync_conn):
        """Failed assignment push keeps that entry in pending."""
        mock_client = MagicMock()
        # First succeeds, second fails
        mock_client.update_assignment.side_effect = [
            None,
            RuntimeError("API error"),
        ]

        pending = {
            "canvas_assignments": {
                "1": {"name": {"baseline": "Homework 1", "current": "HW 1"}},
                "2": {"name": {"baseline": "Homework 2", "current": "HW 2"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None

            sync_conn.execute(
                "UPDATE canvas_assignments SET name = 'HW 1' WHERE canvas_id = 1"
            )

            result = canvas_apply(sync_conn, pending)

        assert result["ok"] is False  # not all succeeded

        # Assignment 1 cleared, assignment 2 still pending
        assert "1" not in pending.get("canvas_assignments", {})
        assert "2" in pending["canvas_assignments"]

    def test_grade_push_partial_failure(self, sync_conn):
        """Failed grade push per-assignment keeps those entries pending."""
        mock_client = MagicMock()
        mock_client.get_assignment.return_value = _make_assignment()
        mock_client.bulk_push_grades.side_effect = RuntimeError("Bulk fail")

        pk_key = json.dumps(
            {"canvas_assignment_id": 1, "canvas_user_id": 100},
            sort_keys=True,
        )
        pending = {
            "canvas_grades": {
                pk_key: {"posted_grade": {"baseline": "9", "current": "10"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None

            result = canvas_apply(sync_conn, pending)

        assert result["ok"] is False
        # Grade still in pending
        assert pk_key in pending["canvas_grades"]

    def test_empty_tables_cleaned_from_pending(self, sync_conn):
        """Empty table entries are removed from pending dict after push."""
        mock_client = MagicMock()
        mock_client.update_assignment.return_value = None

        pending = {
            "canvas_assignments": {
                "1": {"name": {"baseline": "Homework 1", "current": "HW 1"}},
            },
        }

        with patch("cass.apis.canvas.client.CanvasClient") as MockClient:
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = lambda s, *a: None

            sync_conn.execute(
                "UPDATE canvas_assignments SET name = 'HW 1' WHERE canvas_id = 1"
            )
            canvas_apply(sync_conn, pending)

        # Entire canvas_assignments key should be gone
        assert "canvas_assignments" not in pending


# ---------------------------------------------------------------------------
# Releasing grades on manual-post assignments
# ---------------------------------------------------------------------------


class TestReleaseGrades:
    """Grades become visible to students only with separate approval (C5)."""

    @pytest.fixture
    def policies(self) -> dict[int, bool | None]:
        """Canvas's live posting policy by assignment; tests change it."""
        return {1: True, 2: True}

    @pytest.fixture
    def client(self, policies, monkeypatch) -> MagicMock:
        client = MagicMock()
        client.get_assignment.side_effect = lambda aid: CanvasAssignmentResponse(
            id=aid,
            name=f"Homework {aid}",
            points_possible=10,
            grading_type="points",
            post_manually=policies[aid],
        )
        client.list_submissions.side_effect = lambda aid: [
            CanvasSubmissionResponse(user_id=uid, entered_grade="5")
            for uid in (1, 2, 3)
        ]
        monkeypatch.setattr(
            "cass.apis.canvas.client.CanvasClient", lambda: nullcontext(client)
        )
        return client

    @pytest.fixture
    def edit(self, db_conn):
        """Return a function that stores an unpushed grade edit (Canvas has 5)."""

        def _edit(uid: int, aid: int, grade: str) -> None:
            db.upsert_canvas_grade(db_conn, uid, aid, "5")
            db.mark_synced_grades(db_conn, [(uid, aid)])
            db.upsert_canvas_grade(db_conn, uid, aid, grade)

        return _edit

    @staticmethod
    def rows(result: dict[str, object]) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], result["results"])

    def test_push_does_not_post_by_default(self, client, edit, db_conn):
        edit(1, 1, "9")
        result = canvas_apply(db_conn, db.get_pending_changes(db_conn))
        assert result["ok"] is True
        client.bulk_push_grades.assert_called_once_with(1, {1: "9"})
        client.post_assignment_grades.assert_not_called()
        assert db.count_unreleased(result) == 1
        assert db.get_pending_changes(db_conn) == {}

    def test_post_limited_to_pushed_students(self, client, edit, db_conn):
        edit(1, 1, "9")
        edit(2, 1, "8")
        result = canvas_apply(
            db_conn, db.get_pending_changes(db_conn), post_grades=True
        )
        assert result["ok"] is True
        client.post_assignment_grades.assert_called_once_with(
            1, graded_only=True, only_student_ids=[1, 2]
        )
        assert self.rows(result)[-1]["action"] == "posted_to_students"
        assert db.count_unreleased(result) == 0

    @pytest.mark.parametrize(("other", "posted"), [("9", [1]), ("", None)])
    def test_clears_never_post(self, client, edit, db_conn, other, posted):
        edit(1, 1, other)
        edit(2, 1, "")
        canvas_apply(db_conn, db.get_pending_changes(db_conn), post_grades=True)
        assert client.bulk_push_grades.call_args.args == (1, {1: other, 2: ""})
        if posted is None:
            client.post_assignment_grades.assert_not_called()
        else:
            client.post_assignment_grades.assert_called_once_with(
                1, graded_only=True, only_student_ids=posted
            )

    def test_automatic_policy_never_posts(self, client, policies, edit, db_conn):
        policies[1] = False
        edit(1, 1, "9")
        result = canvas_apply(
            db_conn, db.get_pending_changes(db_conn), post_grades=True
        )
        client.post_assignment_grades.assert_not_called()
        assert db.count_unreleased(result) == 0

    def test_stored_policy_is_not_used(self, client, edit, db_conn):
        db_conn["canvas_assignments"].insert(
            {"canvas_id": 1, "name": "Homework 1", "post_manually": False}
        )
        edit(1, 1, "9")
        canvas_apply(
            db_conn,
            {"canvas_grades": db.get_pending_changes(db_conn)["canvas_grades"]},
            post_grades=True,
        )
        client.post_assignment_grades.assert_called_once()

    def test_failed_push_is_never_posted(self, client, edit, db_conn):
        edit(1, 1, "9")
        edit(1, 2, "8")
        client.bulk_push_grades.side_effect = [
            RuntimeError("Bulk fail"),
            SimpleNamespace(id=42),
        ]
        result = canvas_apply(
            db_conn, db.get_pending_changes(db_conn), post_grades=True
        )
        assert result["ok"] is False
        client.post_assignment_grades.assert_called_once_with(
            2, graded_only=True, only_student_ids=[1]
        )

    @pytest.mark.parametrize(
        "failure", [{"side_effect": RuntimeError("no job")}, {"return_value": None}]
    )
    def test_posting_failure_keeps_grades_pushed(self, client, edit, db_conn, failure):
        edit(1, 1, "9")
        client.post_assignment_grades.configure_mock(**failure)
        result = canvas_apply(
            db_conn, db.get_pending_changes(db_conn), post_grades=True
        )
        assert result["ok"] is False
        assert db.get_pending_changes(db_conn) == {}
        pushed, posted = self.rows(result)
        assert pushed["ok"] is True
        assert posted["ok"] is False
        assert "1 grade(s) pushed but not released to students" in str(posted["error"])
        assert "Canvas gradebook" in str(posted["error"])

    def test_failed_policy_read_sends_nothing(self, client, policies, edit, db_conn):
        edit(1, 1, "9")
        edit(1, 2, "8")
        pending = db.get_pending_changes(db_conn)
        policies[1] = None  # Canvas left the policy out
        result = canvas_apply(db_conn, pending, post_grades=True)
        failed, *_ = self.rows(result)
        assert (failed["canvas_assignment_id"], failed["ok"]) == (1, False)
        assert "posting policy" in str(failed["error"])
        client.bulk_push_grades.assert_called_once_with(2, {1: "8"})
        assert len(db.get_pending_changes(db_conn)["canvas_grades"]) == 1

    def test_failed_policy_read_at_preview_is_held(
        self, client, policies, edit, db_conn
    ):
        edit(1, 1, "9")
        edit(1, 2, "8")
        policies[1] = None
        pending = db.get_pending_changes(db_conn)
        preview = canvas_preview(db_conn, pending)
        to_push, held = db.hold_back_unapproved(pending, preview)
        assert [h["held"] for h in held] == [HELD_NOT_COMPARED]
        assert not db.can_be_approved(held[0])
        assert db.count_postable(to_push, preview) == 1

    def test_held_back_grades_not_counted(self, client, policies, edit, db_conn):
        policies[2] = False
        edit(1, 1, "9")
        edit(2, 1, "95")  # above points possible
        edit(3, 1, "")
        edit(1, 2, "8")  # posts automatically
        pending = db.get_pending_changes(db_conn)
        preview = canvas_preview(db_conn, pending)

        def count(**approved: bool) -> int:
            to_push, _ = db.hold_back_unapproved(pending, preview, **approved)
            return db.count_postable(to_push, preview)

        assert count() == 1
        assert count(allow_clears=True) == 1
        assert count(allow_over_points=True, allow_clears=True) == 2

    def test_became_manual_after_preview_is_not_posted(
        self, client, policies, edit, db_conn
    ):
        policies[2] = False
        edit(1, 1, "9")
        edit(1, 2, "8")
        pending = db.get_pending_changes(db_conn)
        preview = canvas_preview(db_conn, pending)
        policies[2] = True
        result = canvas_apply(db_conn, pending, post_grades=True, preview=preview)
        assert result["ok"] is True
        client.post_assignment_grades.assert_called_once_with(
            1, graded_only=True, only_student_ids=[1]
        )
        assert [r.get("unreleased") for r in self.rows(result)] == [0, None, 1]
        assert db.count_unreleased(result) == 1

    @pytest.mark.parametrize("approved", [True, False])
    def test_became_automatic_after_preview(
        self, client, policies, edit, db_conn, approved
    ):
        edit(1, 1, "9")
        pending = db.get_pending_changes(db_conn)
        preview = canvas_preview(db_conn, pending)
        policies[1] = False
        result = canvas_apply(db_conn, pending, post_grades=approved, preview=preview)
        client.post_assignment_grades.assert_not_called()
        assert result["ok"] is approved
        if approved:
            client.bulk_push_grades.assert_called_once()
        else:
            client.bulk_push_grades.assert_not_called()
            assert "now post automatically" in str(self.rows(result)[0]["error"])
            assert db.get_pending_changes(db_conn)
