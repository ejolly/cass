"""Live test: edit a quiz's questions and groups round trip (practice course only)."""

from __future__ import annotations

__docformat__ = "google"

import dataclasses
import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cass.actions.config import get_config
from cass.actions.quizzes import (
    AnswerSpec,
    GroupSpec,
    QuestionSpec,
    QuizSpec,
    dump_quiz_file,
    load_quiz_file,
)
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()


def _question_rows(quiz_id: int) -> list[dict]:
    result = runner.invoke(
        app, ["canvas", "quizzes", "questions", str(quiz_id), "--json"]
    )
    assert result.exit_code == 0, result.output
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _export(quiz_id: int, path: Path) -> QuizSpec:
    result = runner.invoke(
        app, ["canvas", "quizzes", "export", str(quiz_id), "-o", str(path)]
    )
    assert result.exit_code == 0, result.output
    return load_quiz_file(path)


def _apply(quiz_id: int, path: Path, *flags: str) -> None:
    result = runner.invoke(
        app,
        [
            "canvas",
            "quizzes",
            "update",
            str(quiz_id),
            "--from",
            str(path),
            "--questions",
            "--apply",
            *flags,
        ],
    )
    assert result.exit_code == 0, result.output


def test_question_editing_round_trip(
    practice: CanvasClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Credentials sit in the repository root, so build the CLI's client from
    # the practice fixture's auth (as test_live_dry_run.py does).
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

    # A practice quiz (not a survey) so the choice question keeps its correct answer.
    title = f"cass-live: question editing {int(time.time())}"
    choice_answers = [
        AnswerSpec("<b>Bold</b> choice"),
        AnswerSpec("Plain choice", correct=True),
        AnswerSpec("Third choice"),
    ]
    initial = QuizSpec(
        title=title,
        quiz_type="practice_quiz",
        questions=[
            QuestionSpec(text="<p>First?</p>", name="A"),
            QuestionSpec(text="<p>Second?</p>", name="B"),
            QuestionSpec(text="<p>Third?</p>", name="C"),
            QuestionSpec(
                text="<p>Pick one</p>",
                type="multiple_choice_question",
                name="D",
                answers=choice_answers,
            ),
        ],
    )
    initial_path = tmp_path / "initial.toml"
    dump_quiz_file(initial, initial_path)
    created = runner.invoke(
        app, ["canvas", "quizzes", "create", "--from", str(initial_path)]
    )
    assert created.exit_code == 0, created.output
    quiz_id = practice.resolve_quiz(title).id

    try:
        # Answer ids before any edit, by answer text
        start_rows = {r["question_name"]: r for r in _question_rows(quiz_id)}
        answer_ids = {a["text"]: a["id"] for a in start_rows["D"]["answers"]}

        # Edit 1: reorder, rename, add a question, and group two of them.
        exported = _export(quiz_id, tmp_path / "exported.toml")
        by_name = {q.name: q for q in exported.questions}
        edit1 = dataclasses.replace(
            exported,
            groups=[GroupSpec("Pair", 1)],
            questions=[
                by_name["C"],
                dataclasses.replace(by_name["A"], name="First", group="Pair"),
                QuestionSpec(text="<p>Added</p>", name="Added", group="Pair"),
                by_name["B"],
                by_name["D"],
            ],
        )
        edit1_path = tmp_path / "edit1.toml"
        dump_quiz_file(edit1, edit1_path)
        _apply(quiz_id, edit1_path)

        rows = _question_rows(quiz_id)
        assert [r["question_name"] for r in rows] == ["C", "First", "Added", "B", "D"]
        by_row = {r["question_name"]: r for r in rows}
        pair_group = by_row["First"]["quiz_group_id"]
        assert pair_group is not None
        assert by_row["Added"]["quiz_group_id"] == pair_group
        assert all(by_row[n]["quiz_group_id"] is None for n in ("C", "B", "D"))
        count = practice.get_quiz(quiz_id).question_count
        # C, B, D plus one pick from the group. A stale count here is a Canvas
        # lag (the spec's open risk): report it rather than toggling publish.
        assert count == 4, f"question_count is {count}, expected 4 (stale count?)"

        # Edit 2: ungroup First, drop Added with --prune, reword D's third
        # answer. Canvas deletes a group's questions with the group, so the quiz
        # reorder must take First out of Pair before Pair is deleted.
        exported = _export(quiz_id, tmp_path / "exported2.toml")
        by_name = {q.name: q for q in exported.questions}
        reworded = [*by_name["D"].answers[:2], AnswerSpec("Third, reworded")]
        edit2 = dataclasses.replace(
            exported,
            groups=[],
            questions=[
                by_name["C"],
                dataclasses.replace(by_name["First"], group=""),
                by_name["B"],
                dataclasses.replace(by_name["D"], answers=reworded),
            ],
        )
        edit2_path = tmp_path / "edit2.toml"
        dump_quiz_file(edit2, edit2_path)
        _apply(quiz_id, edit2_path, "--prune")

        rows = _question_rows(quiz_id)
        assert [r["question_name"] for r in rows] == ["C", "First", "B", "D"]
        assert all(r["quiz_group_id"] is None for r in rows)
        # Updates resend the whole question: earlier edits survive, and answers
        # whose text is unchanged keep their ids.
        d_row = rows[3]
        assert d_row["question_text"] == "<p>Pick one</p>"
        assert [a["text"] for a in d_row["answers"]][2] == "Third, reworded"
        for answer in d_row["answers"][:2]:
            assert answer["id"] == answer_ids[answer["text"]], d_row["answers"]
        count = practice.get_quiz(quiz_id).question_count
        assert count == 4, f"question_count is {count}, expected 4 (stale count?)"

        # Preview twice: the second run starts or reuses a preview without error.
        for run in (1, 2):
            preview = runner.invoke(
                app, ["canvas", "quizzes", "preview", str(quiz_id), "--json"]
            )
            assert preview.exit_code == 0, f"preview run {run}: {preview.output}"
            assert "differ" in preview.stderr
            if run == 1:
                # Canvas shows students "Question N" instead of names; compare ids
                shown = {
                    json.loads(line)["id"]
                    for line in preview.stdout.splitlines()
                    if line.strip()
                }
                assert shown == {r["id"] for r in rows}

        # Dry run of the same file: Canvas stores questions as cass sends them,
        # so everything is "keep" (answers included) and nothing would be written.
        dry = runner.invoke(
            app,
            [
                "canvas",
                "quizzes",
                "update",
                str(quiz_id),
                "--from",
                str(edit2_path),
                "--questions",
            ],
        )
        assert dry.exit_code == 0, dry.output
        plan_lines = dry.stdout.splitlines()
        marker = next(i for i, ln in enumerate(plan_lines) if ln.startswith("Dry run:"))
        assert marker == 4
        assert all(ln.startswith("keep") for ln in plan_lines[:marker]), dry.stdout
        assert "no Canvas writes needed" in dry.stdout
    finally:
        practice.delete_quiz(quiz_id)

    with pytest.raises(RuntimeError):
        practice.resolve_quiz(title)
