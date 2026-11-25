"""Tests for reshaping quiz reports and adding timing to responses."""

from __future__ import annotations

__docformat__ = "google"

import csv
from unittest.mock import MagicMock

import httpx
import pytest

from cass.actions.quiz_responses import (
    RESPONSE_COLUMNS,
    add_timing,
    fetch_quiz_report,
    fetch_quiz_responses,
    missing_responders,
    parse_report_rows,
    parse_student_analysis,
)
from cass.apis.canvas.auth import CanvasAuthError
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.schema import (
    CanvasQuiz,
    CanvasQuizSubmission,
    CanvasStudentResponse,
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

    def test_answers_trimmed(self):
        text = (
            "name,id,submitted,101: Q,0.0,102: R,0.0\n"
            'A,1,,"  stood up\n\n ",0.0, ,0.0\n'
        )
        first, second = parse_student_analysis(text)
        assert first.answer == "stood up"
        assert second.answer == ""

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

    def test_open_newer_attempt_reports_the_one_before(self):
        """An open attempt 3 means the report holds finished attempt 2."""
        responses = parse_student_analysis(LATEST_REPORT)
        subs = [
            _sub(11, 3, workflow_state="untaken", started_at="2026-09-27T00:00:00Z")
        ]
        add_timing(responses, due_by_user={}, quiz_submissions=subs)
        assert responses[0].attempt == 2
        # Timing describes only the open attempt, so it stays unknown.
        assert responses[0].started_at is None
        assert responses[0].auto_submitted is None

    def test_open_first_attempt_leaves_attempt_unknown(self):
        responses = parse_student_analysis(LATEST_REPORT)
        subs = [_sub(11, 1, workflow_state="untaken")]
        add_timing(responses, due_by_user={}, quiz_submissions=subs)
        assert responses[0].attempt is None

    def test_times_in_course_time_zone(self):
        responses = parse_student_analysis(LATEST_REPORT)
        subs = [_sub(11, 2, started_at="2026-09-25T23:00:00Z")]
        add_timing(
            responses,
            due_by_user={11: "2026-09-26T00:00:00Z"},
            quiz_submissions=subs,
            tz="America/Los_Angeles",
        )
        alice = responses[0]
        assert alice.submitted_at == "2026-09-25T16:30:00-07:00"
        assert alice.due_at == "2026-09-25T17:00:00-07:00"
        assert alice.started_at == "2026-09-25T16:00:00-07:00"
        assert alice.late is False


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
        client.time_zone = "UTC"
        client.download_quiz_report.return_value = LATEST_REPORT
        client.list_quiz_submissions.return_value = []
        client.list_submissions.return_value = [
            CanvasSubmissionResponse(user_id=11, cached_due_date="2026-09-26T02:00:00Z")
        ]
        return client

    def test_graded_quiz_uses_assignment_due_dates(self):
        client = self._client()
        quiz = CanvasQuiz(id=20, title="S", assignment_id=30, due_at=None)
        responses = fetch_quiz_responses(client, quiz, all_attempts=True).responses
        client.download_quiz_report.assert_called_once_with(20, all_versions=True)
        client.list_submissions.assert_called_once_with(30)
        assert responses[0].due_at == "2026-09-26T02:00:00Z"
        assert responses[0].late is False

    def test_ungraded_survey_uses_quiz_due_date(self):
        client = self._client()
        quiz = CanvasQuiz(id=20, title="S", due_at="2026-09-25T00:00:00Z")
        responses = fetch_quiz_responses(client, quiz).responses
        client.list_submissions.assert_not_called()
        assert responses[0].due_at == "2026-09-25T00:00:00Z"
        assert responses[0].late is True


ANONYMOUS_REPORT = """\
section,section_id,section_sis_id,submitted,101: Q1,0.0,n correct,n incorrect,score
Sec A,5,,2026-09-25 23:30:00 UTC,yes,0.0,0,0,0.0
Sec A,5,,2026-09-26 01:00:00 UTC,no,0.0,0,0,0.0
"""

ANONYMOUS_ALL_VERSIONS_REPORT = """\
section,submitted,attempt,101: Q1,0.0
Sec A,2026-09-25 23:30:00 UTC,1,yes,0.0
Sec A,2026-09-26 01:00:00 UTC,2,no,0.0
"""

# A quiz with no questions still has a row per student.
QUESTIONLESS_REPORT = """\
name,id,sis_id,section,submitted,n correct,n incorrect,score
Alice Smith,11,A1,Sec A,2026-09-25 23:30:00 UTC,0,0,0.0
"""

TEST_STUDENT_ID = 99


class TestMissingResponders:
    """C4: students with a finished attempt but no row in Canvas's report."""

    def test_missing_responder_listed(self):
        responses = parse_student_analysis(LATEST_REPORT)
        subs = [_sub(14, 1), _sub(13, 1, workflow_state="pending_review"), _sub(11, 1)]
        assert missing_responders(responses, subs, {11, 12, 13, 14}) == [13, 14]

    def test_test_student_not_listed(self):
        subs = [_sub(TEST_STUDENT_ID, 2), _sub(98, 1)]
        assert missing_responders([], subs, {11, 12}) == []

    def test_unfinished_attempts_not_listed(self):
        subs = [
            _sub(11, 1, workflow_state="untaken"),
            _sub(12, None, workflow_state="settings_only"),
        ]
        assert missing_responders([], subs, {11, 12}) == []

    def test_student_mid_retake_listed(self):
        subs = [_sub(11, 2, workflow_state="untaken")]
        assert missing_responders([], subs, {11}) == [11]


def _report_client(report, finished, *, roster=(11, 12, 13)):
    """Client whose students in ``finished`` have each finished an attempt."""
    client = MagicMock()
    client.time_zone = "UTC"
    client.download_quiz_report.return_value = report
    client.list_students.return_value = [
        CanvasStudentResponse(id=i, name=f"S{i}") for i in roster
    ]
    client.list_quiz_submissions.return_value = [_sub(i, 1) for i in finished]
    return client


SURVEY = CanvasQuiz(id=20, title="S")


class TestReportWarnings:
    def _warnings(self, *args, all_attempts=False, **kw):
        client = _report_client(*args, **kw)
        return fetch_quiz_report(client, SURVEY, all_attempts=all_attempts).warnings

    def test_complete_report_has_no_warning(self):
        assert self._warnings(LATEST_REPORT, [11, 12, TEST_STUDENT_ID]) == []

    def test_missing_student_named(self):
        (warning,) = self._warnings(LATEST_REPORT, [11, 12, 13])
        assert "1 student(s)" in warning
        assert "user IDs: 13" in warning

    def test_all_attempts_report_compares_students(self):
        (warning,) = self._warnings(ALL_VERSIONS_REPORT, [11, 12], all_attempts=True)
        assert warning.endswith("user IDs: 12.")

    def test_questionless_report_uses_its_rows(self):
        assert self._warnings(QUESTIONLESS_REPORT, [11]) == []

    def test_empty_report_names_everyone(self):
        header = LATEST_REPORT.split("Alice")[0]
        (warning,) = self._warnings(header, [11, 12])
        assert "user IDs: 11, 12." in warning

    def test_row_without_id_may_be_a_missing_student(self):
        report = LATEST_REPORT + ",,,Sec A,5,,,x,0.0,A,0.0,0,0,0.0\n"
        (warning,) = self._warnings(report, [13])
        assert "user IDs: 13." in warning
        assert "1 row(s) have no user ID" in warning

    def test_anonymous_report_says_unchecked(self):
        """All attempts without user IDs: rows can't be counted as students."""
        (warning,) = self._warnings(
            ANONYMOUS_ALL_VERSIONS_REPORT, [11, 12], all_attempts=True
        )
        assert "could not check" in warning
        assert "no user IDs" in warning

    def test_anonymous_report_with_extra_rows_says_unchecked(self):
        """Rows from former students could hide a current student's omission."""
        (warning,) = self._warnings(ANONYMOUS_REPORT, [11])
        assert "could not check" in warning

    def test_anonymous_report_compares_counts(self):
        assert self._warnings(ANONYMOUS_REPORT, [11, 12]) == []
        (warning,) = self._warnings(ANONYMOUS_REPORT, [11, 12, 13])
        assert "at least 1 student(s)" in warning
        assert "13" not in warning

    def test_empty_roster_says_unchecked(self):
        """A concluded course lists no current students to compare."""
        (warning,) = self._warnings(LATEST_REPORT, [], roster=())
        assert "could not check" in warning
        assert "no current students" in warning

    def test_list_read_before_report_is_requested(self):
        """A student who finishes while Canvas builds the report isn't missing."""
        client = _report_client(LATEST_REPORT, [11, 12])

        def download(*args, **kw):
            client.list_quiz_submissions.return_value = [_sub(13, 1)]
            return LATEST_REPORT

        client.download_quiz_report.side_effect = download
        assert fetch_quiz_report(client, SURVEY).warnings == []

    @pytest.mark.parametrize("method", ["list_students", "list_quiz_submissions"])
    @pytest.mark.parametrize(
        "error",
        [
            httpx.ConnectError("secret detail"),
            CanvasAuthError("secret detail"),
            ValueError("secret detail"),
        ],
    )
    def test_failed_check_keeps_report(self, method, error):
        client = _report_client(LATEST_REPORT, [11, 12])
        getattr(client, method).side_effect = error
        report = fetch_quiz_report(client, SURVEY)
        assert report.text == LATEST_REPORT
        (warning,) = report.warnings
        assert "could not check" in warning
        assert "secret detail" not in warning

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            (200, b"{}"),
            (200, b"[]"),
            (200, b'{"message": "secret detail"}'),
            (204, b""),
        ],
    )
    @pytest.mark.parametrize("unread", ["users", "submissions"])
    def test_unread_list_keeps_report(self, monkeypatch, unread, status, body):
        """A body that isn't the list must not pass as a clean check."""
        bodies = {
            "users": b'[{"id": 11, "name": "A"}]',
            "submissions": b'{"quiz_submissions": []}',
        }

        def handler(request: httpx.Request) -> httpx.Response:
            endpoint = request.url.path.rsplit("/", 1)[-1]
            if endpoint == unread:
                return httpx.Response(status, content=body)
            return httpx.Response(200, content=bodies[endpoint])

        monkeypatch.setattr(
            CanvasClient, "download_quiz_report", lambda *_, **__: LATEST_REPORT
        )
        with CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(handler),
        ) as client:
            report = fetch_quiz_report(client, SURVEY)
        assert report.text == LATEST_REPORT
        (warning,) = report.warnings
        assert "could not check" in warning
        assert "secret detail" not in warning

    def test_unparseable_report_is_kept(self):
        text = "name,id,101: Q\nAlice,11,one\rtwo\n"
        report = fetch_quiz_report(_report_client(text, [11]), SURVEY)
        assert report.text == text
        (warning,) = report.warnings
        assert "could not check" in warning
        assert "could not read the report" in warning

    def test_long_answer_is_read(self):
        limit = csv.field_size_limit()
        answer = "x" * (limit + 1)
        text = f"name,id,submitted,101: Q,0.0\nAlice,11,,{answer},0.0\n"
        result = fetch_quiz_responses(_report_client(text, [11]), SURVEY)
        assert result.warnings == []
        assert result.responses[0].answer == answer
        assert csv.field_size_limit() == limit

    def test_field_limit_restored_after_error(self):
        limit = csv.field_size_limit()
        with pytest.raises(csv.Error):
            parse_report_rows("a,b\n" + "x" * (limit + 1) + "\ry\n")
        assert csv.field_size_limit() == limit

    @pytest.mark.parametrize("all_attempts", [False, True])
    def test_failed_submissions_list_keeps_responses(self, all_attempts):
        client = _report_client(LATEST_REPORT, [])
        client.list_quiz_submissions.side_effect = httpx.ConnectError("down")
        result = fetch_quiz_responses(client, SURVEY, all_attempts=all_attempts)
        assert len(result.responses) == 4
        unchecked, blank = result.warnings
        assert "could not check" in unchecked
        assert "started_at and auto_submitted are blank" in blank
        assert ("attempt," in blank) is not all_attempts

    def test_responses_carry_report_warnings(self):
        client = _report_client(LATEST_REPORT, [13])
        (warning,) = fetch_quiz_responses(client, SURVEY).warnings
        assert "user IDs: 13." in warning
