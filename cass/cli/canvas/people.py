"""``cass canvas people`` and ``people list`` — the course roster."""

from __future__ import annotations

__docformat__ = "google"

import typer

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
        people_list(csv_out="", save="", as_json=False)


@people_app.command(name="list")
def people_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show course roster with roles and emails."""
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        users = c.list_users()

    if as_json:
        _common.emit_json_lines(users)
        return

    headers = ["Name", "Role", "Email", "SIS ID", "Canvas ID"]
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
            ]
        )

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "People", headers, rows)
    else:
        report.render_list(headers, rows, title="People")
