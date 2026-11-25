"""Live tests for downloading quiz responses.

Canvas leaves the Test Student out of quiz reports, so the practice course
checks the report download and the attempt listing, and a real course
(``$CASS_LIVE_REAL_COURSE``) checks the reshaped responses.
"""

from __future__ import annotations

__docformat__ = "google"

import csv
import io

import pytest
from live_course import QUIZ_TITLE, get_test_student_id

from cass.actions.quiz_responses import (
    fetch_quiz_report,
    fetch_quiz_responses,
    missing_responders,
    parse_student_analysis,
)
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


def test_test_student_is_not_a_missing_responder(practice: CanvasClient):
    """The Test Student's finished attempt is in the list but not the report."""
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    student_ids = {s.id for s in practice.list_students()}
    subs = practice.list_quiz_submissions(quiz.id)
    report = fetch_quiz_report(practice, quiz)
    responses = parse_student_analysis(report.text)

    test_student = get_test_student_id(practice)
    assert test_student in {s.user_id for s in subs}
    assert test_student not in {r.user_id for r in responses}
    assert test_student not in missing_responders(responses, subs, student_ids)
    assert not any(str(test_student) in warning for warning in report.warnings)


def test_real_responses_are_complete(real_course: CanvasClient):
    quizzes = [q for q in real_course.list_quizzes() if q.question_count]
    quiz = next(q for q in quizzes if real_course.list_quiz_submissions(q.id))
    responses = fetch_quiz_responses(real_course, quiz).responses

    students = {r.user_id for r in responses}
    questions = {r.question_id for r in responses}
    assert responses
    assert len(responses) == len(students) * len(questions)
    assert all(r.submitted_at for r in responses)
    assert all(r.late is not None for r in responses if r.due_at)


def _count_missing_on_one_quiz(client: CanvasClient) -> tuple[bool, str] | None:
    """Whether ``missing_responders`` returned a list, and a line of counts."""
    student_ids = {s.id for s in client.list_students()}
    for quiz in client.list_quizzes():
        subs = client.list_quiz_submissions(quiz.id)
        finished = len(missing_responders([], subs, student_ids))
        if not quiz.question_count or not finished:
            continue
        responses = parse_student_analysis(client.download_quiz_report(quiz.id))
        reported = len({r.user_id for r in responses})
        missing = missing_responders(responses, subs, student_ids)
        counts = f"finished {finished}, in report {reported}, missing {len(missing)}"
        return isinstance(missing, list), counts
    return None


def test_real_missing_responders_is_a_list(real_course: CanvasClient):
    """Prints counts only: no IDs, names or Canvas error text, even on failure."""
    failure = ""
    result = None
    try:
        result = _count_missing_on_one_quiz(real_course)
    except Exception as exc:
        failure = type(exc).__name__
    if failure:
        pytest.fail(f"Real course read failed: {failure}", pytrace=False)
    if result is None:
        pytest.skip("The real course has no quiz with finished student attempts")
    is_list, counts = result
    print(counts)
    assert is_list
