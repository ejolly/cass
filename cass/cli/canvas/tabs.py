"""``cass canvas tabs`` / ``show-tab`` / ``hide-tab``."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import canvas_app, console


@canvas_app.command(rich_help_panel="Browse")
def tabs(
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
) -> None:
    """Make a navigation tab visible."""
    _common.require_canvas()
    with _common.client() as c:
        tab = c.resolve_tab(id_or_label)
        t = c.update_tab(tab.id, hidden=False)
    console.print(f"[green]Visible:[/green] {t.label}")


@canvas_app.command(name="hide-tab", rich_help_panel="Manage")
def tabs_hide(
    id_or_label: str = typer.Argument(..., help="Tab ID or label"),
) -> None:
    """Hide a navigation tab."""
    _common.require_canvas()
    with _common.client() as c:
        tab = c.resolve_tab(id_or_label)
        t = c.update_tab(tab.id, hidden=True)
    console.print(f"[yellow]Hidden:[/yellow] {t.label}")
