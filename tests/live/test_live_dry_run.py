"""Live test: raw API reads and dry-run writes against the practice course."""

from __future__ import annotations

__docformat__ = "google"

import json

import pytest
from typer.testing import CliRunner

from cass.actions.config import get_config
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()


def test_api_and_dry_run_leave_modules_unchanged(
    practice: CanvasClient, monkeypatch: pytest.MonkeyPatch
):
    # The CLI looks for credentials beside tests/live/cass.toml, but live
    # credentials sit in the repository root, so build the client from the
    # practice fixture's auth.
    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            get_config().canvas_base_url,
            course_id=practice.course_id,
            auth=practice.auth,
            time_zone=practice.time_zone,
            dry_run=dry_run,
        ),
    )
    before = sorted(m.id for m in practice.list_modules())

    listed = runner.invoke(
        app, ["canvas", "api", "GET", "/courses/{course}/modules", "--all"]
    )
    assert listed.exit_code == 0, listed.output
    assert sorted(m["id"] for m in json.loads(listed.stdout)) == before

    probe = runner.invoke(
        app, ["canvas", "modules", "create", "dry-run probe", "--dry-run"]
    )
    assert probe.exit_code == 0, probe.output
    assert f"POST /courses/{practice.course_id}/modules" in probe.stdout

    after = practice.list_modules()
    assert sorted(m.id for m in after) == before
    assert all(m.name != "dry-run probe" for m in after)
