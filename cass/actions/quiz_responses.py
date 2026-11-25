"""Quiz responses — every student's answers to a classic quiz or survey.

Canvas's student analysis report is wide: one ``"<id>: <text>"`` column per
question, each followed by its score column. ``parse_student_analysis``
reshapes it to one ``QuizResponse`` per student x attempt x question, and
``add_timing`` fills in what the report lacks: each student's due date
(after overrides and extensions) and whether Canvas closed the attempt itself.

``fetch_quiz_report`` compares the report with the quiz's finished attempts and
returns a warning for what it leaves out (commitment C4).
"""

from __future__ import annotations

__docformat__ = "google"

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import msgspec

from ..apis.canvas.attempts import (
    FINISHED_ATTEMPT_STATES,
    failed_request_reason,
    has_finished_attempt,
)
from ..apis.canvas.auth import CanvasAuthError

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasQuiz, CanvasQuizSubmission

RESPONSE_COLUMNS = (
    "student",
    "user_id",
    "sis_id",
    "section",
    "attempt",
    "submitted_at",
    "due_at",
    "late",
    "started_at",
    "auto_submitted",
    "question_id",
    "position",
    "question",
    "answer",
    "score",
)

# Reads that may fail without losing the responses. ValueError covers a body
# that isn't JSON.
_READ_ERRORS = (httpx.HTTPError, CanvasAuthError, msgspec.MsgspecError, ValueError)

_QUESTION_RE = re.compile(r"^(\d+): (.*)$", re.DOTALL)


@dataclass
class QuizResponse:
    """One student's answer to one question on one attempt.

    Timing fields are ``None`` when unknown: ``started_at`` and
    ``auto_submitted`` exist only for a student's latest attempt.
    """

    student: str
    user_id: int | None
    sis_id: str
    section: str
    attempt: int | None
    submitted_at: str
    question_id: int
    position: int
    question: str
    answer: str
    score: float | None
    due_at: str | None = None
    late: bool | None = None
    started_at: str | None = None
    auto_submitted: bool | None = None

    def row(self, columns: tuple[str, ...] = RESPONSE_COLUMNS) -> list[str]:
        """Values for *columns* (default ``RESPONSE_COLUMNS``) as CSV strings."""
        return [_cell(getattr(self, name)) for name in columns]


@dataclass
class ReportRow:
    """One row of a student analysis report; ``user_id`` is blank if anonymous."""

    user_id: int | None


@dataclass
class QuizReport:
    """A student analysis report and what cass found missing from it."""

    text: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class QuizResponses:
    """A quiz's responses and what cass found missing from them."""

    responses: list[QuizResponse]
    warnings: list[str] = field(default_factory=list)


@dataclass
class _CurrentAttempts:
    """The course's current students and their latest attempts on a quiz."""

    student_ids: set[int]
    quiz_submissions: list[CanvasQuizSubmission]


def _read_rows(text: str) -> list[list[str]]:
    """Read a report's CSV rows, with fields of any length.

    Raises:
        csv.Error: The report is not valid CSV.
    """
    # Python stops at 131,072 characters, which a long essay answer can pass.
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(max(previous_limit, len(text)))
    try:
        return list(csv.reader(io.StringIO(text.removeprefix("\ufeff"))))
    finally:
        csv.field_size_limit(previous_limit)


def parse_report_rows(text: str) -> tuple[list[ReportRow], bool]:
    """List a student analysis report's rows, whatever questions it has.

    Args:
        text: Report CSV as downloaded from Canvas.

    Returns:
        The rows, and whether the report identifies students. It doesn't when
        it has no user ID column, or has rows and none of them has a user ID.
    """
    rows = _read_rows(text)
    if not rows:
        return [], False
    header = [h.strip().lower() for h in rows[0]]
    column = header.index("id") if "id" in header else None
    found = [
        ReportRow(
            _as_int(row[column].strip())
            if column is not None and column < len(row)
            else None
        )
        for row in rows[1:]
        if any(cell.strip() for cell in row)
    ]
    if column is None:
        return found, False
    return found, not found or any(r.user_id is not None for r in found)


def missing_responders(
    responses: Sequence[QuizResponse | ReportRow],
    quiz_submissions: list[CanvasQuizSubmission],
    student_ids: set[int],
) -> list[int]:
    """List students with a finished attempt and no row in the report.

    Args:
        responses: The report's rows, or the responses parsed from it.
        quiz_submissions: Each current student's latest attempt on the quiz.
        student_ids: The roster. Everyone else, such as the Test Student, is
            ignored.

    Returns:
        Sorted user IDs.
    """
    reported = {r.user_id for r in responses}
    finished = {
        s.user_id
        for s in quiz_submissions
        if s.user_id is not None and has_finished_attempt(s)
    }
    return sorted((finished & student_ids) - reported)


def parse_student_analysis(text: str) -> list[QuizResponse]:
    """Reshape a student analysis report CSV to one row per answer.

    The latest-only report has no ``attempt`` column; its responses get
    ``attempt=None`` until ``add_timing`` fills it in. Submission times are
    normalized to ISO 8601 UTC (``...Z``).

    Args:
        text: Report CSV as downloaded from Canvas.

    Returns:
        Responses in report order, questions in report column order.
    """
    rows = _read_rows(text)
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    questions = [
        (i, m.group(1), m.group(2))
        for i, h in enumerate(header)
        if (m := _QUESTION_RE.match(h))
    ]
    if not questions:
        return []
    question_cols = {i for i, _, _ in questions}
    meta = {h.strip().lower(): i for i, h in enumerate(header[: questions[0][0]])}

    def meta_value(row: list[str], name: str) -> str:
        i = meta.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    responses: list[QuizResponse] = []
    for row in body:
        if not any(cell.strip() for cell in row):
            continue
        student = meta_value(row, "name")
        user_id = _as_int(meta_value(row, "id"))
        sis_id = meta_value(row, "sis_id")
        section = meta_value(row, "section")
        attempt = _as_int(meta_value(row, "attempt"))
        submitted_at = _iso_utc(meta_value(row, "submitted")) or ""
        for position, (col, question_id, question) in enumerate(questions, 1):
            answer = row[col].strip() if col < len(row) else ""
            score_col = col + 1
            score = (
                _as_float(row[score_col])
                if score_col < len(row) and score_col not in question_cols
                else None
            )
            responses.append(
                QuizResponse(
                    student=student,
                    user_id=user_id,
                    sis_id=sis_id,
                    section=section,
                    attempt=attempt,
                    submitted_at=submitted_at,
                    question_id=int(question_id),
                    position=position,
                    question=question.strip(),
                    answer=answer,
                    score=score,
                )
            )
    return responses


def add_timing(
    responses: list[QuizResponse],
    *,
    due_by_user: dict[int, str | None],
    quiz_submissions: list[CanvasQuizSubmission],
    default_due: str | None = None,
    tz: str = "UTC",
) -> list[QuizResponse]:
    """Fill due dates, lateness, and auto-submission flags in place.

    - ``due_at``: the student's own due date (``cached_due_date``, which
      respects overrides and extensions, and may be ``None``), else
      ``default_due`` for students missing from *due_by_user*.
    - ``late``: ``submitted_at > due_at`` when both are known.
    - ``attempt``: for latest-only reports, the student's latest finished
      attempt. When the student has opened a newer attempt and not submitted
      it, the report holds the one before it.
    - ``started_at`` / ``auto_submitted``: from the student's latest quiz
      submission, on that attempt only, so they stay empty while a newer
      attempt is open. ``auto_submitted`` means Canvas closed the attempt
      (``finished_at >= end_at``): a time limit ran out, or an attempt left
      open was force-submitted when the course concluded.
    - ``submitted_at``, ``due_at`` and ``started_at`` are rewritten as ISO 8601
      with *tz*'s offset (``Z`` for UTC).

    Returns:
        The same list, for chaining.
    """
    latest = {s.user_id: s for s in quiz_submissions}
    for r in responses:
        sub = latest.get(r.user_id) if r.user_id is not None else None
        if r.attempt is None and sub:
            if sub.workflow_state in FINISHED_ATTEMPT_STATES:
                r.attempt = sub.attempt
            elif sub.attempt and sub.attempt > 1:
                r.attempt = sub.attempt - 1
        due = due_by_user.get(r.user_id, default_due) if r.user_id else default_due
        submitted, due_at = _parse(r.submitted_at), _parse(due)
        r.late = submitted > due_at if submitted and due_at else None
        r.submitted_at = _iso_in(r.submitted_at, tz) or ""
        r.due_at = _iso_in(due, tz)
        if sub and r.attempt is not None and sub.attempt == r.attempt:
            r.started_at = _iso_in(sub.started_at, tz)
            finished, end = _parse(sub.finished_at), _parse(sub.end_at)
            r.auto_submitted = finished >= end if finished and end else False
    return responses


def fetch_quiz_report(
    client: CanvasClient, quiz: CanvasQuiz, *, all_attempts: bool = False
) -> QuizReport:
    """Download a student analysis report and check it for missing students.

    Attempts are read before the report is requested, so a student who finishes
    while Canvas builds it is not called missing. The check covers current
    students only, and a failed check never loses the report.

    Args:
        client: Canvas client for the quiz's course.
        quiz: Classic quiz or survey.
        all_attempts: Report every attempt, not only each student's latest.
    """
    attempts = _read_current_attempts(client, quiz.id)
    text = client.download_quiz_report(quiz.id, all_versions=all_attempts)
    if isinstance(attempts, str):
        warning = _unchecked(attempts)
    else:
        warning = _omission_warning(text, attempts, all_attempts=all_attempts)
    return QuizReport(text, [warning] if warning else [])


def fetch_quiz_responses(
    client: CanvasClient, quiz: CanvasQuiz, *, all_attempts: bool = False
) -> QuizResponses:
    """Download, reshape, time-stamp, and check every student's answers to a quiz.

    Times are written in the course time zone.

    Args:
        client: Canvas client for the quiz's course.
        quiz: Classic quiz or survey.
        all_attempts: Include every attempt, not only each student's latest.
    """
    report = fetch_quiz_report(client, quiz, all_attempts=all_attempts)
    warnings = list(report.warnings)
    due_by_user: dict[int, str | None] = {}
    if quiz.assignment_id:
        due_by_user = {
            s.user_id: s.cached_due_date
            for s in client.list_submissions(quiz.assignment_id)
        }
    # Read again after the report: an older list could number its attempts wrong.
    quiz_submissions: list[CanvasQuizSubmission] = []
    try:
        quiz_submissions = client.list_quiz_submissions(quiz.id)
    except _READ_ERRORS as exc:
        blank = "started_at and auto_submitted"
        if not all_attempts:
            blank = f"attempt, {blank}"
        warnings.append(
            f"cass could not read attempt times ({_reason(exc)}), so {blank} are blank."
        )
    responses = add_timing(
        parse_student_analysis(report.text),
        due_by_user=due_by_user,
        quiz_submissions=quiz_submissions,
        default_due=quiz.due_at,
        tz=client.time_zone,
    )
    return QuizResponses(responses, warnings)


def _read_current_attempts(
    client: CanvasClient, quiz_id: int
) -> _CurrentAttempts | str:
    """Read the roster and attempts, or say why they can't be compared."""
    try:
        student_ids = {s.id for s in client.list_students()}
        quiz_submissions = client.list_quiz_submissions(quiz_id)
    except _READ_ERRORS as exc:
        return _reason(exc)
    if not student_ids:
        return "Canvas lists no current students"
    return _CurrentAttempts(student_ids, quiz_submissions)


def _omission_warning(
    text: str, attempts: _CurrentAttempts, *, all_attempts: bool
) -> str | None:
    """Say which students the report leaves out, or that it can't be checked."""
    try:
        rows, identified = parse_report_rows(text)
    except csv.Error:
        return _unchecked("cass could not read the report")
    if identified:
        missing = missing_responders(
            rows, attempts.quiz_submissions, attempts.student_ids
        )
        if not missing:
            return None
        ids = ", ".join(str(user_id) for user_id in missing)
        warning = (
            f"{len(missing)} student(s) with a finished attempt are not in "
            f"Canvas's report, so their responses are missing; user IDs: {ids}."
        )
        unidentified = sum(1 for row in rows if row.user_id is None)
        if unidentified:
            warning += f" {unidentified} row(s) have no user ID and may belong to them."
        return warning

    if all_attempts and rows:
        return _unchecked(
            "the report has no user IDs, so one student's attempts can't be "
            "told from another's"
        )
    # One row per respondent, so counts can be compared.
    finished = len(
        missing_responders([], attempts.quiz_submissions, attempts.student_ids)
    )
    if len(rows) < finished:
        return (
            f"at least {finished - len(rows)} student(s) with a finished attempt "
            "are not in Canvas's report, so their responses are missing. The "
            "report has no user IDs, so cass can't tell which."
        )
    if len(rows) > finished:
        return _unchecked(
            "the report has no user IDs and more rows than current students "
            "with a finished attempt"
        )
    return None


def _unchecked(reason: str) -> str:
    return (
        "cass could not check whether any student's responses are missing "
        f"from Canvas's report ({reason})."
    )


def _reason(exc: Exception) -> str:
    """Say why a read failed, without Canvas's response text."""
    if isinstance(exc, httpx.HTTPError):
        return failed_request_reason(exc)
    if isinstance(exc, CanvasAuthError):
        return "Canvas refused access"
    return "Canvas returned an unreadable list"


def _parse(value: str | None) -> datetime | None:
    """Parse Canvas timestamps: ISO 8601 or the report's ``... UTC`` form."""
    if not value:
        return None
    text = value.strip()
    if text.endswith(" UTC"):
        text = text.removesuffix(" UTC") + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_utc(value: str | None) -> str | None:
    """Normalize a timestamp to ``YYYY-MM-DDTHH:MM:SSZ``; keep unparseable text."""
    return _iso_in(value, "UTC")


def _iso_in(value: str | None, tz: str) -> str | None:
    """Render a timestamp as ISO 8601 in *tz* (``Z`` for UTC); keep unparseable text."""
    parsed = _parse(value)
    if parsed is None:
        return value or None
    if tz == "UTC":
        return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return parsed.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
