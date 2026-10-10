"""``quizzes update --questions``: dry run by default, ``--apply``, ``--prune``."""

from __future__ import annotations

__docformat__ = "google"

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx
import pytest
from typer.testing import CliRunner

from cass.actions.config import reset_config, set_config_path
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()
API = "/api/v1"
QUIZ_PATH = "/courses/1/quizzes/20"

CASS_TOML = """\
[canvas]
base_url = "https://canvas.example.com"
course_id = 1
time_zone = "America/Los_Angeles"
"""

QUIZ = {"id": 20, "title": "Survey", "quiz_type": "survey", "allowed_attempts": 1}


def _question(question_id: int, position: int, text: str, group_id=None) -> dict:
    return {
        "id": question_id,
        "question_name": f"Q{question_id}",
        "question_text": f"<p>{text}</p>",
        "question_type": "multiple_choice_question",
        "points_possible": 0,
        "position": position,
        "quiz_group_id": group_id,
        "answers": [
            {"id": 1, "text": "yes", "weight": 100},
            {"id": 2, "text": "no", "weight": 0},
        ],
    }


QUESTIONS = [
    _question(11, 1, "Intro"),
    _question(12, 2, "Second", group_id=5),
    _question(13, 3, "Third", group_id=5),
]


@dataclass
class FakeCanvas:
    """Recorded requests plus the per-test routes."""

    sent: list[httpx.Request] = field(default_factory=list)
    routes: dict[str, object] = field(default_factory=dict)

    @property
    def writes(self) -> list[httpx.Request]:
        return [r for r in self.sent if r.method != "GET"]

    def write_lines(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.writes]


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture
def canvas(tmp_path, monkeypatch) -> FakeCanvas:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cass.toml").write_text(CASS_TOML)
    fake = FakeCanvas(
        routes={
            QUIZ_PATH: QUIZ,
            "/courses/1/quizzes": [QUIZ],
            f"{QUIZ_PATH}/questions": QUESTIONS,
            f"{QUIZ_PATH}/groups/5": {"id": 5, "name": "Pair", "pick_count": 1},
            f"{QUIZ_PATH}/submissions": {"quiz_submissions": []},
            "/courses/1/users": [],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        fake.sent.append(request)
        path = request.url.path.removeprefix(API)
        if request.method == "GET":
            body = fake.routes.get(path, [])
            if isinstance(body, httpx.Response):
                return body
            return httpx.Response(200, json=body)
        if request.method == "POST" and path in fake.routes:
            return httpx.Response(200, json=fake.routes[path])
        if request.method == "POST" and path.endswith("/questions"):
            return httpx.Response(200, json={"id": 900})
        if request.method == "PUT" and "/questions/" in path:
            return httpx.Response(200, json={"id": int(path.rsplit("/", 1)[1])})
        if request.method == "PUT" and path == QUIZ_PATH:
            return httpx.Response(200, json=QUIZ)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(handler),
            time_zone="America/Los_Angeles",
            dry_run=dry_run,
        ),
    )
    return fake


@pytest.fixture
def quiz_file(canvas, tmp_path) -> Callable[..., str]:
    """Export the mocked quiz to q.toml, apply text edits, return its name."""

    def make(*edits: tuple[str, str]) -> str:
        result = runner.invoke(
            app, ["canvas", "quizzes", "export", "20", "-o", "q.toml"]
        )
        assert result.exit_code == 0, result.output
        path = tmp_path / "q.toml"
        text = path.read_text()
        for old, new in edits:
            assert old in text, f"{old!r} not in exported file:\n{text}"
            text = text.replace(old, new, 1)
        path.write_text(text)
        canvas.sent.clear()
        return "q.toml"

    return make


def _update(*flags: str):
    return runner.invoke(
        app, ["canvas", "quizzes", "update", "20", "--from", "q.toml", *flags]
    )


def test_questions_default_is_dry_run(canvas, quiz_file):
    quiz_file(("Intro", "Intro edited"))

    result = _update("--questions")

    assert result.exit_code == 0, result.output
    assert canvas.writes == []
    assert "update question 11" in result.stdout
    request_line = re.search(
        r"^\s*PUT /courses/1/quizzes/20/questions/11", result.stdout, re.MULTILINE
    )
    assert request_line
    assert result.stdout.index("update question 11") < request_line.start()
    assert "Dry run — use --apply" in result.stderr


def test_questions_explicit_dry_run_sends_nothing(canvas, quiz_file):
    quiz_file(("Intro", "Intro edited"))

    result = _update("--questions", "--dry-run", "--prune")

    assert result.exit_code == 0, result.output
    assert canvas.writes == []


def test_questions_apply_sends_changes(canvas, quiz_file):
    quiz_file(("Intro", "Intro edited"))

    result = _update("--questions", "--apply")

    assert result.exit_code == 0, result.output
    lines = canvas.write_lines()
    assert f"PUT {API}{QUIZ_PATH}/questions/11" in lines
    # No settings changed, so the last PUT is the quiz re-save.
    assert lines[-1] == f"PUT {API}{QUIZ_PATH}"
    assert "Updated: Survey" in result.stdout


def test_questions_apply_sends_settings_changes(canvas, quiz_file):
    quiz_file(("attempts = 1", "attempts = 3"))

    result = _update("--questions", "--apply")

    assert result.exit_code == 0, result.output
    assert "update settings" in result.stdout
    assert canvas.write_lines()[0] == f"PUT {API}{QUIZ_PATH}"


def test_questions_prune_deletes_only_with_prune(canvas, quiz_file, tmp_path):
    quiz_file()
    path = tmp_path / "q.toml"
    blocks = re.split(r"(?=^\[\[questions\]\])", path.read_text(), flags=re.MULTILINE)
    kept = [block for block in blocks if "Third" not in block]
    assert len(kept) == len(blocks) - 1
    path.write_text("".join(kept))

    result = _update("--questions", "--apply")
    assert result.exit_code == 0, result.output
    assert not [w for w in canvas.write_lines() if w.startswith("DELETE")]

    canvas.sent.clear()
    result = _update("--questions", "--apply", "--prune")
    assert result.exit_code == 0, result.output
    assert f"DELETE {API}{QUIZ_PATH}/questions/13" in canvas.write_lines()


@pytest.mark.parametrize("flag", ["--apply", "--prune"])
def test_apply_or_prune_without_questions_exits_2(canvas, quiz_file, flag):
    quiz_file()

    result = _update(flag)

    assert result.exit_code == 2, result.output
    assert "--apply and --prune need --questions." in result.output
    assert canvas.writes == []


def test_questions_apply_and_dry_run_exits_2(canvas, quiz_file):
    quiz_file()

    result = _update("--questions", "--apply", "--dry-run")

    assert result.exit_code == 2, result.output
    assert "--apply and --dry-run cannot be combined." in result.output
    assert canvas.writes == []


def test_plain_update_unchanged(canvas, quiz_file):
    quiz_file(("attempts = 1", "attempts = 3"))

    result = _update()

    assert result.exit_code == 0, result.output
    assert canvas.write_lines() == [f"PUT {API}{QUIZ_PATH}"]
    assert "Updated:" in result.stdout
    assert not [r for r in canvas.sent if r.url.path.endswith("/questions")]


def _answers_changed(quiz_file) -> None:
    quiz_file(('text = "yes"', 'text = "maybe"'))


def test_student_attempt_warns_and_marks_answers(canvas, quiz_file):
    canvas.routes["/courses/1/users"] = [{"id": 1, "name": "Student"}]
    canvas.routes[f"{QUIZ_PATH}/submissions"] = {
        "quiz_submissions": [{"id": 1, "user_id": 1, "workflow_state": "complete"}]
    }
    _answers_changed(quiz_file)

    result = _update("--questions", "--apply")

    assert result.exit_code == 0, result.output
    assert "Warning:" in result.stderr
    assert "old version" in result.stderr
    update_line = next(
        line for line in result.stdout.splitlines() if "update question" in line
    )
    assert "(answers replaced: existing responses may lose their answer link)" in (
        update_line
    )
    assert canvas.writes


def test_teacher_preview_does_not_warn(canvas, quiz_file):
    canvas.routes["/courses/1/users"] = [{"id": 1, "name": "Student"}]
    canvas.routes[f"{QUIZ_PATH}/submissions"] = {
        "quiz_submissions": [{"id": 1, "user_id": 9, "workflow_state": "complete"}]
    }
    _answers_changed(quiz_file)

    result = _update("--questions")

    assert result.exit_code == 0, result.output
    assert "Warning:" not in result.stderr
    assert "answers replaced" not in result.stdout


def test_questions_unknown_id_sends_nothing(canvas, quiz_file, tmp_path):
    quiz_file(("Intro", "Intro edited"))
    path = tmp_path / "q.toml"
    path.write_text(path.read_text().replace("id = 11", "id = 999", 1))

    result = _update("--questions", "--apply")

    assert result.exit_code == 1, result.output
    assert "999" in str(result.exception)
    assert canvas.writes == []


def test_questions_statistics_fallback_sends_nothing(canvas, quiz_file):
    quiz_file(("Intro", "Intro edited"))
    canvas.routes[f"{QUIZ_PATH}/questions"] = httpx.Response(
        403, json={"message": "unauthorized"}
    )
    canvas.routes[f"{QUIZ_PATH}/statistics"] = {
        "quiz_statistics": [{"question_statistics": []}]
    }

    result = _update("--questions", "--apply")

    assert result.exit_code == 1, result.output
    assert "statistics" in str(result.exception)
    assert canvas.writes == []


def test_apply_with_nothing_to_change_says_so(canvas, quiz_file):
    quiz_file()

    result = _update("--questions", "--apply")

    assert result.exit_code == 0, result.output
    assert "No changes for Survey" in result.stderr
    assert "Updated:" not in result.stdout
    assert canvas.writes == []


def test_student_attempt_warns_in_dry_run(canvas, quiz_file):
    canvas.routes["/courses/1/users"] = [{"id": 1, "name": "Student"}]
    canvas.routes[f"{QUIZ_PATH}/submissions"] = {
        "quiz_submissions": [{"id": 1, "user_id": 1, "workflow_state": "complete"}]
    }
    _answers_changed(quiz_file)

    result = _update("--questions")

    assert result.exit_code == 0, result.output
    assert "Warning:" in result.stderr
    assert canvas.writes == []


def test_long_plan_lines_do_not_wrap(canvas, quiz_file, monkeypatch):
    from cass.cli.canvas import _common, quizzes

    canvas.routes["/courses/1/users"] = [{"id": 1, "name": "Student"}]
    canvas.routes[f"{QUIZ_PATH}/submissions"] = {
        "quiz_submissions": [{"id": 1, "user_id": 1, "workflow_state": "complete"}]
    }
    _answers_changed(quiz_file)
    monkeypatch.setenv("COLUMNS", "80")
    for module in (_common, quizzes):
        monkeypatch.setattr(module, "console", _common.Console())

    result = _update("--questions")

    assert result.exit_code == 0, result.output
    marker = "(answers replaced: existing responses may lose their answer link)"
    update_lines = [x for x in result.stdout.splitlines() if "update question" in x]
    assert len(update_lines) == 1
    assert marker in update_lines[0]
    assert len(update_lines[0]) > 80


def _questions_cmd(canvas, *flags: str):
    # The shared group fixture has no position; place it after question 11.
    canvas.routes[f"{QUIZ_PATH}/groups/5"] = {
        "id": 5,
        "name": "Pair",
        "pick_count": 1,
        "position": 2,
    }
    return runner.invoke(app, ["canvas", "quizzes", "questions", "20", *flags])


def test_questions_table_in_quiz_order(canvas):
    canvas.routes[f"{QUIZ_PATH}/questions"] = [
        _question(11, 1, "Intro " + "x" * 80),
        *QUESTIONS[1:],
    ]

    result = _questions_cmd(canvas)

    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "Questions: Survey" in out
    row_ids = re.findall(r"^(\d+) │", out, re.MULTILINE)
    assert row_ids == ["11", "12", "13"]
    assert "Pair" in out
    assert "<p>" not in out
    assert "Intro " + "x" * 54 in out  # 60 characters
    assert "x" * 55 not in out


def test_export_writes_groups_and_ids(canvas, tmp_path):
    canvas.routes[f"{QUIZ_PATH}/groups/5"] = {
        "id": 5,
        "name": "Pair",
        "pick_count": 1,
        "question_points": 2,
        "position": 2,
    }

    result = runner.invoke(app, ["canvas", "quizzes", "export", "20", "-o", "q.toml"])

    assert result.exit_code == 0, result.output
    from cass.actions.quizzes import GroupSpec, load_quiz_file

    spec = load_quiz_file(tmp_path / "q.toml")
    assert spec.groups == [GroupSpec("Pair", 1, 2.0)]
    assert [(q.id, q.group) for q in spec.questions] == [
        (11, ""),
        (12, "Pair"),
        (13, "Pair"),
    ]
    quiz_gets = [r for r in canvas.sent if r.url.path == f"{API}{QUIZ_PATH}"]
    assert len(quiz_gets) == 1


def test_questions_json_lines(canvas):
    result = _questions_cmd(canvas, "--json")

    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r["id"] for r in rows] == [11, 12, 13]
    assert "<p>" in rows[0]["question_text"]


def _preview_routes(canvas) -> None:
    canvas.routes[f"{QUIZ_PATH}/submissions"] = {
        "quiz_submissions": [{"id": 77, "user_id": 1}]
    }
    canvas.routes["/quiz_submissions/77/questions"] = {
        "quiz_submission_questions": [QUESTIONS[2], QUESTIONS[0]]
    }


def test_preview_prints_drawn_questions(canvas):
    _preview_routes(canvas)

    result = runner.invoke(app, ["canvas", "quizzes", "preview", "20"])

    assert result.exit_code == 0, result.output
    assert "Preview: Survey" in result.stdout
    assert result.stdout.index("Third") < result.stdout.index("Intro")
    assert "differ" in result.stderr


def test_preview_json_in_order(canvas):
    _preview_routes(canvas)

    result = runner.invoke(app, ["canvas", "quizzes", "preview", "20", "--json"])

    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r["id"] for r in rows] == [13, 11]
    assert "differ" in result.stderr
