"""Live tests for refusing changes to quizzes students have finished (C2).

The practice course's seeded quiz has a finished attempt by the Test Student
only, which must not block changes. A real course (``$CASS_LIVE_REAL_COURSE``)
checks the refusal against real student attempts, read-only: the refusal comes
before any write, and the CLI runs as a dry run.
"""

from __future__ import annotations

__docformat__ = "google"

import pytest
from live_course import QUIZ_TITLE, get_test_student_id
from typer.testing import CliRunner

from cass.actions.config import get_config
from cass.actions.quizzes import count_finished_attempts
from cass.apis.canvas.client import CanvasClient
from cass.cli import app

runner = CliRunner()


def test_test_student_attempt_does_not_count(practice: CanvasClient):
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    student_id = get_test_student_id(practice)
    finished = [
        s
        for s in practice.list_quiz_submissions(quiz.id)
        if s.user_id == student_id
        and s.workflow_state in ("complete", "pending_review")
    ]
    assert finished, "seed-live should leave a finished Test Student attempt"
    assert count_finished_attempts(practice, quiz.id) == 0


@pytest.mark.usefixtures("practice_cli_client")
def test_delete_dry_run_allowed_with_only_test_student(practice: CanvasClient):
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    result = runner.invoke(
        app, ["canvas", "quizzes", "delete", str(quiz.id), "--yes", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "DELETE" in result.stdout


def test_real_quiz_with_attempts_refuses_delete(
    real_course: CanvasClient, monkeypatch: pytest.MonkeyPatch
):
    quiz = next(
        (
            q
            for q in real_course.list_quizzes()
            if count_finished_attempts(real_course, q.id) > 0
        ),
        None,
    )
    if quiz is None:
        pytest.skip("The real course has no quiz with finished student attempts")
    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            get_config().canvas_base_url,
            course_id=real_course.course_id,
            auth=real_course.auth,
            dry_run=True,
        ),
    )

    result = runner.invoke(
        app, ["canvas", "quizzes", "delete", str(quiz.id), "--yes", "--dry-run"]
    )

    assert result.exit_code == 1, result.output
    assert "Canvas web app" in str(result.exception)
