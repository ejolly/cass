"""``cass canvas submissions`` — list, excuse and clear late flags."""

from __future__ import annotations

__docformat__ = "google"

from typing import Annotated

import typer

from . import _common

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


@submissions_app.command(name="list")
def submissions_list(
    assignment: str = typer.Argument(..., help="Assignment ID or name"),
    student_ids: Annotated[
        list[int],
        typer.Option("--student", help="Canvas user ID; repeatable"),
    ] = [],  # noqa: B006
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show each student's submission state, lateness and score."""
    from ...actions.submissions import submission_rows
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        target = c.resolve_assignment(assignment)
        subs = submission_rows(c, target, student_ids=student_ids)
        tz = c.time_zone

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
    rows = [
        [
            sub.user.name if sub.user else str(sub.user_id),
            str(sub.user_id),
            sub.workflow_state,
            _common.when(sub.submitted_at, tz),
            _common.when(sub.cached_due_date, tz),
            _common.pub(sub.late),
            _common.pub(sub.missing),
            _common.pub(sub.excused),
            sub.late_policy_status or "",
            "" if sub.score is None else f"{sub.score:g}",
        ]
        for sub in subs
    ]
    title = f"Submissions: {target.name}"
    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, title, headers, rows)
    else:
        report.render_list(headers, rows, title=title)
