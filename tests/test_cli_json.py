"""``--json`` on Canvas list and show commands: JSON Lines on stdout only."""

from __future__ import annotations

__docformat__ = "google"

import json
from unittest.mock import MagicMock

import pytest
from click.testing import Result
from typer.testing import CliRunner

from cass.apis.canvas.schema import (
    CanvasAnnouncement,
    CanvasAssignmentGroup,
    CanvasAssignmentResponse,
    CanvasCalendarEvent,
    CanvasFile,
    CanvasFolder,
    CanvasModule,
    CanvasModuleItem,
    CanvasQuiz,
    CanvasQuizQuestion,
    CanvasTab,
    CanvasUser,
)
from cass.cli import app

runner = CliRunner()

QUESTION_HTML = '<p>What are you <b>hoping</b>?</p><img src="x.png">'


def lines(result: Result) -> list[dict]:
    return [json.loads(line) for line in result.stdout.splitlines()]


@pytest.fixture
def json_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.time_zone = "America/Los_Angeles"
    c.list_users.return_value = [CanvasUser(id=1, name="Ann Lee", email="ann@x.edu")]
    c.list_folders.return_value = [
        CanvasFolder(id=2, name="course files", full_name="course files")
    ]
    c.list_files.return_value = [
        CanvasFile(
            id=15, display_name="notes.txt", content_type="text/plain", folder_id=2
        )
    ]
    c.list_announcements.return_value = [CanvasAnnouncement(id=13, title="Welcome")]
    c.list_tabs.return_value = [
        CanvasTab(id="context_external_tool_5826", label="Media Gallery")
    ]
    module = CanvasModule(id=5, name="Week 1", items_count=3)
    c.list_modules.return_value = [module]
    c.resolve_module.return_value = module
    c.list_module_items.return_value = [CanvasModuleItem(id=8, title="Read")]
    assignment = CanvasAssignmentResponse(id=7, name="HW1")
    c.list_assignments.return_value = [assignment]
    c.resolve_assignment.return_value = assignment
    c.list_assignment_groups.return_value = [
        CanvasAssignmentGroup(id=9, name="Labs", position=1)
    ]
    c.list_quizzes.return_value = [CanvasQuiz(id=3, title="Quiz A")]
    c.resolve_quiz.return_value = CanvasQuiz(id=3, title="Quiz A")
    c.list_quiz_questions.return_value = (
        [
            CanvasQuizQuestion(
                id=1,
                position=1,
                question_type="essay_question",
                question_text=QUESTION_HTML,
            )
        ],
        False,
    )
    c.list_calendar_events.return_value = [
        CanvasCalendarEvent(id=11, title="Office hours")
    ]
    monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
    monkeypatch.setattr("cass.cli.canvas._common.client", lambda **_: c)
    return c


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        (("people",), "name", "Ann Lee"),
        (("announcements",), "title", "Welcome"),
        (("tabs",), "id", "context_external_tool_5826"),
        (("assignments",), "name", "HW1"),
        (("assignments", "groups"), "name", "Labs"),
        (("quizzes",), "title", "Quiz A"),
        (("calendar",), "title", "Office hours"),
    ],
)
def test_list_json(json_client: MagicMock, path: tuple[str, ...], key: str, value: str):
    result = runner.invoke(app, ["canvas", *path, "list", "--json"])
    assert result.exit_code == 0, result.output
    assert lines(result)[0][key] == value


def test_files_list_json_kinds(json_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "files", "list", "--json"])
    assert result.exit_code == 0, result.output
    records = lines(result)
    assert [r["kind"] for r in records] == ["folder", "file"]
    assert records[1]["content-type"] == "text/plain"


def test_modules_list_json_has_count_no_items(json_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "modules", "list", "--json"])
    assert result.exit_code == 0, result.output
    (record,) = lines(result)
    assert record["items_count"] == 3
    assert "items" not in record
    json_client.list_module_items.assert_not_called()


def test_quizzes_show_json(json_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "quizzes", "show", "3", "--json"])
    assert result.exit_code == 0, result.output
    (obj,) = lines(result)
    assert obj["questions"][0]["question_text"] == QUESTION_HTML
    assert obj["questions_source"] == "questions"
    json_client.list_assignment_groups.assert_not_called()


def test_quizzes_show_json_statistics_fallback(json_client: MagicMock) -> None:
    questions, _ = json_client.list_quiz_questions.return_value
    json_client.list_quiz_questions.return_value = (questions, True)
    result = runner.invoke(app, ["canvas", "quizzes", "show", "3", "--json"])
    assert result.exit_code == 0, result.output
    (obj,) = lines(result)
    assert obj["questions_source"] == "statistics"


def test_modules_show_json(json_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "modules", "show", "5", "--json"])
    assert result.exit_code == 0, result.output
    (obj,) = lines(result)
    assert obj["name"] == "Week 1"
    assert obj["items"][0]["title"] == "Read"


def test_assignments_show_json(json_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "assignments", "show", "7", "--json"])
    assert result.exit_code == 0, result.output
    (obj,) = lines(result)
    assert obj["id"] == 7


@pytest.mark.parametrize(
    "args",
    [
        ["people", "list", "--json", "--csv", "x.csv"],
        ["submissions", "list", "HW1", "--json", "--csv", "x.csv"],
        ["quizzes", "list", "--json", "--save", "x.md"],
        ["quizzes", "show", "3", "--json", "--csv", "x.csv"],
    ],
)
def test_json_rejects_file_outputs(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    factory = MagicMock()
    monkeypatch.setattr("cass.cli.canvas._common.client", factory)
    result = runner.invoke(app, ["canvas", *args])
    assert result.exit_code == 2
    factory.assert_not_called()


def test_json_empty_list_prints_nothing(json_client: MagicMock) -> None:
    json_client.list_quizzes.return_value = []
    result = runner.invoke(app, ["canvas", "quizzes", "list", "--json"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_json_keeps_unicode(json_client: MagicMock) -> None:
    json_client.list_quizzes.return_value = [CanvasQuiz(id=3, title="Café ✓")]
    result = runner.invoke(app, ["canvas", "quizzes", "list", "--json"])
    assert lines(result)[0]["title"] == "Café ✓"
