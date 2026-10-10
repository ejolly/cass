"""Live test: file and folder lifecycle on the practice course."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from cass.actions.config import get_config
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def practice_cli_client(practice: CanvasClient, monkeypatch: pytest.MonkeyPatch):
    """Point the CLI at the practice course using the fixture's credentials."""
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


def _run(*args: str):
    result = runner.invoke(app, ["canvas", "files", *args])
    assert result.exit_code == 0, result.output
    return result


def test_file_lifecycle(practice: CanvasClient, tmp_path: Path):
    top = f"cass-live-files-{uuid4().hex[:8]}"
    local = tmp_path / "reading.txt"
    local.write_bytes(b"cass live file test\n")

    try:
        _run(
            "upload",
            str(local),
            "--folder",
            f"{top}/week1",
            "--name",
            "reading.txt",
            "--unpublished",
        )
        week1 = practice.find_folder(f"{top}/week1")
        assert week1 is not None
        files = practice.list_files(week1.id)
        assert [f.display_name for f in files] == ["reading.txt"]
        assert files[0].locked is True
        file_id = files[0].id

        skipped = _run(
            "upload",
            str(local),
            "--folder",
            f"{top}/week1",
            "--name",
            "reading.txt",
            "--on-duplicate",
            "skip",
        )
        assert "Skipped:" in skipped.stdout
        assert len(practice.list_files(week1.id)) == 1

        _run("rename", str(file_id), "renamed.txt")
        assert practice.resolve_file(str(file_id)).display_name == "renamed.txt"

        _run("mv", str(file_id), f"{top}/week2")
        week2 = practice.find_folder(f"{top}/week2")
        assert week2 is not None
        assert practice.resolve_file(str(file_id)).folder_id == week2.id

        _run("publish", str(file_id))
        assert practice.resolve_file(str(file_id)).locked is False

        _run("delete", str(file_id), "--yes")
        assert all(f.id != file_id for f in practice.list_files(week2.id))
        _run("folders", "delete", top, "--force", "--yes")
        assert practice.find_folder(top) is None
    finally:
        leftover = practice.find_folder(top)
        if leftover is not None:
            practice.delete_folder(leftover.id, force=True)
