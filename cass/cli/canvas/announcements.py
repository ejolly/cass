"""``cass canvas announcements`` — list, create, update, delete."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import console, due, err_console

announcements_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Announcements — list, create, update, delete.",
)


@announcements_app.callback()
def announcements_callback(ctx: typer.Context) -> None:
    """Course announcements; bare ``announcements`` runs ``announcements list``."""
    if ctx.invoked_subcommand is None:
        announcements_list(csv_out="", save="", as_json=False)


@announcements_app.command(name="list")
def announcements_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """List course announcements."""
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        tz = c.time_zone
        anns = c.list_announcements()

    if as_json:
        _common.emit_json_lines(anns)
        return

    headers = ["ID", "Title", "Posted", "Author"]
    rows = [[str(a.id), a.title, due(a.posted_at, tz), a.user_name] for a in anns]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Announcements", headers, rows)
    else:
        report.render_list(headers, rows, title="Announcements")


@announcements_app.command(name="create")
def announcements_create(
    title: str = typer.Argument(..., help="Announcement title"),
    message: str = typer.Option(..., "--message", "-m", help="HTML message body"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Create an announcement."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        a = c.create_announcement(title, message)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Created announcement:[/green] {a.title} (id={a.id})")


@announcements_app.command(name="update")
def announcements_update(
    id_or_title: str = typer.Argument(..., help="Announcement ID or title"),
    title: str = typer.Option("", "--title", help="New title"),
    message: str = typer.Option("", "--message", "-m", help="New message body"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Update an announcement."""
    _common.require_canvas()
    kwargs: dict[str, str] = {}
    if title:
        kwargs["title"] = title
    if message:
        kwargs["message"] = message
    if not kwargs:
        err_console.print("[yellow]Nothing to update.[/yellow]")
        return
    with _common.client(dry_run=dry_run) as c:
        found = c.resolve_announcement(id_or_title)
        a = c.update_announcement(found.id, **kwargs)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Updated:[/green] {a.title}")


@announcements_app.command(name="delete")
def announcements_delete(
    id_or_title: str = typer.Argument(..., help="Announcement ID or title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Delete an announcement."""
    from ..prompts import confirm

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        a = c.resolve_announcement(id_or_title)
        confirm(f"Delete announcement '{a.title}'?", yes=yes, dry_run=dry_run)
        c.delete_announcement(a.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[red]Deleted announcement:[/red] {a.title}")
