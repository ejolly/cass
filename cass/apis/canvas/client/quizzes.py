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
    file_layout,
    group_form_fields,
    group_members,
    question_form_fields,
    quiz_form_fields,
)
from ..schema import (
    CanvasQuiz,
    CanvasQuizAnswer,
    CanvasQuizGroup,
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
        return msgspec.convert(resp.json(), CanvasQuiz, strict=False)

    def create_quiz(
        self, spec: QuizSpec, *, assignment_group_id: int | None = None
    ) -> CanvasQuiz:
        """Create a quiz with its questions.

        Posts the quiz unpublished, creates the declared question groups, posts
        each question in file order (into its group), orders groups and entries
        when there are groups, then re-saves the quiz (applying
        ``spec.published``) so Canvas recomputes
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
        quiz = msgspec.convert(resp.json(), CanvasQuiz, strict=False)
        try:
            group_ids = {
                group.name: self.create_question_group(
                    quiz.id, group_form_fields(group, spec.quiz_type)
                ).id
                for group in spec.groups
            }
            question_ids: list[int] = []
            for position, question in enumerate(spec.questions, 1):
                created = self.create_quiz_question(
                    quiz.id,
                    question,
                    position,
                    quiz_type=spec.quiz_type,
                    quiz_group_id=group_ids[question.group] if question.group else None,
                )
                question_ids.append(created.id)
            if spec.groups:
                self._order_created_quiz(quiz.id, spec, group_ids, question_ids)
            # Classic quizzes recount questions and points only after a re-save.
            self.resave_quiz(quiz.id, published=spec.published)
        except Exception:
            self.delete_quiz(quiz.id)
            raise
        return self.get_quiz(quiz.id)

    def _order_created_quiz(
        self,
        quiz_id: int,
        spec: QuizSpec,
        group_ids: dict[str, int],
        question_ids: list[int],
    ) -> None:
        """Put a freshly created quiz's entries and group members in file order."""
        top_level: list[tuple[str, int]] = []
        for kind, key in file_layout(spec):
            if kind == "group":
                top_level.append(("group", group_ids[str(key)]))
            else:
                top_level.append(("question", question_ids[int(key)]))
        self.reorder_quiz(quiz_id, top_level)
        for name, indices in group_members(spec).items():
            self.reorder_question_group(
                quiz_id, group_ids[name], [question_ids[i] for i in indices]
            )

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
        quiz_group_id: int | None = None,
    ) -> CanvasQuizQuestion:
        """Add one question to a quiz.

        Args:
            quiz_id: Canvas quiz ID.
            question: Question spec; ``points`` ``None`` uses the type default.
            position: 1-based position.
            quiz_type: Decides the default points (0 for surveys, else 1).
            quiz_group_id: Question group to put the question in.

        Returns:
            The created question.
        """
        payload = question_form_fields(question, quiz_type)
        payload["position"] = position
        if quiz_group_id is not None:
            payload["quiz_group_id"] = quiz_group_id
        resp = self._client.post(
            self._course(f"/quizzes/{quiz_id}/questions"), json={"question": payload}
        )
        return msgspec.convert(resp.json(), CanvasQuizQuestion, strict=False)

    def update_quiz_question(
        self, quiz_id: int, question_id: int, fields: dict[str, object]
    ) -> CanvasQuizQuestion:
        """Update one question (one call).

        Args:
            quiz_id: Canvas quiz ID.
            question_id: Canvas question ID.
            fields: Canvas question field → new value, e.g. ``question_text``.

        Returns:
            The updated question.
        """
        resp = self._client.put(
            self._course(f"/quizzes/{quiz_id}/questions/{question_id}"),
            json={"question": fields},
        )
        return msgspec.convert(resp.json(), CanvasQuizQuestion, strict=False)

    def delete_quiz_question(self, quiz_id: int, question_id: int) -> None:
        """Delete one question (one call)."""
        self._client.delete(self._course(f"/quizzes/{quiz_id}/questions/{question_id}"))

    def create_question_group(
        self, quiz_id: int, fields: dict[str, object]
    ) -> CanvasQuizGroup:
        """Create a question group (one call).

        Args:
            quiz_id: Canvas quiz ID.
            fields: Canvas group fields: ``name``, ``pick_count``,
                ``question_points``.

        Returns:
            The created group.
        """
        resp = self._client.post(
            self._course(f"/quizzes/{quiz_id}/groups"), json={"quiz_groups": [fields]}
        )
        return _quiz_group(resp.json())

    def update_question_group(
        self, quiz_id: int, group_id: int, fields: dict[str, object]
    ) -> CanvasQuizGroup:
        """Update a question group (one call); same fields as the create."""
        resp = self._client.put(
            self._course(f"/quizzes/{quiz_id}/groups/{group_id}"),
            json={"quiz_groups": [fields]},
        )
        return _quiz_group(resp.json())

    def delete_question_group(self, quiz_id: int, group_id: int) -> None:
        """Delete a question group (one call)."""
        self._client.delete(self._course(f"/quizzes/{quiz_id}/groups/{group_id}"))

    def get_question_group(self, quiz_id: int, group_id: int) -> CanvasQuizGroup:
        """Get one question group (one call).

        Canvas has no endpoint that lists a quiz's groups.
        """
        resp = self._client.get(self._course(f"/quizzes/{quiz_id}/groups/{group_id}"))
        return _quiz_group(resp.json())

    def reorder_quiz(self, quiz_id: int, items: list[tuple[str, int]]) -> None:
        """Set the quiz's top-level order (one call).

        Args:
            quiz_id: Canvas quiz ID.
            items: ``("question" | "group", id)`` in the wanted order.
        """
        self.request(
            "POST",
            self._course(f"/quizzes/{quiz_id}/reorder"),
            data=_reorder_pairs(items),
        )

    def reorder_question_group(
        self, quiz_id: int, group_id: int, question_ids: list[int]
    ) -> None:
        """Set the order of the questions inside a group (one call)."""
        items = [("question", question_id) for question_id in question_ids]
        self.request(
            "POST",
            self._course(f"/quizzes/{quiz_id}/groups/{group_id}/reorder"),
            data=_reorder_pairs(items),
        )

    def resave_quiz(self, quiz_id: int, *, published: bool | None = None) -> None:
        """Re-save a quiz without notifying students (one call).

        Classic quizzes recount questions and points, and fill in question
        positions, only after a re-save.

        Args:
            quiz_id: Canvas quiz ID.
            published: Also set the published state when given.
        """
        fields: dict[str, object] = {}
        if published is not None:
            fields["published"] = published
        fields["notify_of_update"] = False
        self._client.put(self._course(f"/quizzes/{quiz_id}"), data=_quiz_form(fields))

    def delete_quiz(self, quiz_id: int) -> None:
        """Delete a quiz."""
        self._client.delete(self._course(f"/quizzes/{quiz_id}"))

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
        return _quiz_report(resp.json())

    def get_quiz_report(self, quiz_id: int, report_id: int) -> CanvasQuizReport:
        """Get a quiz report with its file and progress."""
        resp = self._client.get(
            self._course(f"/quizzes/{quiz_id}/reports/{report_id}"),
            params={"include[]": ["file", "progress"]},
        )
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
        return resp.content.decode("utf-8-sig")

    def list_quiz_submissions(self, quiz_id: int) -> list[CanvasQuizSubmission]:
        """List each student's latest attempt on a quiz.

        Returns:
            One quiz submission per student who opened the quiz.
        """
        data = self._get_paginated(self._course(f"/quizzes/{quiz_id}/submissions"))
        pages = msgspec.convert(data, list[_QuizSubmissionsPage], strict=False)
        return [sub for page in pages for sub in page.quiz_submissions]

    def start_quiz_preview(self, quiz_id: int) -> CanvasQuizSubmission:
        """Start a teacher preview attempt on a quiz.

        Returns:
            The preview's quiz submission.

        Raises:
            RuntimeError: Canvas returned no quiz submission.
        """
        resp = self._client.post(
            self._course(f"/quizzes/{quiz_id}/submissions"),
            params={"preview": "true"},
        )
        page = msgspec.convert(resp.json(), _QuizSubmissionsPage, strict=False)
        if not page.quiz_submissions:
            raise RuntimeError(
                f"Canvas returned no preview submission for quiz {quiz_id}."
            )
        return page.quiz_submissions[0]

    def list_submission_questions(self, submission_id: int) -> list[CanvasQuizQuestion]:
        """List the questions of one quiz submission in the order it was drawn."""
        resp = self._client.get(f"/quiz_submissions/{submission_id}/questions")
        page = msgspec.convert(resp.json(), _SubmissionQuestionsPage, strict=False)
        return page.quiz_submission_questions

    def resolve_quiz_id(self, id_or_name: str) -> int:
        """A quiz's ID from a numeric ID (no request) or a title.

        Raises:
            RuntimeError: If no quiz has that title.
        """
        if id_or_name.isdigit():
            return int(id_or_name)
        return self.resolve_quiz(id_or_name).id

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


class _SubmissionQuestionsPage(msgspec.Struct):
    """``/quiz_submissions/:id/questions`` wraps the list in an envelope."""

    quiz_submission_questions: list[CanvasQuizQuestion] = []


def _reorder_pairs(items: list[tuple[str, int]]) -> list[tuple[str, object]]:
    """Form pairs Canvas reads as a list of ``{id, type}`` objects."""
    pairs: list[tuple[str, object]] = []
    for kind, item_id in items:
        pairs += [("order[][id]", item_id), ("order[][type]", kind)]
    return pairs


def _quiz_group(data: Any) -> CanvasQuizGroup:
    """Unwrap a group from either the plain or the ``quiz_groups`` envelope."""
    if isinstance(data, dict) and data.get("quiz_groups"):
        data = data["quiz_groups"][0]
    return msgspec.convert(data, CanvasQuizGroup, strict=False)


def _quiz_report(data: Any) -> CanvasQuizReport:
    """Unwrap a report from either the plain or the JSON-API envelope."""
    if isinstance(data, dict) and data.get("quiz_reports"):
        data = data["quiz_reports"][0]
    return msgspec.convert(data, CanvasQuizReport, strict=False)


def _as_int(value: object) -> int:
    """Statistics payloads mix int and string IDs; 0 when absent."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
