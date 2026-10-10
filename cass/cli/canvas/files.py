"""``cass canvas files`` — list, upload, move, rename, publish, delete; folders."""

from __future__ import annotations

__docformat__ = "google"

from typing import Annotated

import typer

from ...actions.files import OnConflict, OnDuplicate
from . import _common
from ._common import console, due, err_console, size

files_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course files — list, upload, move, rename, publish, delete; folders.",
)

folders_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course folders — list, create, delete.",
)
files_app.add_typer(folders_app, name="folders")


@files_app.callback()
def files_callback(ctx: typer.Context) -> None:
    """Course files; bare ``files`` runs ``files list``."""
    if ctx.invoked_subcommand is None:
        files_list(folder="", csv_out="", save="", as_json=False)


@files_app.command(name="list")
def files_list(
    folder: str = typer.Option(
        "", "--folder", help="Only this folder (ID or path) and its subfolders"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show course files as a tree."""
    from rich.tree import Tree

    from ...actions.canvas_records import file_tree_records
    from ...actions.files import folder_subtree
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        tz = c.time_zone
        folders = c.list_folders()
        all_files = c.list_files()
        if folder:
            folders, all_files = folder_subtree(
                folders, all_files, c.resolve_folder(folder)
            )

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
        label = f"[bold]{fld.name}[/bold]  [dim]id={fld.id}[/dim]"
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
    folder: str = typer.Option(
        "", "--folder", help="Destination folder in Canvas (created if missing)"
    ),
    name: str | None = typer.Option(
        None, "--name", help="Name in Canvas (default: local file name)"
    ),
    on_duplicate: Annotated[
        OnDuplicate,
        typer.Option(
            "--on-duplicate",
            case_sensitive=False,
            help=(
                "If the name exists: overwrite (default; replaces the file, "
                "which gets a new ID), rename (keep both), or skip (same name "
                "and size)"
            ),
        ),
    ] = OnDuplicate.OVERWRITE,
    unpublished: bool = typer.Option(
        False, "--unpublished", help="Lock the file so students cannot see it"
    ),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Upload a file to the course."""
    import os

    from ...actions.files import upload_course_file

    _common.require_canvas()
    if not os.path.isfile(path):
        err_console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(code=1)

    with _common.client(dry_run=dry_run) as c:
        result = upload_course_file(
            c,
            path,
            folder=folder,
            name=name,
            on_duplicate=on_duplicate,
            unpublished=unpublished,
        )
    f = result.file
    if result.skipped:
        from ...apis.canvas.client.files import normalize_folder_path

        where = normalize_folder_path(folder) or "the files root"
        console.print(
            f"[yellow]Skipped:[/yellow] {f.display_name} (id={f.id}) "
            f"is already in {where} with the same size"
        )
        return
    if dry_run:
        _common.print_plan(c)
        return
    suffix = ", unpublished" if unpublished else ""
    console.print(f"[green]Uploaded:[/green] {f.display_name} (id={f.id}){suffix}")


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


OnConflictOption = Annotated[
    OnConflict | None,
    typer.Option(
        "--on-duplicate",
        case_sensitive=False,
        help="If the name exists in the destination: rename or overwrite",
    ),
]


@files_app.command(name="mv")
def files_mv(
    id_or_name: str = typer.Argument(..., help="File ID or name"),
    folder: str = typer.Argument(
        ..., help="Destination folder path (created if missing); '' is the root"
    ),
    on_duplicate: OnConflictOption = None,
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Move a file to another folder."""
    from ...apis.canvas.client.files import normalize_folder_path

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        f = c.resolve_file(id_or_name)
        dest = c.create_folder(folder)
        c.update_file(
            f.id,
            folder_id=dest.id,
            on_duplicate=on_duplicate.value if on_duplicate else None,
        )
    if dry_run:
        _common.print_plan(c)
        return
    where = normalize_folder_path(folder) or "the files root"
    console.print(f"[green]Moved:[/green] {f.display_name} → {where}")


@files_app.command(name="rename")
def files_rename(
    id_or_name: str = typer.Argument(..., help="File ID or name"),
    new_name: str = typer.Argument(..., help="New file name"),
    on_duplicate: OnConflictOption = None,
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Rename a file."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        f = c.resolve_file(id_or_name)
        renamed = c.update_file(
            f.id,
            name=new_name,
            on_duplicate=on_duplicate.value if on_duplicate else None,
        )
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Renamed:[/green] {f.display_name} → {renamed.display_name}")


@files_app.command(name="publish")
def files_publish(
    id_or_name: str = typer.Argument(..., help="File ID or name"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Make a file visible to students."""
    _set_locked(id_or_name, locked=False, dry_run=dry_run)


@files_app.command(name="unpublish")
def files_unpublish(
    id_or_name: str = typer.Argument(..., help="File ID or name"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Hide a file from students (lock it)."""
    _set_locked(id_or_name, locked=True, dry_run=dry_run)


def _set_locked(id_or_name: str, *, locked: bool, dry_run: bool) -> None:
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        f = c.resolve_file(id_or_name)
        c.update_file(f.id, locked=locked)
    if dry_run:
        _common.print_plan(c)
        return
    label = "Unpublished" if locked else "Published"
    console.print(f"[green]{label}:[/green] {f.display_name}")


@folders_app.callback()
def folders_callback(ctx: typer.Context) -> None:
    """Course folders; bare ``folders`` runs ``folders list``."""
    if ctx.invoked_subcommand is None:
        folders_list(as_json=False)


@folders_app.command(name="list")
def folders_list(as_json: bool = _common.json_option()) -> None:
    """Show course folders with their paths."""
    from ...apis.canvas.client.files import folder_paths
    from .. import report

    _common.require_canvas()
    with _common.client() as c:
        folders = c.list_folders()

    if as_json:
        from ...actions.canvas_records import folder_records

        _common.emit_json_lines(folder_records(folders))
        return

    paths = folder_paths(folders)
    headers = ["ID", "Path", "Files", "Folders"]
    rows = [
        [str(f.id), paths[f.id] or "/", str(f.files_count), str(f.folders_count)]
        for f in sorted(folders, key=lambda f: paths[f.id])
    ]
    report.render_list(headers, rows, title="Course Folders")


@folders_app.command(name="create")
def folders_create(
    path: str = typer.Argument(..., help="Folder path (missing parents are created)"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Create a folder."""
    from ...apis.canvas.client.files import normalize_folder_path

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        folder = c.create_folder(path)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(
        f"[green]Created folder:[/green] {normalize_folder_path(path)} (id={folder.id})"
    )


@folders_app.command(name="delete")
def folders_delete(
    id_or_path: str = typer.Argument(..., help="Folder ID or path"),
    force: bool = typer.Option(
        False, "--force", help="Delete even if the folder holds files or folders"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Delete a folder."""
    from ...apis.canvas.client.files import folder_paths
    from ..prompts import confirm

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        folder = c.resolve_folder(id_or_path)
        if folder.parent_folder_id is None:
            raise RuntimeError("Cannot delete the course files root folder")
        path = folder_paths(c.list_folders())[folder.id]
        confirm(f"Delete folder '{path}'?", yes=yes, dry_run=dry_run)
        c.delete_folder(folder.id, force=force)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[red]Deleted folder:[/red] {path}")
