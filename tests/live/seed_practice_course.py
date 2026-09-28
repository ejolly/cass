"""Seed the Canvas practice course with the quizzes live tests read.

Creates the quizzes declared in ``tests/live/cass.toml`` if they are missing,
then submits them as the course's Test Student until each has the attempts
listed in ``ATTEMPTS``. Safe to rerun: existing quizzes and attempts are kept.

Run with ``uv run poe seed-live``.
"""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

from live_course import QUIZ_TITLE, SURVEY_TITLE, get_test_student_id, practice_client

from cass.actions.config import get_config
from cass.actions.quizzes import load_quiz_file, sync_quizzes
from cass.apis.canvas.client import CanvasClient

# Answers per attempt, by question position. Multiple-choice answers are
# given by their text; the rest are sent as typed.
ATTEMPTS: dict[str, list[list[str]]] = {
    QUIZ_TITLE: [
        ["Wrong", "<p>First try, with a comma.</p><p>Second line.</p>", "halo"],
        ["Right", '<p>Second try, "quoted".</p>', "confirmation bias"],
    ],
    SURVEY_TITLE: [
        ["<p>How people read each other.</p>", "Somewhat"],
    ],
}


def submit_attempt(
    client: CanvasClient, quiz_id: int, student_id: int, answers: list[str]
) -> None:
    """Take one attempt at a quiz as the Test Student and turn it in."""
    as_student = {"as_user_id": student_id}
    course = f"/courses/{client.course_id}"
    started = client.request(
        "POST", f"{course}/quizzes/{quiz_id}/submissions", params=as_student
    ).json()["quiz_submissions"][0]
    token = {
        "attempt": started["attempt"],
        "validation_token": started["validation_token"],
    }

    questions, _ = client.list_quiz_questions(quiz_id)
    quiz_questions: list[dict[str, Any]] = []
    for question, answer in zip(questions, answers, strict=True):
        if question.question_type == "multiple_choice_question":
            choice = next(a.id for a in question.answers if a.text == answer)
            quiz_questions.append({"id": question.id, "answer": choice})
        else:
            quiz_questions.append({"id": question.id, "answer": answer})
    client.request(
        "POST",
        f"/quiz_submissions/{started['id']}/questions",
        params=as_student,
        json={**token, "quiz_questions": quiz_questions},
    )
    client.request(
        "POST",
        f"{course}/quizzes/{quiz_id}/submissions/{started['id']}/complete",
        params=as_student,
        json=token,
    )


def completed_attempts(client: CanvasClient, quiz_id: int, student_id: int) -> int:
    """Number of attempts the Test Student has turned in.

    Canvas lists the Test Student's attempts; an attempt still in progress is
    ``untaken``, and a turned-in one is ``complete`` or ``pending_review``.
    """
    data = client.request(
        "GET",
        f"/courses/{client.course_id}/quizzes/{quiz_id}/submissions",
        params={"as_user_id": student_id},
    ).json()
    return sum(1 for s in data["quiz_submissions"] if s["workflow_state"] != "untaken")


def main() -> None:
    with practice_client() as client:
        cfg = get_config()
        specs = [load_quiz_file(ref.file) for ref in cfg.canvas_quizzes]
        for action, _, name in sync_quizzes(
            client, specs, {}, client.time_zone, apply=True
        ):
            print(f"{action}: {name}")

        student_id = get_test_student_id(client)
        quizzes = {q.title: q for q in client.list_quizzes()}
        for title, attempts in ATTEMPTS.items():
            quiz_id = quizzes[title].id
            done = completed_attempts(client, quiz_id, student_id)
            for answers in attempts[done:]:
                submit_attempt(client, quiz_id, student_id, answers)
            print(f"{title}: {len(attempts)} attempts ({done} already submitted)")


if __name__ == "__main__":
    main()
