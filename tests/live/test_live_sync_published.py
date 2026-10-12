"""Live test: an omitted ``published`` leaves live content as it is."""

from __future__ import annotations

__docformat__ = "google"

import contextlib
from pathlib import Path
from uuid import uuid4

import pytest
from live_course import CONFIG_PATH, SURVEY_TITLE
from typer.testing import CliRunner

from cass.actions.config import get_config, set_config_path
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()


@pytest.mark.usefixtures("practice_cli_client")
def test_sync_without_published_keeps_content_published(
    practice: CanvasClient, tmp_path: Path
):
    tag = uuid4().hex[:8]
    name = f"cass-live published {tag}"
    toml = tmp_path / "cass.toml"
    module = practice.create_module(name)
    assignment = practice.create_assignment(name, submission_types=["none"])
    try:
        practice.publish("modules", module.id)
        practice.publish("assignments", assignment.id)
        cfg = get_config()
        toml.write_text(
            f"""[canvas]
base_url = "{cfg.canvas_base_url}"
course_id = {practice.course_id}
time_zone = "{practice.time_zone}"

[[canvas.modules]]
name = "{name}"

[[canvas.assignments]]
name = "{name}"
"""
        )

        result = runner.invoke(
            app, ["--config", str(toml), "canvas", "sync", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert practice.get_module(module.id).published
        assert practice.get_assignment(assignment.id).published
    finally:
        with contextlib.suppress(Exception):
            practice.delete_module(module.id)
        with contextlib.suppress(Exception):
            practice.delete_assignment(assignment.id)
        set_config_path(CONFIG_PATH)


@pytest.mark.usefixtures("practice_cli_client")
def test_quiz_update_without_settings_changes_nothing(
    practice: CanvasClient, tmp_path: Path
):
    quiz = practice.resolve_quiz(SURVEY_TITLE)
    assert quiz.published
    path = tmp_path / "q.toml"
    path.write_text(f'title = "{quiz.title}"\ntype = "{quiz.quiz_type}"\n')

    # A dry run: if omitted settings still counted, it would plan a PUT.
    result = runner.invoke(
        app, ["canvas", "quizzes", "update", str(quiz.id), "--from", str(path)]
    )

    assert result.exit_code == 0, result.output
    assert "No changes" in result.stderr
