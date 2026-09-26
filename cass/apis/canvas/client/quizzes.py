"""Classic quizzes, quiz questions, reports, and quiz submissions."""

from __future__ import annotations

__docformat__ = "google"

import time
from typing import Any

import httpx
import msgspec

from ....actions.quizzes import (
    QuestionSpec,
    QuizSpec,
    default_question_points,
    quiz_form_fields,
)
from ..schema import (
    CanvasQuiz,
    CanvasQuizAnswer,
    CanvasQuizQuestion,
    CanvasQuizReport,
    CanvasQuizSubmission,
)
from .base import BaseClient


class QuizzesMixin(BaseClient):
    """Classic quizzes and quiz questions."""

    def list_quizzes(self) -> list[CanvasQuiz]:
        """List all course quizzes.

        Returns:
            Quizzes of all types.
        """
        data = self._get_paginated(self._course("/quizzes"))
        return msgspec.convert(data, list[CanvasQuiz], strict=False)

    def get_quiz(self, quiz_id: int) -> CanvasQuiz:
        """Get a single quiz by ID."""
        resp = self._client.get(self._course(f"/quizzes/{quiz_id}"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasQuiz, strict=False)

    def create_quiz(
        self, spec: QuizSpec, *, assignment_group_id: int | None = None
    ) -> CanvasQuiz:
        """Create a quiz with its questions.

        Posts the quiz unpublished, posts each question in order, then re-saves
        the quiz (applying ``spec.published``) so Canvas recomputes
        ``question_count`` and ``points_possible``. If a question post fails
        the partial quiz is deleted and the error re-raised.

        Args:
            spec: Settings and questions; times are parsed in the course zone.
            assignment_group_id: Assignment group to place the quiz in.

        Returns:
            The quiz as re-fetched after the re-save.
        """
        fields = quiz_form_fields(
            spec, self.time_zone, assignment_group_id=assignment_group_id
        )
        fields["published"] = False
        resp = self._client.post(self._course("/quizzes"), data=_quiz_form(fields))
        resp.raise_for_status()
        quiz = msgspec.convert(resp.json(), CanvasQuiz, strict=False)
        try:
            for position, question in enumerate(spec.questions, 1):
                self.create_quiz_question(
                    quiz.id, question, position, quiz_type=spec.quiz_type
                )
            # Classic quizzes recount questions and points only after a re-save.
            resave: dict[str, object] = {
                "published": spec.published,
                "notify_of_update": False,
            }
            self._client.put(
                self._course(f"/quizzes/{quiz.id}"), data=_quiz_form(resave)
            ).raise_for_status()
        except Exception:
            self.delete_quiz(quiz.id)
            raise
        return self.get_quiz(quiz.id)

    def update_quiz(self, quiz_id: int, changes: dict[str, object]) -> CanvasQuiz:
        """Update quiz settings.

        Only the given Canvas fields are sent; questions are never touched.

        Args:
            quiz_id: Canvas quiz ID.
            changes: Canvas field name → new value (see ``quiz_settings_diff``).

        Returns:
            The updated quiz.
        """
        resp = self._client.put(
            self._course(f"/quizzes/{quiz_id}"), data=_quiz_form(changes)
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasQuiz, strict=False)

    def list_quiz_questions(
        self, quiz_id: int
    ) -> tuple[list[CanvasQuizQuestion], bool]:
        """List a quiz's questions in position order.

        Concluded courses return 403 from the questions endpoint; then the
        questions are rebuilt from ``/statistics``, which carries text and
        which answers are correct but no answer weights or names.

        Returns:
            ``(questions, used_statistics_fallback)``.
        """
        try:
            data = self._get_paginated(self._course(f"/quizzes/{quiz_id}/questions"))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403:
                raise
        else:
            questions = msgspec.convert(data, list[CanvasQuizQuestion], strict=False)
            return sorted(questions, key=lambda q: q.position or 0), False

        resp = self._client.get(self._course(f"/quizzes/{quiz_id}/statistics"))
        resp.raise_for_status()
        stats = resp.json().get("quiz_statistics") or []
        raw_questions = stats[0].get("question_statistics", []) if stats else []
        questions = [
            CanvasQuizQuestion(
                id=_as_int(q.get("id")),
                question_text=q.get("question_text", ""),
                question_type=q.get("question_type", ""),
                position=_as_int(q.get("position")) or index,
                answers=[
                    CanvasQuizAnswer(
                        id=_as_int(a.get("id")),
                        text=a.get("text", ""),
                        weight=100.0 if a.get("correct") else 0.0,
                    )
                    for a in q.get("answers", [])
                ],
            )
            for index, q in enumerate(raw_questions, 1)
        ]
        return sorted(questions, key=lambda q: q.position or 0), True

    def create_quiz_question(
        self,
        quiz_id: int,
        question: QuestionSpec,
        position: int,
        *,
        quiz_type: str = "assignment",
    ) -> CanvasQuizQuestion:
        """Add one question to a quiz.

        Args:
            quiz_id: Canvas quiz ID.
            question: Question spec; ``points`` ``None`` uses the type default.
            position: 1-based position; also the default name (``Question N``).
            quiz_type: Decides the default points (0 for surveys, else 1).

        Returns:
            The created question.
        """
        points = (
            question.points
            if question.points is not None
            else default_question_points(quiz_type)
        )
        payload: dict[str, object] = {
            "question_name": question.name or f"Question {position}",
            "question_text": question.text,
            "question_type": question.type,
            "points_possible": _number(points),
            "position": position,
        }
        if question.answers:
            payload["answers"] = [
                {"answer_text": a.text, "answer_weight": 100 if a.correct else 0}
                for a in question.answers
            ]
        resp = self._client.post(
            self._course(f"/quizzes/{quiz_id}/questions"), json={"question": payload}
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasQuizQuestion, strict=False)

    def delete_quiz(self, quiz_id: int) -> None:
        """Delete a quiz."""
        resp = self._client.delete(self._course(f"/quizzes/{quiz_id}"))
        resp.raise_for_status()

    def create_quiz_report(
        self, quiz_id: int, *, all_versions: bool = False
    ) -> CanvasQuizReport:
        """Ask Canvas to generate a student analysis report.

        Canvas returns the existing report when one is already current, so
        repeating the call is cheap. Works on concluded courses.

        Args:
            quiz_id: Canvas quiz ID.
            all_versions: Report every attempt instead of only the latest.

        Returns:
            The report; ``file`` is ``None`` until generation finishes.
        """
        resp = self._client.post(
            self._course(f"/quizzes/{quiz_id}/reports"),
            data={
                "quiz_report[report_type]": "student_analysis",
                "quiz_report[includes_all_versions]": str(all_versions).lower(),
                "include[]": ["file", "progress"],
            },
        )
        resp.raise_for_status()
        return _quiz_report(resp.json())

    def get_quiz_report(self, quiz_id: int, report_id: int) -> CanvasQuizReport:
        """Get a quiz report with its file and progress."""
        resp = self._client.get(
            self._course(f"/quizzes/{quiz_id}/reports/{report_id}"),
            params={"include[]": ["file", "progress"]},
        )
        resp.raise_for_status()
        return _quiz_report(resp.json())

    def download_quiz_report(
        self,
        quiz_id: int,
        *,
        all_versions: bool = False,
        timeout: float = 300.0,
        interval: float = 2.0,
    ) -> str:
        """Generate a student analysis report, wait for it, and download it.

        Generation typically takes about 30 seconds.

        Args:
            quiz_id: Canvas quiz ID.
            all_versions: Report every attempt instead of only the latest.
            timeout: Maximum seconds to wait for Canvas to build the file.
            interval: Seconds between polls.

        Returns:
            The report CSV text.

        Raises:
            RuntimeError: If generation fails or times out.
        """
        report = self.create_quiz_report(quiz_id, all_versions=all_versions)
        deadline = time.monotonic() + timeout
        while report.file is None or not report.file.url:
            if report.progress and report.progress.workflow_state == "failed":
                detail = report.progress.message or "unknown error"
                raise RuntimeError(f"Canvas quiz report failed: {detail}")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Canvas quiz report not ready after {timeout:.0f}s")
            time.sleep(interval)
            report = self.get_quiz_report(quiz_id, report.id)
        resp = self._client.get(report.file.url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content.decode("utf-8-sig")

    def list_quiz_submissions(self, quiz_id: int) -> list[CanvasQuizSubmission]:
        """List each student's latest attempt on a quiz.

        Returns:
            One quiz submission per student who opened the quiz.
        """
        data = self._get_paginated(self._course(f"/quizzes/{quiz_id}/submissions"))
        pages = msgspec.convert(data, list[_QuizSubmissionsPage], strict=False)
        return [sub for page in pages for sub in page.quiz_submissions]

    def resolve_quiz(self, id_or_name: str) -> CanvasQuiz:
        """Resolve a quiz by numeric ID or title (case-insensitive).

        Raises:
            RuntimeError: If no quiz matches.
        """
        if id_or_name.isdigit():
            return self.get_quiz(int(id_or_name))
        return self._resolve(self.list_quizzes(), id_or_name, "Quiz", lambda q: q.title)


def _quiz_form(fields: dict[str, object]) -> dict[str, object]:
    """Wrap fields as ``quiz[<key>]`` form params."""
    return {f"quiz[{k}]": v for k, v in fields.items()}


class _QuizSubmissionsPage(msgspec.Struct):
    """``/quizzes/:id/submissions`` wraps each page in an envelope."""

    quiz_submissions: list[CanvasQuizSubmission] = []


def _quiz_report(data: Any) -> CanvasQuizReport:
    """Unwrap a report from either the plain or the JSON-API envelope."""
    if isinstance(data, dict) and data.get("quiz_reports"):
        data = data["quiz_reports"][0]
    return msgspec.convert(data, CanvasQuizReport, strict=False)


def _number(value: float) -> int | float:
    """Send whole numbers without a trailing ``.0``."""
    return int(value) if float(value).is_integer() else value


def _as_int(value: object) -> int:
    """Statistics payloads mix int and string IDs; 0 when absent."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
