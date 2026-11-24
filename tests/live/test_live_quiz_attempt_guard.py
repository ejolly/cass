"""Live tests for refusing changes to quizzes students have finished (C2).

The practice course's seeded quiz has a finished attempt by the Test Student
only, which must not block changes. A real course (``$CASS_LIVE_REAL_COURSE``)
checks the refusal against real student attempts, read-only: the refusal comes
before any write, and the CLI runs as a dry run.
"""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import sqlite_utils
from live_course import CONFIG_PATH, QUIZ_TITLE, get_test_student_id
from seed_practice_course import submit_attempt
from typer.testing import CliRunner

from cass import db
from cass.actions.config import get_config, set_config_path
from cass.actions.quizzes import count_finished_attempts, load_quiz_file
from cass.apis.canvas.attempts import (
    FINISHED_ATTEMPT_STATES,
    QuizAttemptsUnknownError,
    QuizHasAttemptsError,
)
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.schema import (
    CanvasAssignmentGroup,
    CanvasAssignmentResponse,
    CanvasQuiz,
    CanvasStudentResponse,
)
from cass.cli import app
from cass.db import CanvasAssignment
from cass.db.sync import HELD_QUIZ_ATTEMPTS

runner = CliRunner()


def test_test_student_attempt_does_not_count(practice: CanvasClient):
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    student_id = get_test_student_id(practice)
    finished = [
        s
        for s in practice.list_quiz_submissions(quiz.id)
        if s.user_id == student_id and s.workflow_state in FINISHED_ATTEMPT_STATES
    ]
    assert finished, "seed-live should leave a finished Test Student attempt"
    assert practice.count_quiz_takers(quiz.id) == 0
    assert count_finished_attempts(practice, quiz.id) == 0


@pytest.mark.usefixtures("practice_cli_client")
def test_delete_dry_run_allowed_with_only_test_student(practice: CanvasClient):
    quiz = practice.resolve_quiz(QUIZ_TITLE)
    result = runner.invoke(
        app, ["canvas", "quizzes", "delete", str(quiz.id), "--yes", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "DELETE" in result.stdout


@pytest.mark.usefixtures("practice_cli_client")
def test_retake_in_progress_still_refuses(
    practice: CanvasClient, monkeypatch: pytest.MonkeyPatch
):
    """Starting a retake hides the finished attempt's state but must still count.

    The Test Student stands in for a rostered student.
    """
    student_id = get_test_student_id(practice)
    spec = load_quiz_file(CONFIG_PATH.parent / "quizzes" / "live-quiz.toml")
    spec = replace(spec, title=f"cass-live retake {uuid4().hex[:8]}")
    quiz = practice.create_quiz(spec)
    try:
        submit_attempt(practice, quiz.id, student_id, ["Wrong", "<p>x</p>", "halo"])
        monkeypatch.setattr(
            CanvasClient,
            "list_students",
            lambda self: [CanvasStudentResponse(id=student_id, name="Test Student")],
        )
        assert count_finished_attempts(practice, quiz.id) == 1

        practice.request(
            "POST",
            f"/courses/{practice.course_id}/quizzes/{quiz.id}/submissions",
            params={"as_user_id": student_id},
        )
        (latest,) = practice.list_quiz_submissions(quiz.id)
        assert (latest.attempt, latest.workflow_state) == (2, "untaken")
        assert count_finished_attempts(practice, quiz.id) == 1

        result = runner.invoke(
            app, ["canvas", "quizzes", "delete", str(quiz.id), "--yes", "--dry-run"]
        )
        assert result.exit_code == 1, result.output
        assert "won't delete it" in str(result.exception)
    finally:
        practice.delete_quiz(quiz.id)


@contextmanager
def throwaway_quiz(
    practice: CanvasClient, *, published: bool = True
) -> Iterator[tuple[CanvasQuiz, CanvasAssignmentResponse, CanvasAssignmentGroup]]:
    """A quiz alone in a new assignment group, both deleted afterwards."""
    name = f"cass-live guard {uuid4().hex[:8]}"
    spec = load_quiz_file(CONFIG_PATH.parent / "quizzes" / "live-quiz.toml")
    spec = replace(spec, title=name, published=published)
    group = practice.create_assignment_group(name)
    try:
        try:
            quiz = practice.create_quiz(spec, assignment_group_id=group.id)
            (assignment,) = [
                a for a in practice.list_assignments() if a.quiz_id == quiz.id
            ]
            yield quiz, assignment, group
        finally:
            for left in practice.list_quizzes():
                if left.title == name:
                    practice.delete_quiz(left.id)
    finally:
        if group.id in {g.id for g in practice.list_assignment_groups()}:
            practice.delete_assignment_group(group.id)


def quiz_ids(client: CanvasClient) -> set[int]:
    return {q.id for q in client.list_quizzes()}


def edit_points_locally(
    conn: sqlite_utils.Database, assignment: CanvasAssignmentResponse, points: float
) -> None:
    """Store the assignment as pulled, then change its points."""
    db.save_canvas_assignments(
        [
            CanvasAssignment(
                canvas_id=assignment.id,
                name=assignment.name,
                points_possible=assignment.points_possible or 0.0,
                published=assignment.published,
            )
        ]
    )
    db.snapshot_canvas_synced(conn)
    conn.execute("UPDATE canvas_assignments SET points_possible = ?", [points])


@pytest.fixture
def push_to_practice(practice: CanvasClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point pushes, which open their own client, at the practice course."""

    def same_client() -> CanvasClient:
        return CanvasClient(
            get_config().canvas_base_url,
            course_id=practice.course_id,
            auth=practice.auth,
            time_zone=practice.time_zone,
        )

    monkeypatch.setattr("cass.apis.canvas.client.CanvasClient", same_client)


@pytest.mark.usefixtures("practice_cli_client", "push_to_practice")
def test_assignment_routes_refused_for_attempted_quiz(
    practice: CanvasClient,
    db_conn: sqlite_utils.Database,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Deletes and points changes through the assignment leave the quiz as it was.

    The Test Student stands in for a rostered student.
    """
    student_id = get_test_student_id(practice)
    monkeypatch.setattr(
        CanvasClient,
        "list_students",
        lambda self: [CanvasStudentResponse(id=student_id, name="Test Student")],
    )
    with throwaway_quiz(practice) as (quiz, assignment, group):
        submit_attempt(practice, quiz.id, student_id, ["Wrong", "<p>x</p>", "halo"])

        for args in (
            ["delete", str(assignment.id)],
            ["groups", "delete", str(group.id)],
        ):
            result = runner.invoke(app, ["canvas", "assignments", *args, "--yes"])
            assert result.exit_code == 1, result.output
            assert isinstance(result.exception, QuizHasAttemptsError)
            assert quiz.id in quiz_ids(practice)

        edit_points_locally(db_conn, assignment, 77.0)
        pending = db.get_pending_changes(db_conn)
        preview = db.canvas_preview(db_conn, pending)
        to_push, held = db.hold_back_unapproved(
            pending, preview, overwrite_conflicts=True
        )
        assert to_push == {}
        assert [h["held"] for h in held] == [HELD_QUIZ_ATTEMPTS]
        # As if the student finished the quiz after the preview.
        applied = db.canvas_apply(db_conn, pending)
        assert not applied["ok"]
        assert "finished student attempt(s)" in str(applied["results"])

        toml = tmp_path / "cass.toml"
        toml.write_text(
            f"""[canvas]
base_url = "{get_config().canvas_base_url}"
course_id = {practice.course_id}
time_zone = "{practice.time_zone}"

[[canvas.assignments]]
name = "{assignment.name}"
points = 77
"""
        )
        try:
            result = runner.invoke(
                app, ["--config", str(toml), "canvas", "sync", "--apply"]
            )
        finally:
            set_config_path(CONFIG_PATH)
        assert result.exit_code == 1, result.output
        assert "refuse" in result.stdout

        live = practice.get_assignment(assignment.id)
        assert live.points_possible == assignment.points_possible
        assert quiz.id in quiz_ids(practice)


@pytest.mark.usefixtures("push_to_practice")
def test_points_canvas_reverts_fail_the_push(
    practice: CanvasClient, db_conn: sqlite_utils.Database
):
    with throwaway_quiz(practice) as (_, assignment, _):
        edit_points_locally(db_conn, assignment, 77.0)
        pending = db.get_pending_changes(db_conn)
        assert db.hold_back_unapproved(
            pending, db.canvas_preview(db_conn, pending), overwrite_conflicts=True
        ) == (pending, [])
        result = db.canvas_apply(db_conn, pending)
        kept = assignment.points_possible
        assert f"Canvas kept points_possible at {kept}" in str(result["results"])
        assert not result["ok"]
        assert practice.get_assignment(assignment.id).points_possible == kept


def test_deleting_a_quiz_assignment_deletes_the_quiz(practice: CanvasClient):
    """Why the assignment routes need the guard."""
    with throwaway_quiz(practice) as (quiz, assignment, _):
        assert quiz.id in quiz_ids(practice)
        practice.delete_assignment(assignment.id)
        assert quiz.id not in quiz_ids(practice)


@contextmanager
def errors_without_details() -> Iterator[None]:
    """Fail with only the error's type: Canvas errors can quote student data."""
    try:
        yield
    except Exception as exc:
        pytest.fail(f"Real course read failed: {type(exc).__name__}", pytrace=False)


def _count_undercounted_quizzes(client: CanvasClient) -> tuple[int, int]:
    """Number of quizzes checked, and of those where statistics miss students.

    Only quizzes with a current student in a finished state are checked, and
    not those Canvas has no statistics for, which cass refuses to change.
    """
    student_ids = {s.id for s in client.list_students()}
    checked = 0
    undercounted = 0
    for quiz in client.list_quizzes():
        current = sum(
            1
            for s in client.list_quiz_submissions(quiz.id)
            if s.user_id in student_ids and s.workflow_state in FINISHED_ATTEMPT_STATES
        )
        try:
            takers = client.count_quiz_takers(quiz.id)
        except QuizAttemptsUnknownError:
            continue
        checked += current > 0
        undercounted += takers < current
    return checked, undercounted


def test_takers_at_least_current_attempts(real_course: CanvasClient):
    """Statistics never count fewer students than the submissions list."""
    with errors_without_details():
        checked, undercounted = _count_undercounted_quizzes(real_course)
    assert undercounted == 0
    if checked == 0:
        pytest.skip("The real course has no quiz with finished student attempts")


def _find_attempted_quiz_id(client: CanvasClient) -> int | None:
    """ID of the first quiz cass knows to have finished attempts, if any."""
    for quiz in client.list_quizzes():
        try:
            if count_finished_attempts(client, quiz.id) > 0:
                return quiz.id
        except QuizAttemptsUnknownError:
            continue
    return None


def test_real_quiz_with_attempts_refuses_delete(
    real_course: CanvasClient, monkeypatch: pytest.MonkeyPatch
):
    with errors_without_details():
        quiz_id = _find_attempted_quiz_id(real_course)
    if quiz_id is None:
        pytest.skip("The real course has no quiz with finished student attempts")
    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            get_config().canvas_base_url,
            course_id=real_course.course_id,
            auth=real_course.auth,
            dry_run=True,
        ),
    )

    result = runner.invoke(
        app, ["canvas", "quizzes", "delete", str(quiz_id), "--yes", "--dry-run"]
    )

    # Booleans first: a failed assert on the result would print its details.
    exited_with_error = result.exit_code == 1
    refused = isinstance(result.exception, QuizHasAttemptsError)
    assert exited_with_error
    assert refused
