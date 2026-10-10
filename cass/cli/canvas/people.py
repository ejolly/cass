"""``cass canvas people`` and ``people list`` — the course roster."""

from __future__ import annotations

__docformat__ = "google"

import typer

from ...actions.enrollments import EnrollmentState
from . import _common

people_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course roster — list.",
)


@people_app.callback()
def people_callback(ctx: typer.Context) -> None:
    """Course roster; bare ``people`` runs ``people list``."""
    if ctx.invoked_subcommand is None:
        people_list(csv_out="", save="", enrolled_after="", states=None, as_json=False)


_STATE_OPTION = typer.Option(
    None, "--state", help="Enrollment state; repeatable (default: active and invited)"
)


@people_app.command(name="list")
def people_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    enrolled_after: str = typer.Option(
        "",
        "--enrolled-after",
        help="Only people (any role) first enrolled after DATE (course time zone)",
    ),
    states: list[EnrollmentState] | None = _STATE_OPTION,
    as_json: bool = _common.json_option(),
) -> None:
    """Show course roster with roles, emails and enrolled dates."""
    from rich.markup import escape

    from ...actions.enrollments import person_record, roster
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        users, dates = roster(
            c,
            states=[state.value for state in states or []],
            enrolled_after=enrolled_after,
        )
        tz = c.time_zone

    if as_json:
        _common.emit_json_lines(person_record(u, dates.get(u.id)) for u in users)
        return

    headers = ["Name", "Role", "Email", "SIS ID", "Canvas ID", "Enrolled"]
    rows = [
        [
            u.name,
            u.enrollments[0].role if u.enrollments else "",
            u.email,
            u.sis_user_id or "",
            str(u.id),
            _common.when(dates.get(u.id), tz),
        ]
        for u in users
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "People", headers, rows)
    else:
        report.render_list(
            headers, [[escape(cell) for cell in row] for row in rows], title="People"
        )
