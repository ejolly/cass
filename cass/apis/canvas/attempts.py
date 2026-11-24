"""Finished student attempts on a quiz, and refusing changes once there are any.

Commitment C2: cass never deletes or alters a quiz that has student attempts.
"""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

import httpx
import msgspec

if TYPE_CHECKING:
    from .client import CanvasClient
    from .schema import CanvasAssignmentResponse, CanvasQuiz, CanvasQuizSubmission

FINISHED_ATTEMPT_STATES = ("complete", "pending_review")


class QuizHasAttemptsError(RuntimeError):
    """A change cass refuses because students have finished the quiz (C2)."""

    def __init__(self, title: str, attempts: int, change: str) -> None:
        super().__init__(
            f"Quiz {title!r} has {attempts} finished student attempt(s), so cass "
            f"won't {change}. Make this change in the Canvas web app, which "
            "handles regrading existing attempts."
        )
        self.attempts = attempts


class QuizAttemptsUnknownError(RuntimeError):
    """A change cass refuses because it cannot tell whether there are attempts."""

    def __init__(self, quiz_id: int, reason: str) -> None:
        super().__init__(
            f"cass could not check quiz {quiz_id} for student attempts "
            f"({reason}), so it did not make this change. Make it in the "
            "Canvas web app."
        )


def failed_request_reason(exc: httpx.HTTPError) -> str:
    """Say why a request failed, without Canvas's response text."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Canvas answered with status {exc.response.status_code}"
    return "could not reach Canvas"


def has_finished_attempt(submission: CanvasQuizSubmission) -> bool:
    """Return whether a student has finished at least one attempt.

    Canvas lists only each student's latest attempt and sets it back to
    ``untaken`` when a retake starts, so a later attempt number also means an
    earlier attempt is finished.
    """
    return (
        submission.workflow_state in FINISHED_ATTEMPT_STATES
        or (submission.attempt or 0) > 1
    )


def count_finished_attempts(client: CanvasClient, quiz_id: int) -> int:
    """Count students with a finished attempt on a quiz, including mid-retake.

    Returns the larger of two counts, because each can miss students the other
    has: the submissions list covers current students only, and quiz statistics
    also cover concluded and inactive students but may leave out a retake in
    progress. Neither includes students whose enrollment was deleted. Teacher
    previews and the Test Student never count.

    Raises:
        QuizAttemptsUnknownError: Canvas gave no roster or submissions list, or
            it gave no statistics count and no current student has a finished
            attempt, so whether there are any is unknown. When current students
            do, their count is returned.
    """
    try:
        student_ids = {s.id for s in client.list_students()}
        submissions = client.list_quiz_submissions(quiz_id)
    except httpx.HTTPError as exc:
        raise QuizAttemptsUnknownError(quiz_id, failed_request_reason(exc)) from None
    except (ValueError, msgspec.MsgspecError):
        reason = "Canvas returned no list of attempts"
        raise QuizAttemptsUnknownError(quiz_id, reason) from None
    current = sum(
        1
        for sub in submissions
        if sub.user_id in student_ids and has_finished_attempt(sub)
    )
    try:
        takers = client.count_quiz_takers(quiz_id)
    except RuntimeError:
        # Current students' attempts are enough to refuse the change.
        if current > 0:
            return current
        raise
    return max(current, takers)


def refuse_if_attempted(
    client: CanvasClient,
    quiz: CanvasQuiz,
    change: str,
    *,
    attempts: int | None = None,
) -> None:
    """Raise if students have finished the quiz.

    Args:
        client: Canvas client; only reads.
        quiz: The quiz about to change.
        change: What cass was about to do, e.g. ``"delete it"``.
        attempts: A count already fetched; otherwise it is fetched.

    Raises:
        QuizHasAttemptsError: At least one finished student attempt exists.
        QuizAttemptsUnknownError: Whether one exists could not be checked.
    """
    count = count_finished_attempts(client, quiz.id) if attempts is None else attempts
    if count > 0:
        raise QuizHasAttemptsError(quiz.title, count, change)


def refuse_if_assignment_attempted(
    client: CanvasClient, assignment: CanvasAssignmentResponse, change: str
) -> None:
    """Raise if the assignment is a quiz students have finished.

    Args:
        client: Canvas client; only reads.
        assignment: The assignment about to change. Sends nothing unless it is
            a quiz.
        change: What cass was about to do, e.g. ``"delete it"``.

    Raises:
        QuizHasAttemptsError: At least one finished student attempt exists.
        QuizAttemptsUnknownError: Whether one exists could not be checked.
    """
    if assignment.quiz_id is None:
        return
    count = count_finished_attempts(client, assignment.quiz_id)
    if count > 0:
        raise QuizHasAttemptsError(assignment.name, count, change)
