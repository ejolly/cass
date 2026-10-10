"""Shared helpers for the ``cass canvas`` command modules.

Command modules call ``_common.client()`` and ``_common.require_canvas()``
through this module so tests can patch them in one place."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Iterable
from typing import TYPE_CHECKING

import click
import msgspec
import typer
from rich.console import Console

if TYPE_CHECKING:
    from ...apis.canvas.client import CanvasClient

canvas_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
    help="Canvas LMS — browse and modify course content.",
)

console = Console()
err_console = Console(stderr=True)


def require_canvas() -> None:
    from ...actions.config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        err_console.print("[red]This command requires Canvas configuration.[/red]")
        err_console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


def client(*, dry_run: bool = False) -> CanvasClient:
    from ...apis.canvas.client import CanvasClient

    return CanvasClient(dry_run=dry_run)


def dry_run_option() -> bool:
    """Shared ``--dry-run`` flag, used as a parameter default."""
    return typer.Option(
        False,
        "--dry-run",
        help="Show the Canvas requests this would send, without sending any writes",
    )


def json_option() -> bool:
    """Shared ``--json`` flag, used as a parameter default."""
    return typer.Option(
        False, "--json", help="Print JSON Lines: one Canvas object per line"
    )


def reject_json_with_files(as_json: bool, csv_out: str, save: str) -> None:
    """Exit 2 when ``--json`` is combined with a file output option."""
    if as_json and (csv_out or save):
        raise click.UsageError("--json cannot be combined with --csv or --save.")


def emit_json(obj: object) -> None:
    """Print one object as a single JSON line on stdout."""
    typer.echo(msgspec.json.encode(obj).decode())


def emit_json_lines(items: Iterable[object]) -> None:
    """Print each item as its own JSON line on stdout."""
    for item in items:
        emit_json(item)


def print_plan(c: CanvasClient, *, err: bool = False) -> None:
    """Print the writes a dry-run client recorded."""
    from ...apis.canvas.dry_run import format_plan

    out = err_console if err else console
    if not c.planned_requests:
        out.print(
            "Dry run: no Canvas writes needed.",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
        return
    out.print(
        "Dry run: no changes sent. Planned requests:",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    # soft_wrap keeps each planned write on one line, however long.
    for line in format_plan(c.planned_requests):
        out.print(f"  {line}", markup=False, highlight=False, soft_wrap=True)


def canvas_guide(heading: str, commands: list[tuple[str, str]]) -> None:
    """Print a section of the canvas command guide."""
    err_console.print(f"\n  [bold]{heading}[/bold]")
    for cmd, desc in commands:
        err_console.print(f"    [green]{cmd:<32s}[/green] [dim]{desc}[/dim]")


def group_id_for(c: CanvasClient, name: str, *, create: bool) -> int | None:
    """Resolve an assignment group by name, creating it when asked.

    Only a missing group is created; an ambiguous name raises ``RuntimeError``.
    """
    from ...apis.canvas.errors import CanvasNotFoundError

    if not name:
        return None
    try:
        return c.resolve_assignment_group(name).id
    except CanvasNotFoundError:  # an ambiguous name propagates to run()
        if not create:
            err_console.print(
                f"[red]Assignment group not found: {name}[/red] "
                "(pass --create-groups to create it)"
            )
            raise typer.Exit(code=1) from None
    group = c.create_assignment_group(name)
    if c.dry_run:
        # The plan already lists the POST; the returned id is a placeholder.
        err_console.print(f"Would create group: {name}", markup=False, highlight=False)
    else:
        console.print(f"[green]Created group:[/green] {group.name} (id={group.id})")
    return group.id


def pub(val: bool | None) -> str:
    if val is None:
        return ""
    return "[green]yes[/green]" if val else "[dim]no[/dim]"


def due(val: str | None, tz: str) -> str:
    """Format a Canvas timestamp as a date in the course time zone."""
    from ...apis.canvas.times import format_when

    return format_when(val, tz, date_only=True)


def when(val: str | None, tz: str) -> str:
    """Format a Canvas timestamp as date + HH:MM in the course time zone."""
    from ...apis.canvas.times import format_when

    return format_when(val, tz)


def size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_ / (1024 * 1024):.1f} MB"
