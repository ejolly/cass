"""``cass canvas assignments`` — assignments and assignment groups."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import console, due, pub, when

assignments_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Assignments — list, create, publish, delete.",
)


groups_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Assignment groups — list, create, delete.",
)
assignments_app.add_typer(groups_app, name="groups")


@assignments_app.callback()
def assignments_callback(
    ctx: typer.Context,
    assignment_id: str = typer.Option(
        "", "--id", help="Assignment ID or name for details"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List assignments, or show details for a specific assignment."""
    if ctx.invoked_subcommand is not None:
        return
    _common.require_canvas()

    from .. import report

    with _common.client() as c:
        tz = c.time_zone
        if assignment_id:
            a = c.resolve_assignment(assignment_id)
            headers = ["Field", "Value"]
            rows = [
                ["ID", str(a.id)],
                ["Name", a.name],
                ["Points", str(a.points_possible or 0.0)],
                ["Due", when(a.due_at, tz)],
                ["Published", pub(a.published)],
                ["Submission Types", ", ".join(a.submission_types)],
                ["Grading Type", a.grading_type],
                ["Group ID", str(a.assignment_group_id)],
                ["URL", a.html_url],
            ]
            title = f"Assignment: {a.name}"
        else:
            assignments = c.list_assignments()
            groups = {g.id: g.name for g in c.list_assignment_groups()}
            headers = ["ID", "Name", "Points", "Due", "Published", "Group"]
            rows = [
                [
                    str(a.id),
                    a.name,
                    str(a.points_possible or 0.0),
                    due(a.due_at, tz),
                    pub(a.published),
                    groups.get(a.assignment_group_id, ""),
                ]
                for a in assignments
            ]
            title = "Assignments"

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, title, headers, rows)
    else:
        report.render_list(headers, rows, title=title)


@groups_app.callback()
def groups_callback(
    ctx: typer.Context,
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show assignment groups with weights."""
    if ctx.invoked_subcommand is not None:
        return
    _common.require_canvas()

    from .. import report

    with _common.client() as c:
        groups = c.list_assignment_groups()

    headers = ["ID", "Name", "Position", "Weight"]
    rows = [
        [str(g.id), g.name, str(g.position), f"{g.group_weight}%"]
        for g in sorted(groups, key=lambda g: g.position)
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Assignment Groups", headers, rows)
    else:
        report.render_list(headers, rows, title="Assignment Groups")


@groups_app.command(name="create")
def groups_create(
    name: str = typer.Argument(..., help="Group name (e.g. 'Homeworks')"),
    weight: float | None = typer.Option(
        None, "--weight", help="Percent of final grade (weighted courses only)"
    ),
    position: int | None = typer.Option(None, "--position", help="Position in list"),
) -> None:
    """Create an assignment group."""
    _common.require_canvas()
    with _common.client() as c:
        g = c.create_assignment_group(name, position=position, group_weight=weight)
    console.print(f"[green]Created group:[/green] {g.name} (id={g.id})")


@groups_app.command(name="delete")
def groups_delete(
    id_or_name: str = typer.Argument(..., help="Group ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an assignment group and every assignment in it."""
    _common.require_canvas()
    with _common.client() as c:
        g = c.resolve_assignment_group(id_or_name)
        if not yes and not typer.confirm(
            f"Delete group '{g.name}' and all of its assignments?"
        ):
            raise typer.Abort()
        c.delete_assignment_group(g.id)
    console.print(f"[red]Deleted group:[/red] {g.name}")


@assignments_app.command(name="create")
def assignments_create(
    name: str = typer.Argument(..., help="Assignment name"),
    group: str = typer.Option(
        ..., "--group", help="Assignment group name (e.g. 'Homeworks', 'Labs')"
    ),
    points: float = typer.Option(0, "--points", help="Points possible"),
    due: str = typer.Option(
        "", "--due", help="Due (YYYY-MM-DD HH:MM in course time, or ISO 8601)"
    ),
    sub_type: str = typer.Option(
        "online_url",
        "--type",
        help="Submission type (online_url, online_upload, online_text_entry, etc.)",
    ),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately"),
    description: str | None = typer.Option(
        None, "--description", "-d", help="HTML description"
    ),
) -> None:
    """Create a new assignment."""
    from ...apis.canvas.times import parse_when

    _common.require_canvas()
    with _common.client() as c:
        group_id = c.resolve_assignment_group(group).id
        a = c.create_assignment(
            name,
            points_possible=points,
            due_at=parse_when(due, c.time_zone) or None,
            submission_types=[sub_type],
            published=publish,
            assignment_group_id=group_id,
            description=description,
        )
    console.print(f"[green]Created assignment:[/green] {a.name} (id={a.id})")


@assignments_app.command(name="publish")
def assignments_publish(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
) -> None:
    """Publish an assignment."""
    _common.require_canvas()
    with _common.client() as c:
        a = c.resolve_assignment(id_or_name)
        c.publish("assignments", a.id)
    console.print(f"[green]Published:[/green] {a.name}")


@assignments_app.command(name="unpublish")
def assignments_unpublish(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
) -> None:
    """Unpublish an assignment."""
    _common.require_canvas()
    with _common.client() as c:
        a = c.resolve_assignment(id_or_name)
        c.unpublish("assignments", a.id)
    console.print(f"[yellow]Unpublished:[/yellow] {a.name}")


@assignments_app.command(name="delete")
def assignments_delete(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an assignment."""
    _common.require_canvas()
    with _common.client() as c:
        a = c.resolve_assignment(id_or_name)
        if not yes and not typer.confirm(f"Delete assignment '{a.name}'?"):
            raise typer.Abort()
        c.delete_assignment(a.id)
    console.print(f"[red]Deleted:[/red] {a.name}")
