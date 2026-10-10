"""Live test: declared module items round trip through ``canvas sync``."""

from __future__ import annotations

__docformat__ = "google"

import contextlib
import re
from pathlib import Path
from uuid import uuid4

import pytest
from live_course import CONFIG_PATH
from typer.testing import CliRunner

from cass.actions.config import get_config, set_config_path
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()


def _write_config(path: Path, practice: CanvasClient, module: str, items: str) -> None:
    """Write a cass.toml for the practice course with one module and *items*."""
    cfg = get_config()
    path.write_text(
        f"""[canvas]
base_url = "{cfg.canvas_base_url}"
course_id = {practice.course_id}
time_zone = "{practice.time_zone}"

[[canvas.modules]]
name = "{module}"
{items}
"""
    )


def _sync(toml: Path, *flags: str) -> str:
    result = runner.invoke(app, ["--config", str(toml), "canvas", "sync", *flags])
    assert result.exit_code == 0, result.output
    return result.stdout


def _has_row(output: str, action: str) -> bool:
    """True when a sync table row starts with *action*."""
    return re.search(rf"^\s*{action}\b", output, re.MULTILINE) is not None


def _layout(practice: CanvasClient, module_id: int) -> list[tuple[str, str, int]]:
    return [(i.type, i.title, i.indent) for i in practice.list_module_items(module_id)]


@pytest.mark.usefixtures("practice_cli_client")
def test_module_items_sync_round_trip(practice: CanvasClient, tmp_path: Path):
    tag = uuid4().hex[:8]
    module_name = f"cass-live items {tag}"
    second_module_name = f"cass-live items {tag} b"
    folder_path = f"cass-live-items-{tag}"
    assignment_name = f"cass-live items {tag}"
    file_path = f"{folder_path}/reading.txt"
    toml = tmp_path / "cass.toml"
    source = tmp_path / "reading.txt"
    source.write_bytes(b"v1\n")

    assignment = practice.create_assignment(assignment_name, submission_types=["none"])
    try:
        # 1. Create everything in declared order.
        _write_config(
            toml,
            practice,
            module_name,
            f"""
[[canvas.modules.items]]
type = "SubHeader"
title = "Readings"

[[canvas.modules.items]]
type = "ExternalUrl"
title = "Course site"
url = "https://example.com/cass-live/café"

[[canvas.modules.items]]
type = "Assignment"
title = "{assignment_name}"

[[canvas.modules.items]]
type = "File"
file = "{file_path}"
source = "reading.txt"
published = true
indent = 1
""",
        )
        _sync(toml, "--apply")

        module = next(m for m in practice.list_modules() if m.name == module_name)
        items = practice.list_module_items(module.id)
        assert _layout(practice, module.id) == [
            ("SubHeader", "Readings", 0),
            ("ExternalUrl", "Course site", 0),
            ("Assignment", assignment_name, 0),
            ("File", "reading.txt", 1),
        ]
        assert [i.position for i in items] == [1, 2, 3, 4]
        folder = practice.find_folder(folder_path)
        assert folder is not None
        (file,) = practice.list_files(folder.id)
        file_item = items[3]
        assert file_item.content_id == file.id
        assert file_item.published is True
        assert file.locked is False
        # Canvas stores the URL percent-encoded; it must still match.
        assert items[1].external_url == "https://example.com/cass-live/caf%C3%A9"
        assert not _has_row(_sync(toml), "create")

        # 2. Reorder, retitle and drop an item with --prune.
        step_2_items = f"""
[[canvas.modules.items]]
type = "File"
file = "{file_path}"
source = "reading.txt"
published = true
indent = 1

[[canvas.modules.items]]
type = "SubHeader"
title = "Week 1 readings"

[[canvas.modules.items]]
type = "Assignment"
title = "{assignment_name}"
"""
        _write_config(toml, practice, module_name, step_2_items)
        _sync(toml, "--apply", "--prune")

        items = practice.list_module_items(module.id)
        assert [(i.type, i.title) for i in items] == [
            ("File", "reading.txt"),
            ("SubHeader", "Week 1 readings"),
            ("Assignment", assignment_name),
        ]
        assert [i.position for i in items] == [1, 2, 3]
        assert all(i.type != "ExternalUrl" for i in items)

        # 3. A changed source size overwrites the file. Canvas makes a new
        # file (new id) and re-points the item to it.
        item_id = items[0].id
        source.write_bytes(b"v1\nmore text\n")
        dry_run = _sync(toml)
        assert _has_row(dry_run, "upload")
        assert not _has_row(dry_run, "create")

        _sync(toml, "--apply")
        (file_after,) = practice.list_files(folder.id)
        assert file_after.size == source.stat().st_size
        file_item = practice.list_module_items(module.id)[0]
        assert file_item.id == item_id
        assert file_item.content_id == file_after.id

        # 4. Nothing left to do.
        settled = _sync(toml)
        for action in ("create", "update", "move", "remove", "upload"):
            assert not _has_row(settled, action)
        assert _has_row(settled, "keep")
        assert "kept" in settled
        assert "no Canvas writes needed" in settled

        # 5. Overwrite the file and link it from a new module in one sync:
        # the create must use the new file's id.
        source.write_bytes(b"v1\nmore text\nand more\n")
        _write_config(
            toml,
            practice,
            module_name,
            step_2_items
            + f"""
[[canvas.modules]]
name = "{second_module_name}"

[[canvas.modules.items]]
type = "File"
file = "{file_path}"
source = "reading.txt"
""",
        )
        _sync(toml, "--apply")
        (file_now,) = practice.list_files(folder.id)
        assert file_now.size == source.stat().st_size
        second = next(
            m for m in practice.list_modules() if m.name == second_module_name
        )
        (second_item,) = practice.list_module_items(second.id)
        assert second_item.content_id == file_now.id
        assert practice.list_module_items(module.id)[0].content_id == file_now.id
        settled = _sync(toml)
        for action in ("create", "upload"):
            assert not _has_row(settled, action)
    finally:
        # Each cleanup step runs even if an earlier one fails
        with contextlib.suppress(Exception):
            for module in practice.list_modules():
                if module.name in (module_name, second_module_name):
                    practice.delete_module(module.id)
        with contextlib.suppress(Exception):
            folder = practice.find_folder(folder_path)
            if folder is not None:
                practice.delete_folder(folder.id, force=True)
        with contextlib.suppress(Exception):
            practice.delete_assignment(assignment.id)
        set_config_path(CONFIG_PATH)
