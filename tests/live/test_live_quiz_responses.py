"""Live tests for downloading quiz responses.

Canvas leaves the Test Student out of quiz reports, so the practice course
checks the report download and the attempt listing, and a real course
(``$CASS_LIVE_REAL_COURSE``) checks the reshaped responses.
"""

from __future__ import annotations

__docformat__ = "google"

import csv
import io

from live_course import QUIZ_TITLE, get_test_student_id

from cass.actions.quiz_responses import fetch_quiz_responses
from cass.apis.canvas.client import CanvasClient


def test_report_downloads_with_question_headers(practice: CanvasClient):
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    questions, _ = practice.list_quiz_questions(quiz.id)
    text = practice.download_quiz_report(quiz.id, all_versions=True)
    header = next(csv.reader(io.StringIO(text)))
    assert [h.split(":")[0] for h in header if h.split(":")[0].isdigit()] == [
        str(q.id) for q in questions
    ]


def test_quiz_submissions_list_latest_attempt(practice: CanvasClient):
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    student_id = get_test_student_id(practice)
    subs = practice.list_quiz_submissions(quiz.id)
    mine = [s for s in subs if s.user_id == student_id]
    assert len(mine) == 1
    assert mine[0].attempt == 2
    assert mine[0].workflow_state == "pending_review"  # essay awaits grading
    assert mine[0].started_at
    assert mine[0].finished_at


def test_real_responses_are_complete(real_course: CanvasClient):
    quizzes = [q for q in real_course.list_quizzes() if q.question_count]
    quiz = next(q for q in quizzes if real_course.list_quiz_submissions(q.id))
    responses = fetch_quiz_responses(real_course, quiz)

    students = {r.user_id for r in responses}
    questions = {r.question_id for r in responses}
    assert responses
    assert len(responses) == len(students) * len(questions)
    assert all(r.submitted_at for r in responses)
    assert all(r.late is not None for r in responses if r.due_at)
