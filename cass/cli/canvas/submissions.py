"""``cass canvas submissions`` — list, excuse and clear late flags."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, Annotated

import click
import typer

from . import _common

if TYPE_CHECKING:
    from ...actions.submissions import SubmissionCommand
    from ...apis.canvas.schema import CanvasSubmissionResponse

submissions_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Submissions — list, excuse, clear-late.",
)


@submissions_app.callback()
def submissions_callback(ctx: typer.Context) -> None:
    """Bare ``submissions`` shows this help."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


_LIST_STUDENT_OPTION = typer.Option(
    None, "--student", help="Canvas user ID; repeatable"
)


@submissions_app.command(name="list")
def submissions_list(
    assignment: str = typer.Argument(..., help="Assignment ID or name"),
    student_ids: list[int] | None = _LIST_STUDENT_OPTION,
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show each student's submission status and score."""
    from rich.markup import escape

    from ...actions.submissions import submission_rows, submissions_may_be_pending
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        target = c.resolve_assignment(assignment)
        subs = submission_rows(c, target, student_ids=student_ids or [])
        tz = c.time_zone

    if not subs and submissions_may_be_pending(target):
        _common.err_console.print(
            "[yellow]Canvas adds submissions a few seconds after an assignment "
            "is created; try again shortly.[/yellow]"
        )

    if as_json:
        _common.emit_json_lines(subs)
        return

    headers = [
        "Student",
        "Canvas ID",
        "State",
        "Submitted",
        "Due",
        "Late",
        "Missing",
        "Excused",
        "Late policy",
        "Score",
    ]
    title = f"Submissions: {target.name}"
    if csv_out:
        rows = [_list_row(sub, tz, styled=False) for sub in subs]
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        rows = [_list_row(sub, tz, styled=False) for sub in subs]
        report.save_markdown(save, title, headers, rows)
    else:
        rows = [_list_row(sub, tz, styled=True) for sub in subs]
        report.render_list(headers, rows, title=escape(title))


def _list_row(sub: CanvasSubmissionResponse, tz: str, *, styled: bool) -> list[str]:
    """One ``submissions list`` row; *styled* rows are Rich markup for the table.

    Styled rows escape Canvas text, so a name like ``[/x]`` prints as typed.
    """
    from rich.markup import escape

    def text(value: str) -> str:
        return escape(value) if styled else value

    def flag(value: bool | None) -> str:
        if styled:
            return _common.pub(value)
        return "" if value is None else ("yes" if value else "no")

    return [
        text(sub.user.name if sub.user else str(sub.user_id)),
        str(sub.user_id),
        text(sub.workflow_state),
        _common.when(sub.submitted_at, tz),
        _common.when(sub.cached_due_date, tz),
        flag(sub.late),
        flag(sub.missing),
        flag(sub.excused),
        text(sub.late_policy_status or ""),
        "" if sub.score is None else f"{sub.score:g}",
    ]


_TITLES = {"excuse": "Excuse", "clear-late": "Clear late"}
_DONE = {"excuse": "Excused", "clear-late": "Cleared late on"}


def _run(
    kind: SubmissionCommand,
    assignment: str,
    student_ids: list[int],
    enrolled_after: str,
    *,
    apply: bool,
    dry_run: bool,
    include_graded: bool = False,
) -> None:
    """Plan an ``excuse`` or ``clear-late`` command; send it only with *apply*."""
    from rich.markup import escape

    from ...actions.submissions import (
        apply_submission_changes,
        check_target_options,
        plan_submission_command,
    )
    from .. import report

    if apply and dry_run:
        raise click.UsageError("--apply and --dry-run cannot be combined.")
    try:
        check_target_options(
            has_assignment=bool(assignment),
            student_ids=student_ids,
            enrolled_after=enrolled_after,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    _common.require_canvas()
    with _common.client(dry_run=not apply) as c:
        target = c.resolve_assignment(assignment) if assignment else None
        plan = plan_submission_command(
            c,
            kind,
            assignment=target,
            student_ids=student_ids,
            enrolled_after=enrolled_after,
            include_graded=include_graded,
        )
        for warning in plan.warnings:
            _common.err_console.print(
                warning, markup=False, highlight=False, soft_wrap=True
            )
        if not plan.changes:
            _common.err_console.print("No matching submissions.")
            return
        title = _TITLES[kind] + ("" if apply else " (dry run)")
        report.render_list(
            ["Action", "Assignment", "Student", "Detail"],
            [[escape(cell) for cell in row] for row in plan.rows],
            title=title,
        )
        summary = ", ".join(f"{n} {action}" for action, n in plan.counts.items())
        _common.console.print(f"  {summary}", markup=False, highlight=False)
        applied = apply_submission_changes(c, plan.changes)

    if not apply:
        _common.print_plan(c)
        if c.planned_requests:
            _common.err_console.print("Dry run — use --apply to send these changes.")
        return
    if not applied:
        _common.err_console.print("Nothing to send.")
        return
    _common.console.print(
        f"{_DONE[kind]} {len(applied)} submission(s).", markup=False, highlight=False
    )


_STUDENT_OPTION = typer.Option(
    None, "--student", help="Canvas user ID; repeatable (needs an ASSIGNMENT)"
)
_ENROLLED_AFTER_HELP = (
    "Students first enrolled after DATE (course time zone), "
    "on assignments due before they enrolled"
)


@submissions_app.command(name="excuse")
def submissions_excuse(
    assignment: Annotated[
        str, typer.Argument(help="Assignment ID or name (limits --enrolled-after)")
    ] = "",
    student_ids: list[int] | None = _STUDENT_OPTION,
    enrolled_after: str = typer.Option(
        "", "--enrolled-after", help=_ENROLLED_AFTER_HELP
    ),
    include_graded: bool = typer.Option(
        False, "--include-graded", help="Also excuse submissions that have a grade"
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the changes"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change (the default)"
    ),
) -> None:
    """Excuse submissions; a dry run unless --apply."""
    _run(
        "excuse",
        assignment,
        student_ids or [],
        enrolled_after,
        apply=apply,
        dry_run=dry_run,
        include_graded=include_graded,
    )


@submissions_app.command(name="clear-late")
def submissions_clear_late(
    assignment: Annotated[
        str, typer.Argument(help="Assignment ID or name (limits --enrolled-after)")
    ] = "",
    student_ids: list[int] | None = _STUDENT_OPTION,
    enrolled_after: str = typer.Option(
        "", "--enrolled-after", help=_ENROLLED_AFTER_HELP
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the changes"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change (the default)"
    ),
) -> None:
    """Clear late flags and penalties; a dry run unless --apply."""
    _run(
        "clear-late",
        assignment,
        student_ids or [],
        enrolled_after,
        apply=apply,
        dry_run=dry_run,
    )
