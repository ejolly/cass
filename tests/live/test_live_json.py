"""Live test: read-only smoke test of every `list --json` on the practice course."""

from __future__ import annotations

__docformat__ = "google"

import json

import pytest
from live_course import QUIZ_TITLE
from typer.testing import CliRunner

from cass.cli import app

runner = CliRunner()


pytestmark = pytest.mark.usefixtures("practice_cli_client")


@pytest.mark.parametrize(
    "path",
    [
        ("people",),
        ("modules",),
        ("assignments",),
        ("assignments", "groups"),
        ("quizzes",),
        ("calendar",),
        ("files",),
        ("files", "folders"),
        ("announcements",),
        ("tabs",),
    ],
    ids="/".join,
)
def test_list_json_smoke(path: tuple[str, ...]):
    result = runner.invoke(app, ["canvas", *path, "list", "--json"])
    assert result.exit_code == 0, result.output

    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    for record in records:
        assert isinstance(record, dict)
        assert "id" in record
    if path == ("quizzes",):
        assert records, "the seed script creates quizzes"
    if path == ("files",):
        assert all(record["kind"] in {"folder", "file"} for record in records)


def test_quiz_show_json_live():
    result = runner.invoke(app, ["canvas", "quizzes", "show", QUIZ_TITLE, "--json"])
    assert result.exit_code == 0, result.output

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    quiz = json.loads(lines[0])
    assert quiz["title"] == QUIZ_TITLE
    assert quiz["questions_source"] in {"questions", "statistics"}
    assert quiz["questions"]
