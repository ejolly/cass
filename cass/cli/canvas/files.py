"""``cass canvas files`` — list, upload, delete."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import console, due, err_console, size

files_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course files — list, upload, delete.",
)


@files_app.callback()
def files_callback(ctx: typer.Context) -> None:
    """Course files; bare ``files`` runs ``files list``."""
    if ctx.invoked_subcommand is None:
        files_list(csv_out="", save="", as_json=False)


@files_app.command(name="list")
def files_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show course files as a tree."""
    from rich.tree import Tree

    from ...actions.canvas_records import file_tree_records
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        tz = c.time_zone
        folders = c.list_folders()
        all_files = c.list_files()

    if as_json:
        _common.emit_json_lines(file_tree_records(folders, all_files))
        return

    if csv_out or save:
        headers = ["ID", "Name", "Size", "Type", "Folder", "Created"]
        folder_names = {f.id: f.full_name for f in folders}
        rows = [
            [
                str(f.id),
                f.display_name,
                size(f.size),
                f.content_type,
                folder_names.get(f.folder_id, ""),
                due(f.created_at, tz),
            ]
            for f in all_files
        ]
        if csv_out:
            report.write_csv_file(csv_out, headers=headers, rows=rows)
        else:
            report.save_markdown(save, "Files", headers, rows)
        return

    # Build tree view
    tree = Tree("[bold]Course Files[/bold]")
    folder_nodes: dict[int, Tree] = {}
    for fld in sorted(folders, key=lambda f: f.full_name):
        label = f"[bold]{fld.name}[/bold]"
        if fld.parent_folder_id and fld.parent_folder_id in folder_nodes:
            node = folder_nodes[fld.parent_folder_id].add(label)
        else:
            node = tree.add(label)
        folder_nodes[fld.id] = node

    # Add files to their folders
    for f in sorted(all_files, key=lambda f: f.display_name):
        label = f"{f.display_name}  [dim]{size(f.size)}  id={f.id}[/dim]"
        parent = folder_nodes.get(f.folder_id)
        if parent:
            parent.add(label)
        else:
            tree.add(label)

    console.print()
    console.print(tree)
    console.print()


@files_app.command(name="upload")
def files_upload(
    path: str = typer.Argument(..., help="Local file path to upload"),
    folder: str = typer.Option("", "--folder", help="Destination folder in Canvas"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Upload a file to the course."""
    import os

    _common.require_canvas()
    if not os.path.isfile(path):
        err_console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(code=1)

    with _common.client(dry_run=dry_run) as c:
        f = c.upload_file(path, folder=folder)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Uploaded:[/green] {f.display_name} (id={f.id})")


@files_app.command(name="delete")
def files_delete(
    id_or_name: str = typer.Argument(..., help="File ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Delete a file from the course."""
    from ..prompts import confirm

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        f = c.resolve_file(id_or_name)
        confirm(f"Delete file '{f.display_name}'?", yes=yes, dry_run=dry_run)
        c.delete_file(f.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[red]Deleted file:[/red] {f.display_name}")
