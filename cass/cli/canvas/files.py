"""``cass canvas files`` / ``upload`` / ``delete-file``."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import canvas_app, console, due, size


@canvas_app.command(rich_help_panel="Browse")
def files(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show course files as a tree."""
    from rich.tree import Tree

    from .. import report

    _common.require_canvas()
    with _common.client() as c:
        tz = c.time_zone
        folders = c.list_folders()
        all_files = c.list_files()

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


@canvas_app.command(name="upload", rich_help_panel="Manage")
def files_upload(
    path: str = typer.Argument(..., help="Local file path to upload"),
    folder: str = typer.Option("", "--folder", help="Destination folder in Canvas"),
) -> None:
    """Upload a file to the course."""
    import os

    _common.require_canvas()
    if not os.path.isfile(path):
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(code=1)

    with _common.client() as c:
        f = c.upload_file(path, folder=folder)
    console.print(f"[green]Uploaded:[/green] {f.display_name} (id={f.id})")


@canvas_app.command(name="delete-file", rich_help_panel="Manage")
def files_delete(
    file_id: int = typer.Argument(..., help="Canvas file ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a file from the course."""
    _common.require_canvas()
    if not yes and not typer.confirm(f"Delete file {file_id}?"):
        raise typer.Abort()
    with _common.client() as c:
        c.delete_file(file_id)
    console.print(f"[red]Deleted file {file_id}[/red]")
