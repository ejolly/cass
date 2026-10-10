"""``people list`` enrollment filters and the Enrolled column."""

from __future__ import annotations

__docformat__ = "google"

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from cass.actions.enrollments import ALL_ENROLLMENT_STATES
from cass.apis.canvas.schema import CanvasEnrollment, CanvasUser
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
