"""Live tests for quiz authoring against the seeded practice course."""

from __future__ import annotations

__docformat__ = "google"

import pytest
from live_course import CONFIG_PATH, QUIZ_TITLE, SURVEY_TITLE

from cass.actions.quizzes import load_quiz_file, quiz_spec_from_canvas, strip_html
from cass.apis.canvas.client import CanvasClient


@pytest.mark.parametrize(
    ("title", "file"),
    [(QUIZ_TITLE, "live-quiz.toml"), (SURVEY_TITLE, "live-survey.toml")],
)
def test_seeded_quiz_matches_its_file(practice: CanvasClient, title, file):
    expected = load_quiz_file(CONFIG_PATH.parent / "quizzes" / file)
    quiz = practice.resolve_quiz(title)
    questions, _ = practice.list_quiz_questions(quiz.id)
    exported = quiz_spec_from_canvas(quiz, questions, "", practice.time_zone)

    assert exported.quiz_type == expected.quiz_type
    assert exported.due_at == expected.due_at
    assert exported.attempts == expected.attempts
    assert exported.published
    assert [strip_html(q.text) for q in exported.questions] == [
        strip_html(q.text) for q in expected.questions
    ]
    assert [q.type for q in exported.questions] == [q.type for q in expected.questions]
