"""``cass canvas modules`` — list, create, publish, delete, add-item."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import console, pub

modules_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course modules — list, create, publish, delete.",
)


@modules_app.callback()
def modules_callback(
    ctx: typer.Context,
    module_id: str = typer.Option("", "--id", help="Module ID or name to show items"),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List modules, or show items in a specific module."""
    if ctx.invoked_subcommand is not None:
        return
    _common.require_canvas()

    from .. import report

    with _common.client() as c:
        if module_id:
            mod = c.resolve_module(module_id)
            items = c.list_module_items(mod.id)
            headers = ["ID", "Title", "Type", "Content ID", "Published"]
            rows = [
                [
                    str(it.id),
                    it.title,
                    it.type,
                    str(it.content_id or ""),
                    pub(it.published),
                ]
                for it in items
            ]
            title = f"Module: {mod.name}"
        else:
            modules = c.list_modules()
            headers = ["ID", "Position", "Name", "Published", "Items"]
            rows = [
                [
                    str(m.id),
                    str(m.position),
                    m.name,
                    pub(m.published),
                    str(m.items_count),
                ]
                for m in modules
            ]
            title = "Modules"

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, title, headers, rows)
    else:
        report.render_list(headers, rows, title=title)


@modules_app.command()
def create(
    name: str = typer.Argument(..., help="Module name"),
    position: int | None = typer.Option(None, "--position", help="Position in list"),
) -> None:
    """Create a new module."""
    _common.require_canvas()
    with _common.client() as c:
        mod = c.create_module(name, position=position)
    console.print(f"[green]Created module:[/green] {mod.name} (id={mod.id})")


@modules_app.command(name="publish")
def modules_publish(
    id_or_name: str | None = typer.Argument(None, help="Module ID or name"),
    all_modules: bool = typer.Option(False, "--all", help="Publish all modules"),
) -> None:
    """Publish a module (or all modules with --all)."""
    _common.require_canvas()
    if not all_modules and not id_or_name:
        console.print("[red]Give a module ID or name, or --all.[/red]")
        raise typer.Exit(code=1)
    with _common.client() as c:
        if all_modules:
            modules = c.list_modules()
            for m in modules:
                c.publish("modules", m.id)
                console.print(f"  [green]Published:[/green] {m.name}")
        else:
            mod = c.resolve_module(id_or_name or "")
            c.publish("modules", mod.id)
            console.print(f"[green]Published:[/green] {mod.name}")


@modules_app.command(name="unpublish")
def modules_unpublish(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
) -> None:
    """Unpublish a module."""
    _common.require_canvas()
    with _common.client() as c:
        mod = c.resolve_module(id_or_name)
        c.unpublish("modules", mod.id)
    console.print(f"[yellow]Unpublished:[/yellow] {mod.name}")


@modules_app.command(name="delete")
def modules_delete(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a module."""
    _common.require_canvas()
    with _common.client() as c:
        mod = c.resolve_module(id_or_name)
        if not yes and not typer.confirm(f"Delete module '{mod.name}'?"):
            raise typer.Abort()
        c.delete_module(mod.id)
    console.print(f"[red]Deleted:[/red] {mod.name}")


@modules_app.command(name="add-item")
def modules_add_item(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    item_type: str = typer.Option(
        ..., "--type", help="Item type (Assignment, Quiz, File, Page, etc.)"
    ),
    content_id: int = typer.Option(
        ..., "--content-id", help="Canvas ID of the content"
    ),
    title: str | None = typer.Option(
        None, "--title", help="Item title (defaults to content name)"
    ),
) -> None:
    """Add an item to a module."""
    _common.require_canvas()
    with _common.client() as c:
        mod = c.resolve_module(id_or_name)
        item = c.create_module_item(
            mod.id, item_type=item_type, content_id=content_id, title=title
        )
    console.print(f"[green]Added:[/green] {item.title} to {mod.name}")
