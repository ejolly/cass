"""Finished student attempts on a quiz, and refusing changes once there are any.

Commitment C2: cass never deletes or alters a quiz that has student attempts.
"""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import CanvasClient
    from .schema import CanvasQuiz, CanvasQuizSubmission

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

    Any error reading either count propagates, so an unknown count never
    allows a change.
    """
    student_ids = {s.id for s in client.list_students()}
    current = sum(
        1
        for sub in client.list_quiz_submissions(quiz_id)
        if sub.user_id in student_ids and has_finished_attempt(sub)
    )
    return max(current, client.count_quiz_takers(quiz_id))


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
    """
    count = count_finished_attempts(client, quiz.id) if attempts is None else attempts
    if count > 0:
        raise QuizHasAttemptsError(quiz.title, count, change)
