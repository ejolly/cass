"""``cass canvas tabs list`` / ``show-tab`` / ``hide-tab``."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import canvas_app, console

tabs_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Navigation tabs — list.",
)


@tabs_app.callback()
def tabs_callback(ctx: typer.Context) -> None:
    """Navigation tabs; bare ``tabs`` runs ``tabs list``."""
    if ctx.invoked_subcommand is None:
        tabs_list(csv_out="", save="")


@tabs_app.command(name="list")
def tabs_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List course navigation tabs."""
    from .. import report

    _common.require_canvas()
    with _common.client() as c:
        tab_list = c.list_tabs()

    headers = ["Label", "Type", "Position", "Visibility", "ID"]
    rows = [
        [
            t.label,
            t.type,
            str(t.position or ""),
            "hidden" if t.hidden else "visible",
            t.id,
        ]
        for t in sorted(tab_list, key=lambda t: t.position or 999)
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Tabs", headers, rows)
    else:
        report.render_list(headers, rows, title="Tabs")


@canvas_app.command(name="show-tab", rich_help_panel="Manage")
def tabs_show(
    id_or_label: str = typer.Argument(..., help="Tab ID or label"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Make a navigation tab visible."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        tab = c.resolve_tab(id_or_label)
        t = c.update_tab(tab.id, hidden=False)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Visible:[/green] {t.label}")


@canvas_app.command(name="hide-tab", rich_help_panel="Manage")
def tabs_hide(
    id_or_label: str = typer.Argument(..., help="Tab ID or label"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Hide a navigation tab."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        tab = c.resolve_tab(id_or_label)
        t = c.update_tab(tab.id, hidden=True)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[yellow]Hidden:[/yellow] {t.label}")
