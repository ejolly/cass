"""``cass canvas calendar`` — list, create, update, delete events."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import console, when

calendar_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course calendar — list, create, update, delete events.",
)


@calendar_app.callback()
def calendar_callback(
    ctx: typer.Context,
    start_date: str = typer.Option(
        "", "--from", help="Only events on or after this date (YYYY-MM-DD)"
    ),
    end_date: str = typer.Option(
        "", "--to", help="Only events on or before this date (YYYY-MM-DD)"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List course calendar events (all events unless a date range is given)."""
    if ctx.invoked_subcommand is not None:
        return
    _common.require_canvas()

    from .. import report

    with _common.client() as c:
        tz = c.time_zone
        events = c.list_calendar_events(
            start_date=start_date or None, end_date=end_date or None
        )

    headers = ["ID", "Start", "End", "Title", "Location"]
    rows: list[list[str]] = []
    for e in sorted(events, key=lambda e: e.start_at or ""):
        if e.all_day:
            start = end = e.all_day_date or ""
        else:
            start, end = when(e.start_at, tz), when(e.end_at, tz)
        rows.append([str(e.id), start, end, e.title, e.location_name or ""])

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Calendar", headers, rows)
    else:
        report.render_list(headers, rows, title="Calendar")


@calendar_app.command(name="create")
def calendar_create(
    title: str = typer.Argument(..., help="Event title"),
    start_at: str = typer.Option(
        ..., "--start", help="Start (YYYY-MM-DD HH:MM in course time, or ISO 8601)"
    ),
    end_at: str | None = typer.Option(
        None, "--end", help="End (YYYY-MM-DD HH:MM in course time, or ISO 8601)"
    ),
    location: str | None = typer.Option(None, "--location", help="Location name"),
    description: str | None = typer.Option(
        None, "--description", "-d", help="HTML description"
    ),
    all_day: bool = typer.Option(
        False, "--all-day", help="All-day event (times ignored)"
    ),
) -> None:
    """Create a calendar event."""
    from ...apis.canvas.times import parse_when

    _common.require_canvas()
    with _common.client() as c:
        e = c.create_calendar_event(
            title,
            start_at=parse_when(start_at, c.time_zone),
            end_at=parse_when(end_at, c.time_zone) if end_at else None,
            description=description,
            location_name=location,
            all_day=all_day,
        )
    console.print(f"[green]Created event:[/green] {e.title} (id={e.id})")


@calendar_app.command(name="update")
def calendar_update(
    event_id: int = typer.Argument(..., help="Calendar event ID"),
    title: str | None = typer.Option(None, "--title", help="New title"),
    start_at: str | None = typer.Option(
        None, "--start", help="New start (course time or ISO 8601)"
    ),
    end_at: str | None = typer.Option(
        None, "--end", help="New end (course time or ISO 8601)"
    ),
    location: str | None = typer.Option(None, "--location", help="New location"),
    description: str | None = typer.Option(
        None, "--description", "-d", help="New HTML description"
    ),
    all_day: bool | None = typer.Option(
        None, "--all-day/--timed", help="Make all-day or timed"
    ),
) -> None:
    """Update a calendar event (only the given fields change)."""
    from ...apis.canvas.times import parse_when

    _common.require_canvas()
    kwargs: dict[str, object] = {}
    if title is not None:
        kwargs["title"] = title
    if location is not None:
        kwargs["location_name"] = location
    if description is not None:
        kwargs["description"] = description
    if all_day is not None:
        kwargs["all_day"] = all_day
    if not kwargs and start_at is None and end_at is None:
        console.print("[yellow]Nothing to update.[/yellow]")
        return
    with _common.client() as c:
        if start_at is not None:
            kwargs["start_at"] = parse_when(start_at, c.time_zone)
        if end_at is not None:
            kwargs["end_at"] = parse_when(end_at, c.time_zone)
        e = c.update_calendar_event(event_id, **kwargs)
    console.print(f"[green]Updated:[/green] {e.title}")


@calendar_app.command(name="delete")
def calendar_delete(
    event_id: int = typer.Argument(..., help="Calendar event ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a calendar event."""
    _common.require_canvas()
    if not yes and not typer.confirm(f"Delete calendar event {event_id}?"):
        raise typer.Abort()
    with _common.client() as c:
        c.delete_calendar_event(event_id)
    console.print(f"[red]Deleted calendar event {event_id}[/red]")
