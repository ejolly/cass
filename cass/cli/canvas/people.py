"""``cass canvas people`` and ``people list`` — the course roster."""

from __future__ import annotations

__docformat__ = "google"

from typing import Annotated

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
        people_list(csv_out="", save="", enrolled_after="", states=[], as_json=False)


@people_app.command(name="list")
def people_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    enrolled_after: str = typer.Option(
        "",
        "--enrolled-after",
        help="Only people first enrolled after DATE (course time zone)",
    ),
    states: Annotated[
        list[EnrollmentState],
        typer.Option(
            "--state",
            help="Enrollment state; repeatable (default: active and invited)",
        ),
    ] = [],  # noqa: B006
    as_json: bool = _common.json_option(),
) -> None:
    """Show course roster with roles, emails and enrollment dates."""
    from ...actions.enrollments import (
        enrollment_dates,
        fetch_all_enrollments,
        person_record,
        select_people,
    )
    from ...apis.canvas.times import parse_when
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        users = c.list_users(states=[s.value for s in states])
        dates = enrollment_dates(fetch_all_enrollments(c))
        cutoff = parse_when(enrolled_after, c.time_zone) if enrolled_after else ""
        tz = c.time_zone
    users = select_people(users, dates, cutoff)

    if as_json:
        _common.emit_json_lines(person_record(u, dates.get(u.id)) for u in users)
        return

    headers = ["Name", "Role", "Email", "SIS ID", "Canvas ID", "Enrolled"]
    rows: list[list[str]] = []
    for u in sorted(users, key=lambda u: u.sortable_name or u.name):
        role = ""
        if u.enrollments:
            role = u.enrollments[0].role
        rows.append(
            [
                u.name,
                role,
                u.email,
                u.sis_user_id or "",
                str(u.id),
                _common.when(dates.get(u.id), tz),
            ]
        )

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "People", headers, rows)
    else:
        report.render_list(headers, rows, title="People")
