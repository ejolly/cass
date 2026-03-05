"""Typer CLI subcommands for ``cass canvas`` — Canvas LMS management."""

from __future__ import annotations

__docformat__ = "google"

import typer
from rich.console import Console

canvas_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Canvas LMS management: browse and modify course content.",
)

console = Console()

# Sub-apps for nested commands
modules_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="List, create, publish, and manage course modules.",
)
canvas_app.add_typer(modules_app, name="modules")

assignments_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="List, create, publish, and manage course assignments.",
)
canvas_app.add_typer(assignments_app, name="assignments")

quizzes_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="List, create, publish, and manage course quizzes.",
)
canvas_app.add_typer(quizzes_app, name="quizzes")


def _require_canvas() -> None:
    from .config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        console.print("[red]This command requires Canvas configuration.[/red]")
        console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


def _client():  # noqa: ANN202
    from .canvas_api import CanvasClient

    return CanvasClient()


# ---------------------------------------------------------------------------
# cass canvas — course overview (default)
# ---------------------------------------------------------------------------


@canvas_app.callback()
def canvas_callback(ctx: typer.Context) -> None:
    """Canvas LMS — browse and modify course content."""
    if ctx.invoked_subcommand is not None:
        return
    _require_canvas()

    from .canvas_api import CanvasClient

    with CanvasClient() as c:
        course = c.get_course()
        modules = c.list_modules()
        assignments = c.list_assignments()
        quizzes = c.list_quizzes()
        announcements = c.list_announcements()

    console.print(f"\n[bold]{course.name}[/bold]  ({course.course_code})")
    console.print(f"  State: {course.workflow_state}")
    if course.total_students is not None:
        console.print(f"  Students: {course.total_students}")
    console.print(f"  Modules: {len(modules)}")
    console.print(f"  Assignments: {len(assignments)}")
    console.print(f"  Quizzes: {len(quizzes)}")
    console.print(f"  Announcements: {len(announcements)}")
    console.print()


# ---------------------------------------------------------------------------
# cass canvas people
# ---------------------------------------------------------------------------


@canvas_app.command()
def people(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show course roster with roles and emails."""
    from . import report

    _require_canvas()
    with _client() as c:
        users = c.list_users()

    headers = ["Name", "Role", "Email", "SIS ID", "Canvas ID"]
    rows = []
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
    module_id: str = typer.Argument("", help="Module ID or name to show items"),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List modules, or show items in a specific module."""
    if ctx.invoked_subcommand is not None:
        return
    _require_canvas()

    from . import report

    with _client() as c:
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
                    _pub(it.published),
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
                    _pub(m.published),
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
    _require_canvas()
    with _client() as c:
        mod = c.create_module(name, position=position)
    console.print(f"[green]Created module:[/green] {mod.name} (id={mod.id})")


@modules_app.command(name="publish")
def modules_publish(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    all_modules: bool = typer.Option(False, "--all", help="Publish all modules"),
) -> None:
    """Publish a module (or all modules with --all)."""
    _require_canvas()
    with _client() as c:
        if all_modules:
            modules = c.list_modules()
            for m in modules:
                c.publish("modules", m.id)
                console.print(f"  [green]Published:[/green] {m.name}")
        else:
            mod = c.resolve_module(id_or_name)
            c.publish("modules", mod.id)
            console.print(f"[green]Published:[/green] {mod.name}")


@modules_app.command(name="unpublish")
def modules_unpublish(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
) -> None:
    """Unpublish a module."""
    _require_canvas()
    with _client() as c:
        mod = c.resolve_module(id_or_name)
        c.unpublish("modules", mod.id)
    console.print(f"[yellow]Unpublished:[/yellow] {mod.name}")


@modules_app.command(name="delete")
def modules_delete(
    id_or_name: str = typer.Argument(..., help="Module ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a module."""
    _require_canvas()
    with _client() as c:
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
    title: str = typer.Option(
        "", "--title", help="Item title (defaults to content name)"
    ),
) -> None:
    """Add an item to a module."""
    _require_canvas()
    with _client() as c:
        mod = c.resolve_module(id_or_name)
        item = c.create_module_item(
            mod.id, title=title or item_type, item_type=item_type, content_id=content_id
        )
    console.print(f"[green]Added:[/green] {item.title} to {mod.name}")


# ---------------------------------------------------------------------------
# cass canvas assignments [ID]
# ---------------------------------------------------------------------------


@assignments_app.callback()
def assignments_callback(
    ctx: typer.Context,
    assignment_id: str = typer.Argument("", help="Assignment ID or name for details"),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List assignments, or show details for a specific assignment."""
    if ctx.invoked_subcommand is not None:
        return
    _require_canvas()

    from . import report

    with _client() as c:
        if assignment_id:
            a = c.resolve_assignment(assignment_id)
            headers = ["Field", "Value"]
            rows = [
                ["ID", str(a.id)],
                ["Name", a.name],
                ["Points", str(a.points_possible)],
                ["Due", a.due_at or ""],
                ["Published", _pub(a.published)],
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
                    str(a.points_possible),
                    _due(a.due_at),
                    _pub(a.published),
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

    _require_canvas()
    with _client() as c:
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
    points: float = typer.Option(0, "--points", help="Points possible"),
    due: str = typer.Option("", "--due", help="Due date (ISO 8601)"),
    sub_type: str = typer.Option(
        "online_url",
        "--type",
        help="Submission type (online_url, online_upload, online_text_entry, etc.)",
    ),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately"),
    group_id: int | None = typer.Option(None, "--group-id", help="Assignment group ID"),
) -> None:
    """Create a new assignment."""
    _require_canvas()
    with _client() as c:
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
    _require_canvas()
    with _client() as c:
        a = c.resolve_assignment(id_or_name)
        c.publish("assignments", a.id)
    console.print(f"[green]Published:[/green] {a.name}")


@assignments_app.command(name="unpublish")
def assignments_unpublish(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
) -> None:
    """Unpublish an assignment."""
    _require_canvas()
    with _client() as c:
        a = c.resolve_assignment(id_or_name)
        c.unpublish("assignments", a.id)
    console.print(f"[yellow]Unpublished:[/yellow] {a.name}")


@assignments_app.command(name="delete")
def assignments_delete(
    id_or_name: str = typer.Argument(..., help="Assignment ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an assignment."""
    _require_canvas()
    with _client() as c:
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
    _require_canvas()

    from . import report

    with _client() as c:
        quizzes = c.list_quizzes()

    headers = ["ID", "Title", "Type", "Questions", "Points", "Published"]
    rows = [
        [
            str(q.id),
            q.title,
            q.quiz_type,
            str(q.question_count),
            str(q.points_possible or ""),
            _pub(q.published),
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
    points: float | None = typer.Option(None, "--points", help="Points possible"),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately"),
    time_limit: int | None = typer.Option(
        None, "--time-limit", help="Time limit in minutes"
    ),
) -> None:
    """Create a new quiz."""
    _require_canvas()
    with _client() as c:
        q = c.create_quiz(
            title,
            quiz_type=quiz_type,
            points_possible=points,
            published=publish,
            time_limit=time_limit,
        )
    console.print(f"[green]Created quiz:[/green] {q.title} (id={q.id})")


@quizzes_app.command(name="publish")
def quizzes_publish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
) -> None:
    """Publish a quiz."""
    _require_canvas()
    with _client() as c:
        q = c.resolve_quiz(id_or_name)
        c.publish("quizzes", q.id)
    console.print(f"[green]Published:[/green] {q.title}")


@quizzes_app.command(name="unpublish")
def quizzes_unpublish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
) -> None:
    """Unpublish a quiz."""
    _require_canvas()
    with _client() as c:
        q = c.resolve_quiz(id_or_name)
        c.unpublish("quizzes", q.id)
    console.print(f"[yellow]Unpublished:[/yellow] {q.title}")


@quizzes_app.command(name="delete")
def quizzes_delete(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a quiz."""
    _require_canvas()
    with _client() as c:
        q = c.resolve_quiz(id_or_name)
        if not yes and not typer.confirm(f"Delete quiz '{q.title}'?"):
            raise typer.Abort()
        c.delete_quiz(q.id)
    console.print(f"[red]Deleted:[/red] {q.title}")


# ---------------------------------------------------------------------------
# cass canvas files
# ---------------------------------------------------------------------------


@canvas_app.command()
def files(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """Show course files as a tree."""
    from . import report
    from rich.tree import Tree

    _require_canvas()
    with _client() as c:
        folders = c.list_folders()
        all_files = c.list_files()

    if csv_out or save:
        headers = ["ID", "Name", "Size", "Type", "Folder", "Created"]
        folder_names = {f.id: f.full_name for f in folders}
        rows = [
            [
                str(f.id),
                f.display_name,
                _size(f.size),
                f.content_type,
                folder_names.get(f.folder_id, ""),
                f.created_at[:10] if f.created_at else "",
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
        label = f"{f.display_name}  [dim]{_size(f.size)}[/dim]"
        parent = folder_nodes.get(f.folder_id)
        if parent:
            parent.add(label)
        else:
            tree.add(label)

    console.print()
    console.print(tree)
    console.print()


@canvas_app.command(name="upload")
def files_upload(
    path: str = typer.Argument(..., help="Local file path to upload"),
    folder: str = typer.Option("", "--folder", help="Destination folder in Canvas"),
) -> None:
    """Upload a file to the course."""
    import os

    _require_canvas()
    if not os.path.isfile(path):
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(code=1)

    with _client() as c:
        f = c.upload_file(path, folder=folder)
    console.print(f"[green]Uploaded:[/green] {f.display_name} (id={f.id})")


@canvas_app.command(name="delete-file")
def files_delete(
    file_id: int = typer.Argument(..., help="Canvas file ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a file from the course."""
    _require_canvas()
    if not yes and not typer.confirm(f"Delete file {file_id}?"):
        raise typer.Abort()
    with _client() as c:
        c.delete_file(file_id)
    console.print(f"[red]Deleted file {file_id}[/red]")


# ---------------------------------------------------------------------------
# cass canvas announcements
# ---------------------------------------------------------------------------


@canvas_app.command()
def announcements(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List course announcements."""
    from . import report

    _require_canvas()
    with _client() as c:
        anns = c.list_announcements()

    headers = ["ID", "Title", "Posted", "Author"]
    rows = [[str(a.id), a.title, _due(a.posted_at), a.user_name] for a in anns]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Announcements", headers, rows)
    else:
        report.render_list(headers, rows, title="Announcements")


@canvas_app.command(name="announce")
def announcements_create(
    title: str = typer.Argument(..., help="Announcement title"),
    message: str = typer.Option(..., "--message", "-m", help="HTML message body"),
) -> None:
    """Create an announcement."""
    _require_canvas()
    with _client() as c:
        a = c.create_announcement(title, message)
    console.print(f"[green]Created announcement:[/green] {a.title} (id={a.id})")


@canvas_app.command(name="update-announcement")
def announcements_update(
    topic_id: int = typer.Argument(..., help="Announcement (discussion topic) ID"),
    title: str = typer.Option("", "--title", help="New title"),
    message: str = typer.Option("", "--message", "-m", help="New message body"),
) -> None:
    """Update an announcement."""
    _require_canvas()
    kwargs: dict = {}
    if title:
        kwargs["title"] = title
    if message:
        kwargs["message"] = message
    if not kwargs:
        console.print("[yellow]Nothing to update.[/yellow]")
        return
    with _client() as c:
        a = c.update_announcement(topic_id, **kwargs)
    console.print(f"[green]Updated:[/green] {a.title}")


@canvas_app.command(name="delete-announcement")
def announcements_delete(
    topic_id: int = typer.Argument(..., help="Announcement (discussion topic) ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an announcement."""
    _require_canvas()
    if not yes and not typer.confirm(f"Delete announcement {topic_id}?"):
        raise typer.Abort()
    with _client() as c:
        c.delete_announcement(topic_id)
    console.print(f"[red]Deleted announcement {topic_id}[/red]")


# ---------------------------------------------------------------------------
# cass canvas tabs
# ---------------------------------------------------------------------------


@canvas_app.command()
def tabs(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List course navigation tabs."""
    from . import report

    _require_canvas()
    with _client() as c:
        tab_list = c.list_tabs()

    headers = ["ID", "Label", "Type", "Position", "Visibility"]
    rows = [
        [
            t.id,
            t.label,
            t.type,
            str(t.position or ""),
            "hidden" if t.hidden else "visible",
        ]
        for t in sorted(tab_list, key=lambda t: t.position or 999)
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Tabs", headers, rows)
    else:
        report.render_list(headers, rows, title="Tabs")


@canvas_app.command(name="show-tab")
def tabs_show(
    tab_id: str = typer.Argument(..., help="Tab ID to show"),
) -> None:
    """Make a navigation tab visible."""
    _require_canvas()
    with _client() as c:
        t = c.update_tab(tab_id, hidden=False)
    console.print(f"[green]Visible:[/green] {t.label}")


@canvas_app.command(name="hide-tab")
def tabs_hide(
    tab_id: str = typer.Argument(..., help="Tab ID to hide"),
) -> None:
    """Hide a navigation tab."""
    _require_canvas()
    with _client() as c:
        t = c.update_tab(tab_id, hidden=True)
    console.print(f"[yellow]Hidden:[/yellow] {t.label}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pub(val: bool | None) -> str:
    if val is None:
        return ""
    return "[green]yes[/green]" if val else "[dim]no[/dim]"


def _due(val: str | None) -> str:
    if not val:
        return ""
    # Show date portion only
    return val[:10] if len(val) >= 10 else val


def _size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_ / (1024 * 1024):.1f} MB"
