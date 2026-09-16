"""Shared helpers for the ``cass canvas`` command modules.

Command modules call ``_common.client()`` and ``_common.require_canvas()``
through this module so tests can patch them in one place."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

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


def require_canvas() -> None:
    from ...actions.config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        console.print("[red]This command requires Canvas configuration.[/red]")
        console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


def client() -> CanvasClient:
    from ...apis.canvas.client import CanvasClient

    return CanvasClient()


def canvas_guide(heading: str, commands: list[tuple[str, str]]) -> None:
    """Print a section of the canvas command guide."""
    console.print(f"\n  [bold]{heading}[/bold]")
    for cmd, desc in commands:
        console.print(f"    [green]{cmd:<32s}[/green] [dim]{desc}[/dim]")


def group_id_for(c: CanvasClient, name: str, *, create: bool) -> int | None:
    """Resolve an assignment group by name, creating it when asked."""
    if not name:
        return None
    try:
        return c.resolve_assignment_group(name).id
    except RuntimeError:
        if not create:
            console.print(
                f"[red]Assignment group not found: {name}[/red] "
                "(pass --create-groups to create it)"
            )
            raise typer.Exit(code=1) from None
    group = c.create_assignment_group(name)
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
