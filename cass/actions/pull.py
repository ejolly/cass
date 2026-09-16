"""Pull orchestration — fetch Canvas data into the local database."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Callable

from rich.console import Console

from .. import db
from ..apis.canvas import matching as canvas_api
from ..db.schema import CanvasAssignment, CanvasStudent, CanvasSubmission
from .config import Config

ProgressCallback = Callable[[str, str], None]


def _fetch_students(cfg: Config) -> int:
    """Fetch the Canvas roster into ``canvas_students`` and return the count."""
    students_api, section_map = canvas_api.fetch_students_with_sections(
        cfg.canvas_course_id
    )
    sections = section_map or {}
    return db.save_canvas_students(
        [
            CanvasStudent.from_api(s, sis_section_id=sections.get(s.id, ""))
            for s in students_api
        ]
    )


def _fetch_assignments(cfg: Config) -> int:
    """Fetch Canvas assignments into ``canvas_assignments`` and return the count."""
    assignments_api, group_names = canvas_api.fetch_canvas_assignments(
        cfg.canvas_course_id
    )
    groups = group_names or {}
    return db.save_canvas_assignments(
        [
            CanvasAssignment.from_api(
                a, group_name=groups.get(a.assignment_group_id, "")
            )
            for a in assignments_api
        ]
    )


def _fetch_submissions(cfg: Config) -> int:
    """Fetch submissions for every stored assignment and return the count."""
    student_ids = db.load_canvas_student_ids()
    submissions: list[CanvasSubmission] = []
    for assignment_id in db.load_canvas_assignment_ids():
        submissions.extend(
            canvas_api.fetch_canvas_submissions(
                cfg.canvas_course_id, assignment_id, student_ids
            )
        )
    return db.save_canvas_submissions(submissions)


def pull_students(cfg: Config, console: Console) -> None:
    """CLI step: pull the Canvas roster."""
    console.print("[bold]Pulling students from Canvas...[/bold]")
    count = _fetch_students(cfg)
    console.print(f"  [green]{count} Canvas students[/green]")


def pull_assignments(cfg: Config, console: Console) -> None:
    """CLI step: pull Canvas assignments."""
    console.print("[bold]Pulling assignments from Canvas...[/bold]")
    count = _fetch_assignments(cfg)
    console.print(f"  [green]{count} Canvas assignments[/green]")


def pull_submissions(cfg: Config, console: Console) -> None:
    """CLI step: pull Canvas submissions for every stored assignment."""
    if not db.load_canvas_assignment_ids():
        console.print("[yellow]No assignments. Pull assignments first.[/yellow]")
        return
    console.print("[bold]Pulling submissions from Canvas...[/bold]")
    count = _fetch_submissions(cfg)
    console.print(f"  [green]{count} Canvas submissions[/green]")


def pull_all(cfg: Config, on_progress: ProgressCallback | None = None) -> None:
    """Run a full pull: course name, students, assignments, submissions.

    Shared by ``cass pull`` and the viewer's progress page. Progress is
    reported through *on_progress(step, detail)* with steps ``students``,
    ``assignments``, ``submissions``, and ``done``.

    Raises:
        RuntimeError: when local Canvas edits would be overwritten.
    """
    if (reason := db.pull_block_reason()) is not None:
        raise RuntimeError(reason)

    def report(step: str, detail: str) -> None:
        if on_progress is not None:
            on_progress(step, detail)

    db.save_meta("course_name", canvas_api.fetch_course_name(cfg.canvas_course_id))

    report("students", "Pulling Canvas students...")
    report("students", f"{_fetch_students(cfg)} Canvas students")

    report("assignments", "Pulling Canvas assignments...")
    report("assignments", f"{_fetch_assignments(cfg)} Canvas assignments")

    report("submissions", "Pulling Canvas submissions...")
    report("submissions", f"{_fetch_submissions(cfg)} Canvas submissions")

    db.snapshot_canvas_synced()
    report("done", "Pull complete")
