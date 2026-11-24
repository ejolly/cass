"""Pull orchestration — fetch Canvas data into the local database."""

from __future__ import annotations

__docformat__ = "google"

import json
from collections.abc import Callable

from rich.console import Console

from .. import db
from ..apis.canvas import matching as canvas_api
from ..apis.canvas.sync import resolve_row_name
from ..db.schema import (
    CanvasAssignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
)
from .config import Config

ProgressCallback = Callable[[str, str], None]
# A progress step (``removed`` or ``kept``) and the text to show the user.
Notice = tuple[str, str]


def _removed_notices(kind: str, names: list[str]) -> list[Notice]:
    """Name each student or assignment removed because Canvas no longer lists it."""
    return [
        (
            "removed",
            f"Removed {kind} {name}, with local submissions and grades: "
            f"Canvas no longer lists this {kind}",
        )
        for name in names
    ]


def _kept_notices(kind: str, count: int) -> list[Notice]:
    """Say that local rows were kept because Canvas returned none."""
    if count == 0:
        return []
    return [("kept", f"Canvas returned no {kind}; kept {count} local {kind}")]


def _pulled_assignment_ids() -> list[int]:
    """IDs of stored assignments that exist on Canvas; local ones are negative."""
    return [aid for aid in db.load_canvas_assignment_ids() if aid > 0]


def _fetch_students(cfg: Config) -> tuple[int, list[Notice]]:
    """Fetch the Canvas roster into ``canvas_students``, removing departed students.

    Returns:
        The student count, and notices of removed or kept students.

    Raises:
        RuntimeError: when an edit was made during the fetch.
    """
    stored = db.load_canvas_student_ids()
    students_api, section_map = canvas_api.fetch_students_with_sections(
        cfg.canvas_course_id
    )
    sections = section_map or {}
    count = db.save_canvas_students(
        [
            CanvasStudent.from_api(s, sis_section_id=sections.get(s.id, ""))
            for s in students_api
        ]
    )
    if not students_api:
        return count, _kept_notices("students", len(db.load_canvas_student_ids()))
    names, kept = db.remove_departed_students({s.id for s in students_api}, stored)
    return count, [
        *_removed_notices("student", names),
        *_kept_grade_notices(kept),
    ]


def _fetch_assignments(cfg: Config) -> tuple[list[int], list[Notice]]:
    """Fetch Canvas assignments into ``canvas_assignments``, removing deleted ones.

    Returns:
        The IDs of the listed assignments, and notices of removed or kept ones.

    Raises:
        RuntimeError: when an edit was made during the fetch.
    """
    stored = set(db.load_canvas_assignment_ids())
    assignments_api, group_names = canvas_api.fetch_canvas_assignments(
        cfg.canvas_course_id
    )
    groups = group_names or {}
    db.save_pulled_assignments(
        [
            CanvasAssignment.from_api(
                a, group_name=groups.get(a.assignment_group_id, "")
            )
            for a in assignments_api
        ]
    )
    if not assignments_api:
        return [], _kept_notices("assignments", len(_pulled_assignment_ids()))
    listed_ids = sorted(a.id for a in assignments_api)
    names, kept = db.remove_deleted_assignments(set(listed_ids), stored)
    return listed_ids, [
        *_removed_notices("assignment", names),
        *_kept_grade_notices(kept),
    ]


def _kept_grade_notice(
    user_id: int, assignment_id: int, canvas_grade: str | None
) -> str:
    """Tell the user about a local grade that pull kept instead of the Canvas one.

    ``canvas_grade`` is None when Canvas sent no value for the grade.
    """
    pk_key = json.dumps(
        {"canvas_assignment_id": assignment_id, "canvas_user_id": user_id}
    )
    name = resolve_row_name(db.get_db(), "canvas_grades", pk_key)
    if canvas_grade is None:
        return (
            f"{name}: kept your local grade, which may be unpushed; Canvas lists no "
            "grade to compare it with. After a full pull it is pending: `cass push` "
            "cannot send it while Canvas lists none. Only `cass revert`, which deletes "
            "it, clears it, so record the grade or run `cass backup` first."
        )
    on_canvas = f"has {canvas_grade}" if canvas_grade else "has no grade"
    return (
        f"{name}: kept your local grade, but Canvas {on_canvas}. "
        "Push or revert it with `cass push` or `cass revert`."
    )


def _kept_grade_notices(
    kept: list[tuple[int, int]],
    canvas_grades: dict[tuple[int, int], str] | None = None,
) -> list[Notice]:
    """Name each kept grade, given the grades Canvas sent."""
    sent = canvas_grades or {}
    return [("kept", _kept_grade_notice(*key, sent.get(key))) for key in kept]


def _fetch_submissions(
    cfg: Config, assignment_ids: list[int], *, full_pull: bool
) -> tuple[int, list[Notice]]:
    """Fetch submissions and grades for the given assignments.

    Returns:
        The submission count, and a notice for each local grade that was kept.

    Raises:
        RuntimeError: when an edit made during the fetch would be overwritten.
    """
    student_ids = db.load_canvas_student_ids()
    submissions: list[CanvasSubmission] = []
    for assignment_id in assignment_ids:
        submissions.extend(
            canvas_api.fetch_canvas_submissions(
                cfg.canvas_course_id, assignment_id, student_ids
            )
        )
    canvas_grades = {
        (s.canvas_user_id, s.canvas_assignment_id): s.entered_grade for s in submissions
    }
    kept = db.save_pulled_grades(
        [
            CanvasGrade(
                canvas_user_id=s.canvas_user_id,
                canvas_assignment_id=s.canvas_assignment_id,
                score=s.score,
                posted_grade=s.entered_grade,
            )
            for s in submissions
        ],
        full_pull=full_pull,
    )
    count = db.save_canvas_submissions(submissions)
    return count, _kept_grade_notices(kept, canvas_grades)


def _print_notices(console: Console, notices: list[Notice]) -> None:
    """Print notices literally: names from Canvas may hold Rich markup."""
    for _, notice in notices:
        console.print(f"  {notice}", style="yellow", markup=False)


def pull_students(cfg: Config, console: Console) -> None:
    """CLI step: pull the Canvas roster."""
    console.print("[bold]Pulling students from Canvas...[/bold]")
    count, notices = _fetch_students(cfg)
    console.print(f"  [green]{count} Canvas students[/green]")
    _print_notices(console, notices)


def pull_assignments(cfg: Config, console: Console) -> None:
    """CLI step: pull Canvas assignments."""
    console.print("[bold]Pulling assignments from Canvas...[/bold]")
    listed_ids, notices = _fetch_assignments(cfg)
    console.print(f"  [green]{len(listed_ids)} Canvas assignments[/green]")
    _print_notices(console, notices)


def pull_submissions(cfg: Config, console: Console) -> None:
    """CLI step: pull Canvas submissions and grades for every stored assignment."""
    assignment_ids = _pulled_assignment_ids()
    if not assignment_ids:
        console.print("[yellow]No assignments. Pull assignments first.[/yellow]")
        return
    console.print("[bold]Pulling submissions from Canvas...[/bold]")
    count, notices = _fetch_submissions(cfg, assignment_ids, full_pull=False)
    console.print(f"  [green]{count} Canvas submissions[/green]")
    _print_notices(console, notices)


def pull_all(cfg: Config, on_progress: ProgressCallback | None = None) -> None:
    """Run a full pull: course name, students, assignments, submissions, grades.

    Shared by ``cass pull`` and the viewer's progress page. Progress is
    reported through *on_progress(step, detail)* with steps ``students``,
    ``assignments``, ``submissions``, ``removed`` (once for each student or
    assignment removed because Canvas no longer lists it), ``kept`` (local
    students, assignments, or a grade kept where Canvas differs), and ``done``.

    Raises:
        RuntimeError: when local Canvas edits would be overwritten.
    """
    if (reason := db.pull_block_reason()) is not None:
        raise RuntimeError(reason)

    def report(step: str, detail: str) -> None:
        if on_progress is not None:
            on_progress(step, detail)

    db.save_meta("course_name", canvas_api.fetch_course_name(cfg.canvas_course_id))

    reported: set[Notice] = set()

    def report_new(notices: list[Notice]) -> None:
        for step, text in notices:
            if (step, text) not in reported:
                report(step, text)
                reported.add((step, text))

    report("students", "Pulling Canvas students...")
    student_count, notices = _fetch_students(cfg)
    report("students", f"{student_count} Canvas students")
    report_new(notices)

    report("assignments", "Pulling Canvas assignments...")
    listed_ids, notices = _fetch_assignments(cfg)
    report("assignments", f"{len(listed_ids)} Canvas assignments")
    report_new(notices)

    if listed_ids:
        report("submissions", "Pulling Canvas submissions...")
        # With no students, a missing grade says nothing about what Canvas has.
        full_pull = student_count > 0
        count, notices = _fetch_submissions(cfg, listed_ids, full_pull=full_pull)
        report("submissions", f"{count} Canvas submissions")
        if full_pull:
            db.save_meta(db.GRADE_BASELINES_KEY, "1")
        report_new(notices)
    else:
        report("submissions", "Not pulled: Canvas returned no assignments")
        if _pulled_assignment_ids():
            report(
                "kept",
                "Submissions and grades of the kept assignments were not refreshed",
            )

    report("done", "Pull complete")
