"""``cass canvas modules`` — list, show, create, publish, delete, items."""

from __future__ import annotations

__docformat__ = "google"

import click
import typer

from . import _common
from ._common import console, err_console, pub

modules_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course modules — list, show, create, publish, delete, items.",
)


@modules_app.callback()
def modules_callback(ctx: typer.Context) -> None:
    """Course modules; bare ``modules`` runs ``modules list``."""
    if ctx.invoked_subcommand is None:
        modules_list(csv_out="", save="", as_json=False)


@modules_app.command(name="list")
def modules_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """List modules."""
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        modules = c.list_modules()

    if as_json:
        _common.emit_json_lines(modules)
        return

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

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Modules", headers, rows)
    else:
        report.render_list(headers, rows, title="Modules")


@modules_app.command(name="show")
def modules_show(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show the items in a module."""
    from ...actions.canvas_records import module_detail_record
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        mod = c.resolve_module(id_or_name)
        items = c.list_module_items(mod.id)

    if as_json:
        _common.emit_json(module_detail_record(mod, items))
        return

    headers = ["ID", "Position", "Indent", "Type", "Title", "Content ID", "Published"]
    rows = [
        [
            str(it.id),
            str(index),
            str(it.indent),
            it.type,
            it.title,
            str(it.content_id or ""),
            pub(it.published),
        ]
        for index, it in enumerate(items, start=1)
    ]
    title = f"Module: {mod.name}"

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
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Create a new module."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.create_module(name, position=position)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Created module:[/green] {mod.name} (id={mod.id})")


@modules_app.command(name="publish")
def modules_publish(
    id_or_name: str | None = typer.Argument(None, help="Module ID or name"),
    all_modules: bool = typer.Option(False, "--all", help="Publish all modules"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Publish a module (or all modules with --all)."""
    _common.require_canvas()
    if not all_modules and not id_or_name:
        err_console.print("[red]Give a module ID or name, or --all.[/red]")
        raise typer.Exit(code=1)
    with _common.client(dry_run=dry_run) as c:
        if all_modules:
            modules = c.list_modules()
            for module in modules:
                c.publish("modules", module.id)
            published = [module.name for module in modules]
        else:
            mod = c.resolve_module(id_or_name or "")
            c.publish("modules", mod.id)
            published = [mod.name]
    if dry_run:
        _common.print_plan(c)
        return
    for name in published:
        console.print(f"[green]Published:[/green] {name}")


@modules_app.command(name="unpublish")
def modules_unpublish(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Unpublish a module."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.resolve_module(id_or_name)
        c.unpublish("modules", mod.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[yellow]Unpublished:[/yellow] {mod.name}")


@modules_app.command(name="delete")
def modules_delete(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Delete a module."""
    from ..prompts import confirm

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.resolve_module(id_or_name)
        confirm(f"Delete module '{mod.name}'?", yes=yes, dry_run=dry_run)
        c.delete_module(mod.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[red]Deleted:[/red] {mod.name}")


items_app = typer.Typer(
    no_args_is_help=True, help="Module items — add, update, move, remove."
)
modules_app.add_typer(items_app, name="items")


@items_app.command(name="add")
def items_add(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    item_type: str = typer.Option(
        ...,
        "--type",
        help="Assignment, Quiz, File, Page, ExternalUrl or SubHeader",
    ),
    content_id: int | None = typer.Option(
        None, "--content-id", help="Canvas ID of the content (Assignment, Quiz, File)"
    ),
    page_url: str | None = typer.Option(
        None, "--page-url", help="Page slug (Page items)"
    ),
    url: str | None = typer.Option(
        None, "--url", help="Target URL (ExternalUrl items)"
    ),
    title: str | None = typer.Option(
        None, "--title", help="Item title (defaults to the content's name)"
    ),
    indent: int | None = typer.Option(None, "--indent", min=0, help="Indent level"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Add an item to a module."""
    from ...actions.module_items import check_item_add_args

    try:
        canonical = check_item_add_args(
            item_type,
            content_id=content_id,
            page_url=page_url,
            url=url,
            title=title,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.resolve_module(id_or_name)
        item = c.create_module_item(
            mod.id,
            item_type=canonical,
            content_id=content_id,
            title=title,
            indent=indent,
            page_url=page_url,
            external_url=url,
        )
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Added:[/green] {item.title} to {mod.name}")


@items_app.command(name="update")
def items_update(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    item: str = typer.Argument(..., help="Item ID or title"),
    title: str | None = typer.Option(None, "--title", help="New title"),
    indent: int | None = typer.Option(None, "--indent", min=0, help="New indent level"),
    published: bool | None = typer.Option(None, "--publish/--unpublish"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Change an item's title, indent or published state."""
    from ...actions.module_items import check_item_update_args

    try:
        check_item_update_args(title=title, indent=indent, published=published)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.resolve_module(id_or_name)
        current = c.resolve_module_item(mod.id, item)
        updated = c.update_module_item(
            mod.id,
            current.id,
            title=title,
            indent=indent,
            published=published,
            current=current,
        )
    if dry_run:
        _common.print_plan(c)
        return
    if updated is current:  # the client sent nothing: published already matched
        console.print(f"No changes: {current.title}")
        return
    console.print(f"[green]Updated:[/green] {updated.title}")


@items_app.command(name="move")
def items_move(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    item: str = typer.Argument(..., help="Item ID or title"),
    position: int = typer.Option(
        ..., "--position", min=1, help="New position (1 = first)"
    ),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Move an item to a position within its module."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.resolve_module(id_or_name)
        current = c.resolve_module_item(mod.id, item)
        c.update_module_item(mod.id, current.id, position=position)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Moved:[/green] {current.title} to position {position}")


@items_app.command(name="remove")
def items_remove(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    item: str = typer.Argument(..., help="Item ID or title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Remove an item from a module (the linked content is untouched)."""
    from ..prompts import confirm

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        mod = c.resolve_module(id_or_name)
        current = c.resolve_module_item(mod.id, item)
        confirm(
            f"Remove '{current.title}' from module '{mod.name}'?",
            yes=yes,
            dry_run=dry_run,
        )
        c.delete_module_item(mod.id, current.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[red]Removed:[/red] {current.title}")
