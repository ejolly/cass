"""Quiz responses — every student's answers to a classic quiz or survey.

Canvas's student analysis report is wide: one ``"<id>: <text>"`` column per
question, each followed by its score column. ``parse_student_analysis``
reshapes it to one ``QuizResponse`` per student x attempt x question, and
``add_timing`` fills in what the report lacks: each student's due date
(after overrides and extensions) and whether Canvas closed the attempt itself.
"""

from __future__ import annotations

__docformat__ = "google"

import csv
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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

_QUESTION_RE = re.compile(r"^(\d+): (.*)$", re.DOTALL)
_FINISHED_STATES = ("complete", "pending_review")


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
    rows = list(csv.reader(io.StringIO(text.removeprefix("\ufeff"))))
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
            answer = row[col] if col < len(row) else ""
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
) -> list[QuizResponse]:
    """Fill due dates, lateness, and auto-submission flags in place.

    - ``due_at``: the student's own due date (``cached_due_date``, which
      respects overrides and extensions, and may be ``None``), else
      ``default_due`` for students missing from *due_by_user*.
    - ``late``: ``submitted_at > due_at`` when both are known.
    - ``attempt``: the latest finished attempt number, for latest-only reports.
    - ``started_at`` / ``auto_submitted``: from the student's latest quiz
      submission, on that attempt only. ``auto_submitted`` means Canvas
      closed the attempt (``finished_at >= end_at``): a time limit ran out,
      or an attempt left open was force-submitted when the course concluded.

    Returns:
        The same list, for chaining.
    """
    latest = {s.user_id: s for s in quiz_submissions}
    for r in responses:
        sub = latest.get(r.user_id) if r.user_id is not None else None
        if r.attempt is None and sub and sub.workflow_state in _FINISHED_STATES:
            r.attempt = sub.attempt
        due = due_by_user.get(r.user_id, default_due) if r.user_id else default_due
        r.due_at = _iso_utc(due)
        submitted, due_at = _parse(r.submitted_at), _parse(r.due_at)
        r.late = submitted > due_at if submitted and due_at else None
        if sub and r.attempt is not None and sub.attempt == r.attempt:
            r.started_at = _iso_utc(sub.started_at)
            finished, end = _parse(sub.finished_at), _parse(sub.end_at)
            r.auto_submitted = finished >= end if finished and end else False
    return responses


def fetch_quiz_responses(
    client: CanvasClient, quiz: CanvasQuiz, *, all_attempts: bool = False
) -> list[QuizResponse]:
    """Download, reshape, and time-stamp every student's answers to a quiz.

    Args:
        client: Canvas client for the quiz's course.
        quiz: Classic quiz or survey.
        all_attempts: Include every attempt, not only each student's latest.
    """
    text = client.download_quiz_report(quiz.id, all_versions=all_attempts)
    responses = parse_student_analysis(text)
    due_by_user: dict[int, str | None] = {}
    if quiz.assignment_id:
        due_by_user = {
            s.user_id: s.cached_due_date
            for s in client.list_submissions(quiz.assignment_id)
        }
    return add_timing(
        responses,
        due_by_user=due_by_user,
        quiz_submissions=client.list_quiz_submissions(quiz.id),
        default_due=quiz.due_at,
    )


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
    parsed = _parse(value)
    if parsed is None:
        return value or None
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
