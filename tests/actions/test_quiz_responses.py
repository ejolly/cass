"""Tests for reshaping quiz reports and adding timing to responses."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

from cass.actions.quiz_responses import (
    RESPONSE_COLUMNS,
    add_timing,
    fetch_quiz_responses,
    parse_student_analysis,
)
from cass.apis.canvas.schema import (
    CanvasQuiz,
    CanvasQuizSubmission,
    CanvasSubmissionResponse,
)

LATEST_REPORT = """\
﻿name,id,sis_id,section,section_id,section_sis_id,submitted,"101: <p>How are you,
really?</p>",0.0,102: Pick one,1.0,n correct,n incorrect,score
Alice Smith,11,A1,Sec A,5,,2026-09-25 23:30:00 UTC,"Fine, thanks",0.0,B,1.0,1,0,1.0
Bob Jones,12,A2,Sec A,5,,2026-09-26 01:00:00 UTC,,0.0,A,0.0,0,1,0.0
"""

ALL_VERSIONS_REPORT = """\
name,id,sis_id,section,section_id,section_sis_id,submitted,attempt,\
101: Q1,1.0,n correct,n incorrect,score
Alice Smith,11,A1,Sec A,5,,2026-09-25 20:00:00 UTC,1,first,0.0,0,1,0.0
Alice Smith,11,A1,Sec A,5,,2026-09-25 23:30:00 UTC,2,second,1.0,1,0,1.0
"""


def _sub(user_id, attempt, **kw):
    return CanvasQuizSubmission(
        id=user_id * 10,
        user_id=user_id,
        attempt=attempt,
        workflow_state=kw.pop("workflow_state", "complete"),
        **kw,
    )


class TestParseStudentAnalysis:
    def test_one_row_per_student_and_question(self):
        responses = parse_student_analysis(LATEST_REPORT)
        assert [(r.student, r.question_id) for r in responses] == [
            ("Alice Smith", 101),
            ("Alice Smith", 102),
            ("Bob Jones", 101),
            ("Bob Jones", 102),
        ]
        first = responses[0]
        assert first.user_id == 11
        assert first.sis_id == "A1"
        assert first.section == "Sec A"
        assert first.position == 1
        assert first.question == "<p>How are you,\nreally?</p>"
        assert first.answer == "Fine, thanks"
        assert first.score == 0.0
        assert responses[1].score == 1.0

    def test_latest_report_has_no_attempt(self):
        assert parse_student_analysis(LATEST_REPORT)[0].attempt is None

    def test_submitted_normalized_to_iso_utc(self):
        assert (
            parse_student_analysis(LATEST_REPORT)[0].submitted_at
            == "2026-09-25T23:30:00Z"
        )

    def test_all_versions_report_keeps_attempts(self):
        responses = parse_student_analysis(ALL_VERSIONS_REPORT)
        assert [(r.attempt, r.answer) for r in responses] == [
            (1, "first"),
            (2, "second"),
        ]

    def test_empty_or_questionless_report(self):
        assert parse_student_analysis("") == []
        assert parse_student_analysis("name,id\nA,1\n") == []

    def test_anonymous_rows_have_no_user_id(self):
        text = "name,id,submitted,101: Q,0.0\n,,,yes,0.0\n"
        (r,) = parse_student_analysis(text)
        assert r.user_id is None
        assert r.answer == "yes"


class TestAddTiming:
    def test_per_student_due_date_and_late(self):
        responses = parse_student_analysis(LATEST_REPORT)
        add_timing(
            responses,
            due_by_user={11: "2026-09-26T00:00:00Z"},
            quiz_submissions=[],
            default_due="2026-09-26T00:30:00Z",
        )
        alice, bob = responses[0], responses[2]
        assert alice.due_at == "2026-09-26T00:00:00Z"
        assert alice.late is False
        # No override for Bob: the quiz due date applies, and he was late.
        assert bob.due_at == "2026-09-26T00:30:00Z"
        assert bob.late is True

    def test_override_without_due_date_beats_quiz_due_date(self):
        responses = parse_student_analysis(LATEST_REPORT)
        add_timing(
            responses,
            due_by_user={11: None},
            quiz_submissions=[],
            default_due="2026-09-01T00:00:00Z",
        )
        assert responses[0].due_at is None
        assert responses[0].late is None

    def test_no_due_date_leaves_late_unknown(self):
        responses = parse_student_analysis(LATEST_REPORT)
        add_timing(responses, due_by_user={}, quiz_submissions=[])
        assert responses[0].due_at is None
        assert responses[0].late is None

    def test_latest_attempt_gets_start_and_auto_submitted(self):
        responses = parse_student_analysis(LATEST_REPORT)
        subs = [
            _sub(
                11,
                2,
                started_at="2026-09-25T23:00:00Z",
                finished_at="2026-09-25T23:30:00Z",
                end_at="2026-09-26T00:00:00Z",
            ),
            # Force-submitted at course end: finished exactly at end_at.
            _sub(
                12,
                1,
                started_at="2026-09-20T10:00:00Z",
                finished_at="2026-12-15T08:00:00Z",
                end_at="2026-12-15T08:00:00Z",
            ),
        ]
        add_timing(responses, due_by_user={}, quiz_submissions=subs)
        alice, bob = responses[0], responses[2]
        assert (alice.attempt, bob.attempt) == (2, 1)
        assert alice.started_at == "2026-09-25T23:00:00Z"
        assert alice.auto_submitted is False
        assert bob.auto_submitted is True

    def test_older_attempts_have_no_quiz_submission_timing(self):
        responses = parse_student_analysis(ALL_VERSIONS_REPORT)
        subs = [_sub(11, 2, started_at="2026-09-25T23:00:00Z")]
        add_timing(responses, due_by_user={}, quiz_submissions=subs)
        first, second = responses
        assert first.started_at is None
        assert first.auto_submitted is None
        assert second.started_at == "2026-09-25T23:00:00Z"
        assert second.auto_submitted is False

    def test_attempt_in_progress_is_not_the_reported_one(self):
        """An open new attempt must not relabel the finished one in the report."""
        responses = parse_student_analysis(LATEST_REPORT)
        subs = [_sub(11, 3, workflow_state="untaken")]
        add_timing(responses, due_by_user={}, quiz_submissions=subs)
        assert responses[0].attempt is None
        assert responses[0].started_at is None


class TestRow:
    def test_row_follows_columns(self):
        (r, *_) = parse_student_analysis(LATEST_REPORT)
        row = r.row()
        assert len(row) == len(RESPONSE_COLUMNS)
        assert row[RESPONSE_COLUMNS.index("late")] == ""
        r.late = True
        assert r.row(("student", "late")) == ["Alice Smith", "true"]


class TestFetchQuizResponses:
    def _client(self):
        client = MagicMock()
        client.download_quiz_report.return_value = LATEST_REPORT
        client.list_quiz_submissions.return_value = []
        client.list_submissions.return_value = [
            CanvasSubmissionResponse(user_id=11, cached_due_date="2026-09-26T02:00:00Z")
        ]
        return client

    def test_graded_quiz_uses_assignment_due_dates(self):
        client = self._client()
        quiz = CanvasQuiz(id=20, title="S", assignment_id=30, due_at=None)
        responses = fetch_quiz_responses(client, quiz, all_attempts=True)
        client.download_quiz_report.assert_called_once_with(20, all_versions=True)
        client.list_submissions.assert_called_once_with(30)
        assert responses[0].due_at == "2026-09-26T02:00:00Z"
        assert responses[0].late is False

    def test_ungraded_survey_uses_quiz_due_date(self):
        client = self._client()
        quiz = CanvasQuiz(id=20, title="S", due_at="2026-09-25T00:00:00Z")
        responses = fetch_quiz_responses(client, quiz)
        client.list_submissions.assert_not_called()
        assert responses[0].due_at == "2026-09-25T00:00:00Z"
        assert responses[0].late is True
