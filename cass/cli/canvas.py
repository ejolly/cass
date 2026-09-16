"""Typer CLI subcommands for ``cass canvas`` — Canvas LMS management."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient

canvas_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
    help="Canvas LMS — browse and modify course content.",
)

console = Console()

# Sub-apps for nested commands
modules_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course modules — list, create, publish, delete.",
)
canvas_app.add_typer(modules_app, name="modules", rich_help_panel="Browse")

assignments_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Assignments — list, create, publish, delete.",
)
canvas_app.add_typer(assignments_app, name="assignments", rich_help_panel="Browse")

quizzes_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Quizzes — list, create, publish, delete.",
)
canvas_app.add_typer(quizzes_app, name="quizzes", rich_help_panel="Browse")

calendar_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Course calendar — list, create, update, delete events.",
)
canvas_app.add_typer(calendar_app, name="calendar", rich_help_panel="Browse")


def require_canvas() -> None:
    from ..actions.config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        console.print("[red]This command requires Canvas configuration.[/red]")
        console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


def client() -> CanvasClient:
    from ..apis.canvas.client import CanvasClient

    return CanvasClient()


@canvas_app.command(rich_help_panel="Setup")
def login(
    from_brave: bool = typer.Option(
        False,
        "--from-brave",
        help="Import your Canvas session from Brave on macOS.",
    ),
    from_chrome: bool = typer.Option(
        False,
        "--from-chrome",
        help="Import your Canvas session from Google Chrome on macOS.",
    ),
    profile: str = typer.Option(
        "Default",
        "--profile",
        help="Browser profile directory, such as 'Profile 1'.",
    ),
) -> None:
    """Save a browser session and refresh it automatically after a 401 rejection."""
    from ..actions.config import get_config
    from ..apis.canvas.auth import Browser, CanvasAuthError
    from ..apis.canvas.browser import login_from_browser

    if from_brave == from_chrome:
        raise typer.BadParameter("Choose exactly one: --from-brave or --from-chrome.")
    browser = Browser.BRAVE if from_brave else Browser.CHROME
    require_canvas()
    cfg = get_config()
    console.print(
        f"Reading {browser.label}'s Canvas session. macOS may ask for Keychain access."
    )
    try:
        login_from_browser(cfg.root, cfg.canvas_base_url, profile, browser=browser)
    except (CanvasAuthError, OSError) as exc:
        console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=1) from None
    console.print(
        "Canvas session saved to .canvascreds. "
        "If Canvas rejects authentication, cass will refresh the cookies from "
        f"{browser.label} and retry the request once."
    )


# ---------------------------------------------------------------------------
# cass canvas — course overview (default)
# ---------------------------------------------------------------------------


@canvas_app.callback()
def canvas_callback(ctx: typer.Context) -> None:
    """Canvas LMS — browse and modify course content."""
    if ctx.invoked_subcommand is not None:
        return
    require_canvas()

    from rich.panel import Panel

    from ..apis.canvas.client import CanvasClient

    with CanvasClient() as c:
        course = c.get_course()
        modules = c.list_modules()
        assignments = c.list_assignments()
        quizzes = c.list_quizzes()
        anns = c.list_announcements()

    lines: list[str] = []
    lines.append(f"  [dim]State[/dim]          {course.workflow_state}")
    if course.total_students is not None:
        lines.append(f"  [dim]Students[/dim]       {course.total_students}")
    lines.append(f"  [dim]Modules[/dim]        {len(modules)}")
    lines.append(f"  [dim]Assignments[/dim]    {len(assignments)}")
    lines.append(f"  [dim]Quizzes[/dim]        {len(quizzes)}")
    lines.append(f"  [dim]Announcements[/dim]  {len(anns)}")

    title = f"[bold]{course.name}[/bold]"
    if course.course_code:
        title += f"  [dim]{course.course_code}[/dim]"

    panel = Panel(
        "\n".join(lines),
        title=title,
        title_align="left",
        border_style="blue",
        padding=(1, 1),
    )
    console.print()
    console.print(panel)

    canvas_guide(
        "Browse content",
        [
            ("cass canvas people", "Student roster"),
            ("cass canvas modules", "Course modules"),
            ("cass canvas assignments", "Assignments"),
            ("cass canvas files", "File tree"),
        ],
    )
    canvas_guide(
        "More",
        [("cass canvas --help", "All canvas commands")],
    )
    console.print()


def canvas_guide(heading: str, commands: list[tuple[str, str]]) -> None:
    """Print a section of the canvas command guide."""
    console.print(f"\n  [bold]{heading}[/bold]")
    for cmd, desc in commands:
        console.print(f"    [green]{cmd:<32s}[/green] [dim]{desc}[/dim]")


# ---------------------------------------------------------------------------
# cass canvas people
# ---------------------------------------------------------------------------


@canvas_app.command(rich_help_panel="Browse")
def people(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show course roster with roles and emails."""
    from . import report

    require_canvas()
    with client() as c:
        users = c.list_users()

    headers = ["Name", "Role", "Email", "SIS ID", "Canvas ID"]
    rows: list[list[str]] = []
    for u in sorted(users, key=lambda u: u.sortable_name or u.name):
        role = ""
        if u.enrollments:
            role = u.enrollments[0].role
        rows.append(
            [
                u.name,
                role,
                u.email,
                u.sis_user_id or "",
                str(u.id),
            ]
        )

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "People", headers, rows)
    else:
        report.render_list(headers, rows, title="People")


# ---------------------------------------------------------------------------
# cass canvas modules [ID]
# ---------------------------------------------------------------------------


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
    require_canvas()

    from . import report

    with client() as c:
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
    require_canvas()
    with client() as c:
        mod = c.create_module(name, position=position)
    console.print(f"[green]Created module:[/green] {mod.name} (id={mod.id})")


@modules_app.command(name="publish")
def modules_publish(
    id_or_name: str | None = typer.Argument(None, help="Module ID or name"),
    all_modules: bool = typer.Option(False, "--all", help="Publish all modules"),
) -> None:
    """Publish a module (or all modules with --all)."""
    require_canvas()
    if not all_modules and not id_or_name:
        console.print("[red]Give a module ID or name, or --all.[/red]")
        raise typer.Exit(code=1)
    with client() as c:
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
    require_canvas()
    with client() as c:
        mod = c.resolve_module(id_or_name)
        c.unpublish("modules", mod.id)
    console.print(f"[yellow]Unpublished:[/yellow] {mod.name}")


@modules_app.command(name="delete")
def modules_delete(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a module."""
    require_canvas()
    with client() as c:
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
    require_canvas()
    with client() as c:
        mod = c.resolve_module(id_or_name)
        item = c.create_module_item(
            mod.id, item_type=item_type, content_id=content_id, title=title
        )
    console.print(f"[green]Added:[/green] {item.title} to {mod.name}")


# ---------------------------------------------------------------------------
# cass canvas assignments [ID]
# ---------------------------------------------------------------------------


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
    require_canvas()

    from . import report

    with client() as c:
        if assignment_id:
            a = c.resolve_assignment(assignment_id)
            headers = ["Field", "Value"]
            rows = [
                ["ID", str(a.id)],
                ["Name", a.name],
                ["Points", str(a.points_possible or 0.0)],
                ["Due", a.due_at or ""],
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
                    due(a.due_at),
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


@assignments_app.command(name="groups")
def assignment_groups(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show assignment groups with weights."""
    from . import report

    require_canvas()
    with client() as c:
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


@assignments_app.command(name="create")
def assignments_create(
    name: str = typer.Argument(..., help="Assignment name"),
    group: str = typer.Option(
        ..., "--group", help="Assignment group name (e.g. 'Homeworks', 'Labs')"
    ),
    points: float = typer.Option(0, "--points", help="Points possible"),
    due: str = typer.Option("", "--due", help="Due date (ISO 8601)"),
    sub_type: str = typer.Option(
        "online_url",
        "--type",
        help="Submission type (online_url, online_upload, online_text_entry, etc.)",
    ),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately"),
) -> None:
    """Create a new assignment."""
    require_canvas()
    with client() as c:
        group_id = resolve_assignment_group(c, group)
        a = c.create_assignment(
            name,
            points_possible=points,
            due_at=due or None,
            submission_types=[sub_type],
            published=publish,
            assignment_group_id=group_id,
        )
    console.print(f"[green]Created assignment:[/green] {a.name} (id={a.id})")


@assignments_app.command(name="publish")
def assignments_publish(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
) -> None:
    """Publish an assignment."""
    require_canvas()
    with client() as c:
        a = c.resolve_assignment(id_or_name)
        c.publish("assignments", a.id)
    console.print(f"[green]Published:[/green] {a.name}")


@assignments_app.command(name="unpublish")
def assignments_unpublish(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
) -> None:
    """Unpublish an assignment."""
    require_canvas()
    with client() as c:
        a = c.resolve_assignment(id_or_name)
        c.unpublish("assignments", a.id)
    console.print(f"[yellow]Unpublished:[/yellow] {a.name}")


@assignments_app.command(name="delete")
def assignments_delete(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an assignment."""
    require_canvas()
    with client() as c:
        a = c.resolve_assignment(id_or_name)
        if not yes and not typer.confirm(f"Delete assignment '{a.name}'?"):
            raise typer.Abort()
        c.delete_assignment(a.id)
    console.print(f"[red]Deleted:[/red] {a.name}")


# ---------------------------------------------------------------------------
# cass canvas quizzes
# ---------------------------------------------------------------------------


@quizzes_app.callback()
def quizzes_callback(
    ctx: typer.Context,
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List all quizzes."""
    if ctx.invoked_subcommand is not None:
        return
    require_canvas()

    from . import report

    with client() as c:
        quizzes = c.list_quizzes()

    headers = ["ID", "Title", "Type", "Questions", "Points", "Published"]
    rows = [
        [
            str(q.id),
            q.title,
            q.quiz_type,
            str(q.question_count),
            str(q.points_possible or ""),
            pub(q.published),
        ]
        for q in quizzes
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Quizzes", headers, rows)
    else:
        report.render_list(headers, rows, title="Quizzes")


@quizzes_app.command(name="create")
def quizzes_create(
    title: str = typer.Argument(..., help="Quiz title"),
    quiz_type: str = typer.Option(
        "assignment",
        "--type",
        help="Quiz type (practice_quiz, assignment, graded_survey, survey)",
    ),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately"),
    time_limit: int | None = typer.Option(
        None, "--time-limit", help="Time limit in minutes"
    ),
) -> None:
    """Create a new quiz (points come from its questions)."""
    require_canvas()
    with client() as c:
        q = c.create_quiz(
            title,
            quiz_type=quiz_type,
            published=publish,
            time_limit=time_limit,
        )
    console.print(f"[green]Created quiz:[/green] {q.title} (id={q.id})")


@quizzes_app.command(name="publish")
def quizzes_publish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
) -> None:
    """Publish a quiz."""
    require_canvas()
    with client() as c:
        q = c.resolve_quiz(id_or_name)
        c.publish("quizzes", q.id)
    console.print(f"[green]Published:[/green] {q.title}")


@quizzes_app.command(name="unpublish")
def quizzes_unpublish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
) -> None:
    """Unpublish a quiz."""
    require_canvas()
    with client() as c:
        q = c.resolve_quiz(id_or_name)
        c.unpublish("quizzes", q.id)
    console.print(f"[yellow]Unpublished:[/yellow] {q.title}")


@quizzes_app.command(name="delete")
def quizzes_delete(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a quiz."""
    require_canvas()
    with client() as c:
        q = c.resolve_quiz(id_or_name)
        if not yes and not typer.confirm(f"Delete quiz '{q.title}'?"):
            raise typer.Abort()
        c.delete_quiz(q.id)
    console.print(f"[red]Deleted:[/red] {q.title}")


# ---------------------------------------------------------------------------
# cass canvas calendar
# ---------------------------------------------------------------------------


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
    require_canvas()

    from . import report

    with client() as c:
        events = c.list_calendar_events(
            start_date=start_date or None, end_date=end_date or None
        )

    headers = ["ID", "Start", "End", "Title", "Location"]
    rows: list[list[str]] = []
    for e in sorted(events, key=lambda e: e.start_at or ""):
        if e.all_day:
            start = end = e.all_day_date or ""
        else:
            start, end = when(e.start_at), when(e.end_at)
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
    start_at: str = typer.Option(..., "--start", help="Start (ISO 8601)"),
    end_at: str | None = typer.Option(None, "--end", help="End (ISO 8601)"),
    location: str | None = typer.Option(None, "--location", help="Location name"),
    description: str | None = typer.Option(
        None, "--description", "-d", help="HTML description"
    ),
    all_day: bool = typer.Option(
        False, "--all-day", help="All-day event (times ignored)"
    ),
) -> None:
    """Create a calendar event."""
    require_canvas()
    with client() as c:
        e = c.create_calendar_event(
            title,
            start_at=start_at,
            end_at=end_at,
            description=description,
            location_name=location,
            all_day=all_day,
        )
    console.print(f"[green]Created event:[/green] {e.title} (id={e.id})")


@calendar_app.command(name="update")
def calendar_update(
    event_id: int = typer.Argument(..., help="Calendar event ID"),
    title: str | None = typer.Option(None, "--title", help="New title"),
    start_at: str | None = typer.Option(None, "--start", help="New start (ISO 8601)"),
    end_at: str | None = typer.Option(None, "--end", help="New end (ISO 8601)"),
    location: str | None = typer.Option(None, "--location", help="New location"),
    description: str | None = typer.Option(
        None, "--description", "-d", help="New HTML description"
    ),
    all_day: bool | None = typer.Option(
        None, "--all-day/--timed", help="Make all-day or timed"
    ),
) -> None:
    """Update a calendar event (only the given fields change)."""
    require_canvas()
    kwargs: dict[str, object] = {}
    if title is not None:
        kwargs["title"] = title
    if start_at is not None:
        kwargs["start_at"] = start_at
    if end_at is not None:
        kwargs["end_at"] = end_at
    if location is not None:
        kwargs["location_name"] = location
    if description is not None:
        kwargs["description"] = description
    if all_day is not None:
        kwargs["all_day"] = all_day
    if not kwargs:
        console.print("[yellow]Nothing to update.[/yellow]")
        return
    with client() as c:
        e = c.update_calendar_event(event_id, **kwargs)
    console.print(f"[green]Updated:[/green] {e.title}")


@calendar_app.command(name="delete")
def calendar_delete(
    event_id: int = typer.Argument(..., help="Calendar event ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a calendar event."""
    require_canvas()
    if not yes and not typer.confirm(f"Delete calendar event {event_id}?"):
        raise typer.Abort()
    with client() as c:
        c.delete_calendar_event(event_id)
    console.print(f"[red]Deleted calendar event {event_id}[/red]")


# ---------------------------------------------------------------------------
# cass canvas files
# ---------------------------------------------------------------------------


@canvas_app.command(rich_help_panel="Browse")
def files(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show course files as a tree."""
    from rich.tree import Tree

    from . import report

    require_canvas()
    with client() as c:
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
                due(f.created_at),
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

    require_canvas()
    if not os.path.isfile(path):
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(code=1)

    with client() as c:
        f = c.upload_file(path, folder=folder)
    console.print(f"[green]Uploaded:[/green] {f.display_name} (id={f.id})")


@canvas_app.command(name="delete-file", rich_help_panel="Manage")
def files_delete(
    file_id: int = typer.Argument(..., help="Canvas file ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a file from the course."""
    require_canvas()
    if not yes and not typer.confirm(f"Delete file {file_id}?"):
        raise typer.Abort()
    with client() as c:
        c.delete_file(file_id)
    console.print(f"[red]Deleted file {file_id}[/red]")


# ---------------------------------------------------------------------------
# cass canvas announcements
# ---------------------------------------------------------------------------


@canvas_app.command(rich_help_panel="Browse")
def announcements(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List course announcements."""
    from . import report

    require_canvas()
    with client() as c:
        anns = c.list_announcements()

    headers = ["ID", "Title", "Posted", "Author"]
    rows = [[str(a.id), a.title, due(a.posted_at), a.user_name] for a in anns]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Announcements", headers, rows)
    else:
        report.render_list(headers, rows, title="Announcements")


@canvas_app.command(name="announce", rich_help_panel="Manage")
def announcements_create(
    title: str = typer.Argument(..., help="Announcement title"),
    message: str = typer.Option(..., "--message", "-m", help="HTML message body"),
) -> None:
    """Create an announcement."""
    require_canvas()
    with client() as c:
        a = c.create_announcement(title, message)
    console.print(f"[green]Created announcement:[/green] {a.title} (id={a.id})")


@canvas_app.command(name="update-announcement", rich_help_panel="Manage")
def announcements_update(
    topic_id: int = typer.Argument(..., help="Announcement (discussion topic) ID"),
    title: str = typer.Option("", "--title", help="New title"),
    message: str = typer.Option("", "--message", "-m", help="New message body"),
) -> None:
    """Update an announcement."""
    require_canvas()
    kwargs: dict[str, str] = {}
    if title:
        kwargs["title"] = title
    if message:
        kwargs["message"] = message
    if not kwargs:
        console.print("[yellow]Nothing to update.[/yellow]")
        return
    with client() as c:
        a = c.update_announcement(topic_id, **kwargs)
    console.print(f"[green]Updated:[/green] {a.title}")


@canvas_app.command(name="delete-announcement", rich_help_panel="Manage")
def announcements_delete(
    topic_id: int = typer.Argument(..., help="Announcement (discussion topic) ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an announcement."""
    require_canvas()
    if not yes and not typer.confirm(f"Delete announcement {topic_id}?"):
        raise typer.Abort()
    with client() as c:
        c.delete_announcement(topic_id)
    console.print(f"[red]Deleted announcement {topic_id}[/red]")


# ---------------------------------------------------------------------------
# cass canvas tabs
# ---------------------------------------------------------------------------


@canvas_app.command(rich_help_panel="Browse")
def tabs(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List course navigation tabs."""
    from . import report

    require_canvas()
    with client() as c:
        tab_list = c.list_tabs()

    headers = ["Label", "Type", "Position", "Visibility", "ID"]
    rows = [
        [
            t.label,
            t.type,
            str(t.position or ""),
            "hidden" if t.hidden else "visible",
            t.id,
        ]
        for t in sorted(tab_list, key=lambda t: t.position or 999)
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Tabs", headers, rows)
    else:
        report.render_list(headers, rows, title="Tabs")


@canvas_app.command(name="show-tab", rich_help_panel="Manage")
def tabs_show(
    id_or_label: str = typer.Argument(..., help="Tab ID or label"),
) -> None:
    """Make a navigation tab visible."""
    require_canvas()
    with client() as c:
        tab = c.resolve_tab(id_or_label)
        t = c.update_tab(tab.id, hidden=False)
    console.print(f"[green]Visible:[/green] {t.label}")


@canvas_app.command(name="hide-tab", rich_help_panel="Manage")
def tabs_hide(
    id_or_label: str = typer.Argument(..., help="Tab ID or label"),
) -> None:
    """Hide a navigation tab."""
    require_canvas()
    with client() as c:
        tab = c.resolve_tab(id_or_label)
        t = c.update_tab(tab.id, hidden=True)
    console.print(f"[yellow]Hidden:[/yellow] {t.label}")


# ---------------------------------------------------------------------------
# cass canvas sync — reconcile TOML desired state → Canvas actual state
# ---------------------------------------------------------------------------


@canvas_app.command(rich_help_panel="Manage")
def sync(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="Show what would change (default) or apply changes",
    ),
) -> None:
    """Sync cass.toml declarations to Canvas (modules and assignments).

    Compares [[canvas.modules]] and [[canvas.assignments]] in cass.toml
    against the live Canvas course. Shows a diff of create/update/skip
    actions. Use --apply to execute changes.
    """
    from rich.table import Table

    from ..actions.config import get_config

    require_canvas()
    cfg = get_config()

    if not cfg.canvas_modules and not cfg.canvas_assignments:
        console.print(
            "[yellow]No [[canvas.modules]] or "
            "[[canvas.assignments]] in cass.toml.[/yellow]"
        )
        return

    with client() as c:
        actions: list[tuple[str, str, str]] = []  # (action, type, name)

        # --- Modules ---
        if cfg.canvas_modules:
            live_modules = c.list_modules()
            live_by_name = {m.name.lower(): m for m in live_modules}

            for spec in cfg.canvas_modules:
                key = spec.name.lower()
                if key in live_by_name:
                    live = live_by_name[key]
                    if live.published != spec.published:
                        actions.append(
                            (
                                "update",
                                "module",
                                f"{spec.name} (published: {spec.published})",
                            )
                        )
                        if not dry_run:
                            if spec.published:
                                c.publish("modules", live.id)
                            else:
                                c.unpublish("modules", live.id)
                    else:
                        actions.append(("skip", "module", spec.name))
                else:
                    actions.append(("create", "module", spec.name))
                    if not dry_run:
                        mod = c.create_module(spec.name)
                        if spec.published:
                            c.publish("modules", mod.id)

        # --- Assignments ---
        if cfg.canvas_assignments:
            from ..apis.canvas.sync import push_assignments, same_instant

            live_assignments = c.list_assignments()
            live_by_name = {a.name.lower(): a for a in live_assignments}

            # Resolve assignment group names to IDs
            group_map: dict[str, int] = {}
            if any(s.group for s in cfg.canvas_assignments):
                groups = c.list_assignment_groups()
                group_map = {g.name.lower(): g.id for g in groups}

            updates_by_id: dict[int, dict[str, object]] = {}
            for spec in cfg.canvas_assignments:
                key = spec.name.lower()
                if key in live_by_name:
                    live = live_by_name[key]
                    changes: dict[str, object] = {}
                    if spec.points and (live.points_possible or 0.0) != spec.points:
                        changes["points_possible"] = spec.points
                    if spec.due_at and not same_instant(live.due_at, spec.due_at):
                        changes["due_at"] = spec.due_at
                    if live.published != spec.published:
                        changes["published"] = spec.published

                    if changes:
                        detail = ", ".join(f"{k}: {v}" for k, v in changes.items())
                        actions.append(
                            ("update", "assignment", f"{spec.name} ({detail})")
                        )
                        updates_by_id[live.id] = changes
                    else:
                        actions.append(("skip", "assignment", spec.name))
                else:
                    actions.append(("create", "assignment", spec.name))
                    if not dry_run:
                        group_id = (
                            group_map.get(spec.group.lower()) if spec.group else None
                        )
                        c.create_assignment(
                            spec.name,
                            points_possible=spec.points,
                            due_at=spec.due_at or None,
                            submission_types=spec.submission_types,
                            published=spec.published,
                            assignment_group_id=group_id,
                        )

            if not dry_run and updates_by_id:
                push_assignments(c, updates_by_id)

    # --- Display results ---
    table = Table(
        title="Canvas Sync" + (" (dry run)" if dry_run else ""),
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Action")
    table.add_column("Type")
    table.add_column("Name")

    for action, rtype, name in actions:
        color = {"create": "green", "update": "yellow", "skip": "dim"}.get(action, "")
        table.add_row(f"[{color}]{action}[/{color}]", rtype, name)

    console.print()
    console.print(table)
    console.print()

    creates = sum(1 for a, _, _ in actions if a == "create")
    updates = sum(1 for a, _, _ in actions if a == "update")
    skips = sum(1 for a, _, _ in actions if a == "skip")
    console.print(f"  {creates} create, {updates} update, {skips} skip")

    if dry_run and (creates or updates):
        console.print(
            "\n  [yellow]Dry run — no changes made. Use --apply to sync.[/yellow]"
        )
    elif not dry_run:
        console.print("\n  [green]Sync complete.[/green]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_assignment_group(c: CanvasClient, group_name: str) -> int:
    """Resolve an assignment group name to its Canvas ID (case-insensitive)."""
    groups = c.list_assignment_groups()
    key = group_name.lower()
    for g in groups:
        if g.name.lower() == key:
            return g.id
    names = ", ".join(g.name for g in sorted(groups, key=lambda g: g.position))
    console.print(f"[red]Unknown assignment group:[/red] {group_name}")
    console.print(f"[dim]Available groups: {names}[/dim]")
    raise typer.Exit(code=1)


def pub(val: bool | None) -> str:
    if val is None:
        return ""
    return "[green]yes[/green]" if val else "[dim]no[/dim]"


def due(val: str | None) -> str:
    """Format a Canvas timestamp (UTC) as a local date."""
    from datetime import datetime

    if not val:
        return ""
    return datetime.fromisoformat(val).astimezone().strftime("%Y-%m-%d")


def when(val: str | None) -> str:
    """Format a Canvas timestamp (UTC) as local date + HH:MM."""
    from datetime import datetime

    if not val:
        return ""
    return datetime.fromisoformat(val).astimezone().strftime("%Y-%m-%d %H:%M")


def size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_ / (1024 * 1024):.1f} MB"
