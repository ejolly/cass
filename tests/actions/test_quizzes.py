"""Tests for quiz spec types, quiz files, and settings diffs."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any
from unittest.mock import MagicMock

import pytest

from cass.actions.quizzes import (
    AnswerSpec,
    QuestionSpec,
    QuizSpec,
    dump_quiz_file,
    load_quiz_file,
    quiz_form_fields,
    quiz_settings_diff,
    quiz_spec_from_canvas,
    strip_html,
    sync_quizzes,
)
from cass.apis.canvas.schema import CanvasQuiz, CanvasQuizAnswer, CanvasQuizQuestion

LA = "America/Los_Angeles"

SURVEY_TOML = """\
title = "09-25 Participation Survey"
type = "graded_survey"
group = "Attendance & Participation"
points = 2
unlock_at = "2026-09-25 14:15"
due_at = "2026-09-25 17:00"
attempts = 1
hide_results = "always"

[[questions]]
type = "essay"
text = "<p>What are you most hoping to get out of this course?</p>"

[[questions]]
type = "multiple_choice"
text = "<p>Which gamble?</p>"
points = 1
answers = [{ text = "A", correct = true }, { text = "B" }]
"""


def _write(tmp_path, text, name="quiz.toml"):
    path = tmp_path / name
    path.write_text(text)
    return path


class TestLoadQuizFile:
    def test_loads_settings_and_questions(self, tmp_path):
        spec = load_quiz_file(_write(tmp_path, SURVEY_TOML))
        assert spec.title == "09-25 Participation Survey"
        assert spec.quiz_type == "graded_survey"
        assert spec.points == 2
        assert spec.hide_results == "always"
        assert spec.scoring_policy == "keep_highest"
        assert spec.lock_at == ""
        assert [q.type for q in spec.questions] == [
            "essay_question",
            "multiple_choice_question",
        ]
        assert spec.questions[0].points is None
        assert spec.questions[1].answers == [
            AnswerSpec("A", True),
            AnswerSpec("B", False),
        ]

    def test_unknown_question_type_passes_through(self, tmp_path):
        toml = (
            'title = "Q"\ntype = "assignment"\n'
            '[[questions]]\ntype = "calculated_question"\ntext = "x"\n'
        )
        spec = load_quiz_file(_write(tmp_path, toml))
        assert spec.questions[0].type == "calculated_question"

    @pytest.mark.parametrize(
        "toml, message",
        [
            ('type = "survey"\n', "missing required key 'title'"),
            ('title = "Q"\n', "missing required key 'type'"),
            (
                'title = "Q"\ntype = "assignment"\nattemps = 2\n',
                "unknown key 'attemps' (did you mean 'attempts'?)",
            ),
            (
                'title = "Q"\ntype = "assignment"\nhide_results = "never"\n',
                "hide_results",
            ),
            (
                'title = "Q"\ntype = "assignment"\nscoring_policy = "avg"\n',
                "scoring_policy",
            ),
            ('title = "Q"\ntype = "assignment"\npoints = 2\n', "points"),
            ('title = "Q"\ntype = "quizz"\n', "type"),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntype = "multiple_choice"\ntext = "x"\n',
                "answers",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntype = "multiple_choice"\ntext = "x"\n'
                'answers = [{ text = "A", correct = true }, '
                '{ text = "B", correct = true }]\n',
                "one correct answer",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntext = "x"\nponts = 1\n',
                "unknown key 'ponts'",
            ),
        ],
        ids=[
            "no-title",
            "no-type",
            "typo",
            "hide",
            "scoring",
            "points",
            "quiz-type",
            "no-answers",
            "two-correct",
            "q-typo",
        ],
    )
    def test_validation(self, tmp_path, toml, message):
        path = _write(tmp_path, toml)
        with pytest.raises(SystemExit) as exc:
            load_quiz_file(path)
        assert str(path) in str(exc.value)
        assert message in str(exc.value)


class TestDumpQuizFile:
    def test_round_trip(self, tmp_path):
        spec = load_quiz_file(_write(tmp_path, SURVEY_TOML))
        text = dump_quiz_file(spec, None)
        again = load_quiz_file(_write(tmp_path, text, "again.toml"))
        assert again == spec

    def test_multiline_text_round_trips(self, tmp_path):
        spec = QuizSpec(
            title="Q",
            quiz_type="survey",
            questions=[QuestionSpec(text='<p>line one</p>\n<p>"quoted"</p>')],
        )
        text = dump_quiz_file(spec, None)
        assert load_quiz_file(_write(tmp_path, text)) == spec

    def test_writes_file(self, tmp_path):
        spec = QuizSpec(title="Q", quiz_type="survey")
        out = tmp_path / "out.toml"
        dump_quiz_file(spec, out)
        assert 'title = "Q"' in out.read_text()


class TestQuizSpecFromCanvas:
    def test_maps_fields_and_course_times(self):
        quiz = CanvasQuiz(
            id=1,
            title="S",
            quiz_type="graded_survey",
            points_possible=2.0,
            allowed_attempts=1,
            hide_results="always",
            unlock_at="2026-09-25T21:15:00Z",
            due_at="2026-09-26T00:00:00Z",
            assignment_group_id=9,
            published=True,
        )
        questions = [
            CanvasQuizQuestion(
                id=5,
                question_name="Question 1",
                question_type="essay_question",
                question_text="<p>Hi</p>",
                position=1,
            ),
            CanvasQuizQuestion(
                id=6,
                question_name="Pick",
                question_type="multiple_choice_question",
                question_text="<p>?</p>",
                points_possible=1.0,
                position=2,
                answers=[
                    CanvasQuizAnswer(id=1, text="A", weight=100),
                    CanvasQuizAnswer(id=2, text="B", weight=0),
                ],
            ),
        ]
        spec = quiz_spec_from_canvas(quiz, questions, "Participation", LA)
        assert spec.group == "Participation"
        assert spec.points == 2.0
        assert spec.unlock_at == "2026-09-25 14:15"
        assert spec.due_at == "2026-09-25 17:00"
        assert spec.lock_at == ""
        assert spec.published is True
        assert spec.questions[0].name == ""  # default name is dropped
        assert spec.questions[1].name == "Pick"
        assert spec.questions[1].answers[0].correct is True

    def test_points_only_for_graded_survey(self):
        quiz = CanvasQuiz(id=1, title="Q", quiz_type="assignment", points_possible=3.0)
        assert quiz_spec_from_canvas(quiz, [], "", LA).points is None


def _live(**overrides: Any) -> CanvasQuiz:
    base: dict[str, Any] = {
        "id": 1,
        "title": "S",
        "quiz_type": "graded_survey",
        "points_possible": 2.0,
        "allowed_attempts": 1,
        "hide_results": "always",
        "unlock_at": "2026-09-25T21:15:00Z",
        "due_at": "2026-09-26T00:00:00Z",
        "lock_at": None,
        "time_limit": None,
        "scoring_policy": "keep_highest",
        "published": False,
        "assignment_group_id": 9,
    }
    base.update(overrides)
    return CanvasQuiz(**base)


def _spec(**overrides: Any) -> QuizSpec:
    base: dict[str, Any] = {
        "title": "S",
        "quiz_type": "graded_survey",
        "points": 2,
        "attempts": 1,
        "hide_results": "always",
        "unlock_at": "2026-09-25 14:15",
        "due_at": "2026-09-25 17:00",
    }
    base.update(overrides)
    return QuizSpec(**base)


class TestQuizSettingsDiff:
    def test_equal_is_empty(self):
        assert quiz_settings_diff(_spec(), _live(), LA, group_id=9) == {}

    def test_offset_only_difference_is_not_a_change(self):
        spec = _spec(due_at="2026-09-25T17:00:00-07:00")
        assert quiz_settings_diff(spec, _live(), LA) == {}

    def test_each_field_type(self):
        spec = _spec(
            due_at="2026-09-25 18:00",
            attempts=2,
            hide_results="",
            published=True,
            description="<p>x</p>",
            time_limit=5,
        )
        diff = quiz_settings_diff(spec, _live(), LA, group_id=10)
        assert diff == {
            "description": "<p>x</p>",
            "due_at": "2026-09-25T18:00:00-07:00",
            "allowed_attempts": 2,
            "time_limit": 5,
            "hide_results": "",
            "published": True,
            "assignment_group_id": 10,
        }

    def test_form_fields_and_diff_share_names(self):
        fields = quiz_form_fields(_spec(), LA, assignment_group_id=9)
        assert fields["due_at"] == "2026-09-25T17:00:00-07:00"
        assert fields["points_possible"] == 2
        assert fields["time_limit"] == ""
        assert set(quiz_settings_diff(_spec(title="T"), _live(), LA)) == {"title"}


class TestSyncQuizzes:
    def test_create_update_skip(self):
        live = CanvasQuiz(
            id=1, title="Existing", quiz_type="survey", allowed_attempts=1
        )
        client = MagicMock()
        client.list_quizzes.return_value = [live]
        specs = [
            QuizSpec(title="New", quiz_type="survey", group="Participation"),
            QuizSpec(title="Existing", quiz_type="survey", attempts=2),
            QuizSpec(title="Existing", quiz_type="survey"),
        ]
        rows = sync_quizzes(client, specs, {"participation": 9}, LA, apply=True)
        assert [r[0] for r in rows] == ["create", "update", "skip"]
        assert "allowed_attempts: 2" in rows[1][2]
        client.create_quiz.assert_called_once_with(specs[0], assignment_group_id=9)
        client.update_quiz.assert_called_once_with(1, {"allowed_attempts": 2})

    def test_dry_run_calls_nothing(self):
        client = MagicMock()
        client.list_quizzes.return_value = []
        sync_quizzes(
            client, [QuizSpec(title="New", quiz_type="survey")], {}, LA, apply=False
        )
        client.create_quiz.assert_not_called()


def test_strip_html():
    assert strip_html("<p>What &amp; why?</p>\n<ul><li>a</li></ul>") == "What & why? a"
    assert strip_html("<p>What are you <b>hoping</b>?</p>") == "What are you hoping?"
