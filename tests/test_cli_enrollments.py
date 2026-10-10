"""``people list`` enrollment filters and the Enrolled column."""

from __future__ import annotations

__docformat__ = "google"

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from cass.actions.enrollments import ALL_ENROLLMENT_STATES
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasEnrollment,
    CanvasStudentResponse,
    CanvasSubmissionResponse,
    CanvasUser,
)
from cass.cli import app

runner = CliRunner()


@pytest.fixture
def people_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.time_zone = "America/Los_Angeles"
    c.list_users.return_value = [
        CanvasUser(id=5, name="Ann Lee", sortable_name="Lee, Ann"),
        CanvasUser(id=6, name="Ben Ray", sortable_name="Ray, Ben"),
    ]
    c.list_enrollments.return_value = [
        CanvasEnrollment(
            id=1,
            user_id=5,
            type="StudentEnrollment",
            created_at="2026-10-02T17:00:00Z",
        ),
        CanvasEnrollment(
            id=2,
            user_id=6,
            type="StudentEnrollment",
            created_at="2026-09-01T00:00:00Z",
        ),
    ]
    monkeypatch.setattr("cass.cli.canvas._common.client", lambda *a, **k: c)
    monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
    return c


def test_people_enrolled_column(people_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "people", "list"])
    assert result.exit_code == 0, result.output
    assert "Enrolled" in result.stdout
    assert "2026-10-02 10:00" in result.stdout
    people_client.list_enrollments.assert_called_once_with(
        enrollment_type=None, states=ALL_ENROLLMENT_STATES, include_scores=False
    )


def test_people_enrolled_after_filters(people_client: MagicMock) -> None:
    result = runner.invoke(
        app, ["canvas", "people", "list", "--enrolled-after", "2026-10-01"]
    )
    assert result.exit_code == 0, result.output
    assert "Ann" in result.stdout
    assert "Ben" not in result.stdout


def test_people_state_passes_enrollment_states(people_client: MagicMock) -> None:
    result = runner.invoke(
        app, ["canvas", "people", "list", "--state", "active", "--state", "completed"]
    )
    assert result.exit_code == 0, result.output
    people_client.list_users.assert_called_once_with(states=["active", "completed"])
    bad = runner.invoke(app, ["canvas", "people", "list", "--state", "bogus"])
    assert bad.exit_code == 2


def test_people_json_has_enrolled_at(people_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "people", "list", "--json"])
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    ann = next(r for r in rows if r["id"] == 5)
    assert ann["enrolled_at"] == "2026-10-02T17:00:00Z"


# --- submissions list ---------------------------------------------------------


@pytest.fixture
def submissions_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.time_zone = "America/Los_Angeles"
    c.resolve_assignment.return_value = CanvasAssignmentResponse(id=7, name="HW1")
    c.list_submissions.return_value = [
        CanvasSubmissionResponse(
            user_id=6,
            excused=True,
            workflow_state="unsubmitted",
            user=CanvasStudentResponse(id=6, name="Ben Ray", sortable_name="Ray, Ben"),
        ),
        CanvasSubmissionResponse(
            user_id=5,
            late=True,
            workflow_state="submitted",
            submitted_at="2026-10-02T17:00:00Z",
            late_policy_status="late",
            user=CanvasStudentResponse(id=5, name="Ann Lee", sortable_name="Lee, Ann"),
        ),
    ]
    factory = MagicMock(return_value=c)
    monkeypatch.setattr("cass.cli.canvas._common.client", factory)
    monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
    c.factory = factory
    return c


def test_submissions_list_table(submissions_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "submissions", "list", "HW1"])
    assert result.exit_code == 0, result.output
    assert "Submissions: HW1" in result.stdout
    assert "Ann" in result.stdout
    assert "Late policy" in result.stdout
    submissions_client.list_submissions.assert_called_once_with(7, include_user=True)


def test_submissions_list_student_filter(submissions_client: MagicMock) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "list", "HW1", "--student", "6"]
    )
    assert result.exit_code == 0, result.output
    assert "Ben" in result.stdout
    assert "Ann" not in result.stdout
    bad = runner.invoke(
        app, ["canvas", "submissions", "list", "HW1", "--student", "42"]
    )
    assert bad.exit_code == 1
    assert "42" in str(bad.exception)


def test_submissions_list_json(submissions_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "submissions", "list", "HW1", "--json"])
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    for key in (
        "late",
        "missing",
        "excused",
        "late_policy_status",
        "workflow_state",
        "submitted_at",
        "user",
    ):
        assert key in rows[0]


def test_bare_submissions_shows_help(submissions_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "submissions"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    submissions_client.factory.assert_not_called()
