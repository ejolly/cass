"""Typer CLI subcommands for ``cass canvas`` — Canvas LMS management."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import (
    canvas_app,
    canvas_guide,
    client,
    console,
    due,
    err_console,
    pub,
    require_canvas,
    size,
    when,
)
from .assignments import assignments_app
from .calendar import calendar_app
from .modules import modules_app
from .quizzes import quizzes_app

__all__ = [
    "canvas_app",
    "canvas_guide",
    "client",
    "console",
    "due",
    "pub",
    "require_canvas",
    "size",
    "when",
]

canvas_app.add_typer(modules_app, name="modules", rich_help_panel="Browse")
canvas_app.add_typer(assignments_app, name="assignments", rich_help_panel="Browse")
canvas_app.add_typer(quizzes_app, name="quizzes", rich_help_panel="Browse")
canvas_app.add_typer(calendar_app, name="calendar", rich_help_panel="Browse")


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
    from ...actions.config import get_config
    from ...apis.canvas.auth import (
        TOKEN_FILENAME,
        Browser,
        CanvasAuthError,
        TokenAuth,
        find_auth,
    )
    from ...apis.canvas.browser import login_from_browser

    if from_brave == from_chrome:
        raise typer.BadParameter("Choose exactly one: --from-brave or --from-chrome.")
    browser = Browser.BRAVE if from_brave else Browser.CHROME
    _common.require_canvas()
    cfg = get_config()
    err_console.print(
        f"Reading {browser.label}'s Canvas session. macOS may ask for Keychain access."
    )
    try:
        login_from_browser(cfg.root, cfg.canvas_base_url, profile, browser=browser)
    except (CanvasAuthError, OSError) as exc:
        err_console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=1) from None
    console.print(
        "Canvas session saved to .canvascreds. "
        "If Canvas rejects authentication, cass will refresh the cookies from "
        f"{browser.label} and retry the request once."
    )
    if isinstance(find_auth(cfg.root), TokenAuth):
        err_console.print(
            f"{TOKEN_FILENAME} takes priority over this session; "
            "delete it to use the browser session.",
            style="yellow",
        )


@canvas_app.callback()
def canvas_callback(ctx: typer.Context) -> None:
    """Canvas LMS — browse and modify course content."""
    if ctx.invoked_subcommand is not None:
        return
    _common.require_canvas()

    from rich.panel import Panel

    from ...apis.canvas.client import CanvasClient

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
    err_console.print()


# Imported last, in this order, so commands keep their place in the help panels.
# isort: off
from . import people  # noqa: E402
from . import files  # noqa: E402
from . import announcements  # noqa: E402
from . import tabs  # noqa: E402
from . import sync  # noqa: E402, F401
from . import api  # noqa: E402, F401

# isort: on

canvas_app.add_typer(people.people_app, name="people", rich_help_panel="Browse")
canvas_app.add_typer(files.files_app, name="files", rich_help_panel="Browse")
canvas_app.add_typer(
    announcements.announcements_app, name="announcements", rich_help_panel="Browse"
)
canvas_app.add_typer(tabs.tabs_app, name="tabs", rich_help_panel="Browse")
