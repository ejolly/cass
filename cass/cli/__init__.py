"""Typer CLI for cass — workflow commands plus curated querying."""

from __future__ import annotations

__docformat__ = "google"

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from .. import __version__
from ..db import QUERY_DATASETS, TABLE_QUERY_DATASETS
from .canvas import canvas_app
from .sqlite_utils import render_query, render_rows

app = typer.Typer(invoke_without_command=True, no_args_is_help=False)
app.add_typer(canvas_app, name="canvas")

console = Console()


@dataclass
class State:
    no_cache: bool = False
    ttl: float = 6.0


state = State()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"cass {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Force API refresh (bypass cache)"
    ),
    ttl: float = typer.Option(6.0, "--ttl", help="Cache TTL in hours"),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    """cass — Classroom Assignment Grading CLI."""
    state.no_cache = no_cache
    state.ttl = ttl
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def require_classroom() -> None:
    from ..actions.config import get_config

    cfg = get_config()
    if not cfg.has_classroom:
        console.print(
            "[red]This command requires GitHub Classroom configuration.[/red]"
        )
        if cfg.classroom_needs_resolution:
            console.print(
                "GitHub Classroom URL is saved, but the gh-classroom ID is unresolved. "
                "Fix gh auth/Classroom access and rerun [bold]cass init[/bold]."
            )
        else:
            console.print("Add a \\[classroom] section to cass.toml.")
        raise typer.Exit(code=1)


def require_canvas() -> None:
    from ..actions.config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        console.print("[red]This command requires Canvas configuration.[/red]")
        console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


def _pending_count(
    pending: dict[str, dict[str, dict[str, dict[str, object]]]],
) -> int:
    return sum(len(cols) for rows in pending.values() for cols in rows.values())


def _render_pending_summary(
    pending: dict[str, dict[str, dict[str, dict[str, object]]]],
    *,
    title: str,
) -> None:
    table = Table(title=title, show_edge=False, pad_edge=False)
    table.add_column("Table")
    table.add_column("Row")
    table.add_column("Column")
    table.add_column("Baseline")
    table.add_column("Current")

    for table_name, rows in pending.items():
        for pk_key, columns in rows.items():
            for column, values in columns.items():
                table.add_row(
                    table_name,
                    pk_key,
                    column,
                    str(values["baseline"]),
                    str(values["current"]),
                )

    console.print()
    console.print(table)
    console.print(f"\n{_pending_count(pending)} pending change(s)\n")


def _render_push_preview(preview: dict[str, object]) -> None:
    changes_obj = preview.get("changes", [])
    if not isinstance(changes_obj, list):
        return
    changes = cast(list[dict[str, object]], changes_obj)

    table = Table(title="Canvas Push Preview", show_edge=False, pad_edge=False)
    table.add_column("Table")
    table.add_column("Name")
    table.add_column("Column")
    table.add_column("Baseline")
    table.add_column("Current")
    table.add_column("Live")
    table.add_column("Status")

    for change in changes:
        status = "ok"
        if "error" in change:
            status = "error"
        elif bool(change.get("conflict")):
            status = "conflict"
        table.add_row(
            str(change.get("table", "")),
            str(change.get("name", "")),
            str(change.get("column", "")),
            str(change.get("baseline", "")),
            str(change.get("current", "")),
            str(change.get("live", "")),
            status,
        )

    console.print()
    console.print(table)
    if preview.get("has_conflicts"):
        console.print(
            "\n[yellow]Conflicts detected: live Canvas values differ from the "
            "last synced baseline.[/yellow]"
        )
    if preview.get("has_errors"):
        console.print(
            "[yellow]Preview errors detected: some live Canvas values could "
            "not be fetched.[/yellow]"
        )
    console.print()


def _render_push_results(results: list[dict[str, object]]) -> None:
    total_posted = 0
    failed: list[str] = []
    for result in results:
        if result.get("ok"):
            if result.get("action") == "posted_to_students":
                console.print(
                    "  [green]✓[/green] "
                    f"Assignment {result['canvas_assignment_id']}: "
                    "grades now visible to students"
                )
            elif "canvas_id" in result:
                console.print(
                    f"  [green]✓[/green] Assignment {result['canvas_id']}: updated"
                )
            else:
                count = int(cast(int | str, result.get("count", 0)))
                total_posted += count
                console.print(
                    "  [green]✓[/green] "
                    f"Assignment {result['canvas_assignment_id']}: {count} grades"
                )
        else:
            label = str(
                result.get("canvas_id", result.get("canvas_assignment_id", "Canvas"))
            )
            failed.append(f"{label}: {result.get('error', 'unknown error')}")
            console.print(
                f"  [red]✗[/red] {label}: {result.get('error', 'unknown error')}"
            )

    if failed:
        console.print(f"\n[red]Failed {len(failed)} operation(s).[/red]")
    console.print(f"\n[green]Pushed {total_posted} grades/updates.[/green]")


@app.command()
def status() -> None:
    """Show project sync status and the local DB overview."""
    from .. import db
    from ..actions.config import config_file_path, get_config

    cfg_path = config_file_path()
    if cfg_path is None:
        console.print(
            "[yellow]No cass.toml found.[/yellow] "
            "Run [bold]cass init[/bold] to create one."
        )
        return

    cfg = get_config()
    console.print("\n[bold]cass status[/bold]\n")
    console.print(f"Config: {cfg_path}")
    gh_status = "GitHub Classroom [dim]not configured[/dim]"
    if cfg.has_classroom:
        gh_status = "GitHub Classroom"
    elif cfg.classroom_needs_resolution:
        gh_status = "GitHub Classroom [yellow]URL saved; gh ID unresolved[/yellow]"
    console.print(
        "Integrations: "
        + ", ".join(
            [
                "Canvas" if cfg.has_canvas else "Canvas [dim]not configured[/dim]",
                gh_status,
            ]
        )
    )

    db_file = Path(db.db_path())
    if not db_file.exists():
        console.print("\n[yellow]No local database yet.[/yellow]")
        console.print("Next: [bold]cass pull[/bold] to fetch data.\n")
        return

    conn = db.get_db()
    course_name = db.get_meta("course_name", conn)
    size_kb = db_file.stat().st_size / 1024
    if course_name:
        console.print(f"Course: {course_name}")
    console.print(f"Database: {db_file.name} ({size_kb:.0f} KB)")

    tables = {table.name for table in conn.tables}
    console.print("\n[bold]Data[/bold]")
    console.print(
        f"  students: {conn['students'].count if 'students' in tables else 0}"
    )
    console.print(
        f"  assignments: {conn['assignments'].count if 'assignments' in tables else 0}"
    )
    if (
        "canvas_grades" in tables
        and "canvas_assignments" in tables
        and "canvas_students" in tables
    ):
        console.print(
            "  gradebook: "
            f"{conn['canvas_students'].count} students x "
            f"{conn['canvas_assignments'].count} assignments"
        )
    if "canvas_submissions" in tables:
        console.print(f"  canvas submissions: {conn['canvas_submissions'].count}")
    if cfg.has_classroom and "gh_submissions" in tables:
        console.print(f"  github submissions: {conn['gh_submissions'].count}")

    pending = db.get_pending_changes(conn)
    total = _pending_count(pending)
    console.print("\n[bold]Sync[/bold]")
    if total == 0:
        console.print("  [green]All Canvas-managed changes are synchronized.[/green]")
        console.print(
            "\nNext: [bold]cass query gradebook[/bold], "
            "[bold]cass view[/bold], or [bold]cass pull[/bold]\n"
        )
        return

    console.print(f"  [yellow]{total} pending change(s) ready to review.[/yellow]")
    _render_pending_summary(pending, title="Pending Changes")
    console.print(
        "Next: [bold]cass push[/bold], [bold]cass revert[/bold], "
        "or [bold]cass view[/bold]\n"
    )


def ensure_token_gitignored(project_root: Path) -> None:
    """Append .canvastoken to .gitignore if not already present."""
    gitignore = project_root / ".gitignore"
    entry = ".canvastoken"
    if gitignore.exists():
        text = gitignore.read_text()
        if entry in text.splitlines():
            return
        gitignore.write_text(text.rstrip("\n") + f"\n{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")


def _has_saved_canvas_token(project_root: Path) -> bool:
    token_path = project_root / ".canvastoken"
    return token_path.exists() and token_path.read_text().strip() != ""


def _prompt_canvas_course() -> tuple[str, int]:
    from ..actions.config import parse_canvas_course_url

    console.print("[bold]Canvas setup[/bold]")
    console.print(
        "Paste the full course URL from your browser, for example "
        "[bold]https://canvas.ucsd.edu/courses/72335[/bold]."
    )

    while True:
        course_url = typer.prompt("Canvas course URL").strip()
        parsed = parse_canvas_course_url(course_url)
        if parsed is not None:
            return parsed
        console.print(
            "[red]That doesn't look like a Canvas course URL.[/red] "
            "Expected format: [bold]https://canvas.ucsd.edu/courses/72335[/bold]"
        )


def _prompt_canvas_token() -> str:
    console.print("\n[bold]Canvas token[/bold]")
    console.print(
        "Create a token in Canvas under "
        "[bold]Account > Settings > Approved Integrations[/bold]."
    )
    console.print("cass will save it to [bold].canvastoken[/bold].")

    while True:
        token = typer.prompt("Canvas API token", hide_input=True).strip()
        if token:
            return token
        console.print("[red]A Canvas API token is required.[/red]")


def _prompt_classroom_url() -> str:
    console.print("\n[bold]GitHub Classroom[/bold]")
    console.print(
        "Optional. Paste the classroom URL to enable GitHub pulls, "
        "or press Enter to skip it for now."
    )
    return typer.prompt(
        "GitHub Classroom URL",
        default="",
        show_default=False,
    ).strip()


def _resolve_classroom_settings(
    classroom_url: str,
) -> tuple[str, int, int, str, str, str]:
    from ..apis.github.service import resolve_classroom_direct

    result = resolve_classroom_direct(classroom_url)

    if result.gh_account:
        console.print(f"[dim]GitHub account: {result.gh_account}[/dim]")

    if result.resolved is not None:
        return (
            result.resolved.url,
            result.resolved.url_id,
            result.resolved.gh_id,
            result.resolved.slug,
            result.resolved.title,
            result.resolved.org,
        )

    # Failed — return partial with error detail as the last element
    detail = result.error_detail
    if result.recovery_hint:
        detail = f"{detail} {result.recovery_hint}"
    return result.url, result.url_id, 0, "", "", detail


@app.command()
def init() -> None:
    """Initialize or repair the local cass setup."""
    from ..actions.config import (
        CONFIG_FILENAME,
        config_file_path,
        parse_canvas_course_url,
        read_config_data,
        reset_config,
        update_config,
    )
    from ..actions.doctor import check_prerequisites
    from ..apis.canvas.matching import save_token as canvas_save_token

    cfg_path = config_file_path()
    project_root = cfg_path.parent if cfg_path is not None else Path.cwd()
    toml_path = project_root / CONFIG_FILENAME
    token_path = project_root / ".canvastoken"

    try:
        raw = read_config_data(toml_path)
    except tomllib.TOMLDecodeError as exc:
        console.print(f"[red]Invalid cass.toml:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    canvas = raw.get("canvas", {})
    canvas_base_url = ""
    canvas_course_id = 0
    if isinstance(canvas, dict):
        base_url = canvas.get("base_url", "")
        course_id = canvas.get("course_id", 0)
        if isinstance(base_url, str) and isinstance(course_id, int):
            canvas_base_url = base_url
            canvas_course_id = course_id

    classroom = raw.get("classroom", {})
    classroom_url = ""
    classroom_url_id = 0
    classroom_gh_id = 0
    classroom_slug = ""
    classroom_title = ""
    org = ""
    if isinstance(classroom, dict):
        existing_url = classroom.get("url", "")
        existing_url_id = classroom.get("url_id", 0)
        existing_gh_id = classroom.get("gh_id", 0)
        existing_slug = classroom.get("slug", "")
        existing_title = classroom.get("title", "")
        existing_org = classroom.get("org", "")
        if isinstance(existing_url, str):
            classroom_url = existing_url
        if isinstance(existing_url_id, int):
            classroom_url_id = existing_url_id
        if isinstance(existing_gh_id, int):
            classroom_gh_id = existing_gh_id
        if isinstance(existing_slug, str):
            classroom_slug = existing_slug
        if isinstance(existing_title, str):
            classroom_title = existing_title
        if isinstance(existing_org, str):
            org = existing_org

    needs_canvas = not (canvas_base_url and canvas_course_id)
    needs_token = not _has_saved_canvas_token(project_root)
    if cfg_path is None:
        console.print("[bold]cass setup[/bold]")
        console.print(f"[dim]Project directory: {project_root}[/dim]\n")
    else:
        console.print("[bold]cass setup check[/bold]")
        console.print(f"[dim]Project directory: {project_root}[/dim]\n")

    changed = False

    if needs_canvas:
        canvas_base_url, canvas_course_id = _prompt_canvas_course()
        update_config(
            toml_path,
            canvas_base_url=canvas_base_url,
            canvas_course_id=canvas_course_id,
        )
        changed = True
        console.print(
            f"[green]Saved {toml_path.name}[/green] "
            f"for Canvas course [bold]{canvas_course_id}[/bold]."
        )
    else:
        parsed_course_url = f"{canvas_base_url.rstrip('/')}/courses/{canvas_course_id}"
        if parse_canvas_course_url(parsed_course_url) is not None:
            console.print(
                f"[green]Canvas configured[/green] [dim]({parsed_course_url})[/dim]"
            )

    ensure_token_gitignored(project_root)
    if needs_token:
        token = _prompt_canvas_token()
        if cfg_path is None and not changed:
            update_config(
                toml_path,
                canvas_base_url=canvas_base_url,
                canvas_course_id=canvas_course_id,
            )
            changed = True
        canvas_save_token(token)
        reset_config()
        console.print(f"[green]Saved {token_path.name}[/green]")
    else:
        console.print(f"[green]Using existing {token_path.name}[/green]")

    if classroom_gh_id:
        classroom_label = classroom_title or classroom_slug or classroom_url
        console.print(
            "[green]GitHub Classroom configured[/green] "
            f"[dim]({classroom_label}, gh classroom {classroom_gh_id})[/dim]"
        )
    elif classroom_url and classroom_url_id and not classroom_gh_id:
        # Retry resolution for previously saved but unresolved classroom
        console.print(
            "\n[bold]GitHub Classroom[/bold] "
            "[dim](retrying resolution for saved URL)[/dim]"
        )
        (
            classroom_url,
            classroom_url_id,
            classroom_gh_id,
            classroom_slug,
            classroom_title,
            gh_detail,
        ) = _resolve_classroom_settings(classroom_url)
        if classroom_url and classroom_url_id:
            update_config(
                toml_path,
                classroom_url=classroom_url,
                classroom_url_id=classroom_url_id,
                classroom_gh_id=classroom_gh_id,
                classroom_slug=classroom_slug,
                classroom_title=classroom_title,
                org=gh_detail if classroom_gh_id else org,
            )
            changed = True
        if classroom_gh_id:
            classroom_label = classroom_title or classroom_slug or classroom_url
            console.print(
                "[green]GitHub Classroom configured[/green] "
                f"[dim]({classroom_label}, "
                f"gh classroom {classroom_gh_id})[/dim]"
            )
        else:
            console.print(
                "[yellow]GitHub Classroom URL saved, but setup is incomplete.[/yellow]"
            )
            console.print(
                gh_detail
                or "Resolve the gh-classroom ID and run [bold]cass init[/bold] again."
            )
    else:
        prompt_url = _prompt_classroom_url()
        if prompt_url:
            (
                classroom_url,
                classroom_url_id,
                classroom_gh_id,
                classroom_slug,
                classroom_title,
                gh_detail,
            ) = _resolve_classroom_settings(
                prompt_url,
            )
            if classroom_url and classroom_url_id:
                update_config(
                    toml_path,
                    classroom_url=classroom_url,
                    classroom_url_id=classroom_url_id,
                    classroom_gh_id=classroom_gh_id,
                    classroom_slug=classroom_slug,
                    classroom_title=classroom_title,
                    org=gh_detail if classroom_gh_id else org,
                )
                changed = True
            if classroom_gh_id:
                classroom_label = classroom_title or classroom_slug or classroom_url
                console.print(
                    "[green]GitHub Classroom configured[/green] "
                    f"[dim]({classroom_label}, gh classroom {classroom_gh_id})[/dim]"
                )
            elif classroom_url_id:
                console.print(
                    "[yellow]GitHub Classroom URL saved, but setup is "
                    "incomplete.[/yellow]"
                )
                console.print(
                    gh_detail
                    or "Resolve the gh-classroom ID and run [bold]cass init[/bold] or "
                    "[bold]cass pull[/bold] again."
                )
        else:
            if classroom:
                update_config(
                    toml_path,
                    classroom_url=None,
                    classroom_url_id=None,
                    classroom_gh_id=None,
                    classroom_slug=None,
                    classroom_title=None,
                    org=None,
                )
                changed = True
            console.print("[dim]GitHub Classroom skipped.[/dim]")

    if changed and cfg_path is None:
        console.print(f"\n[green]Created {toml_path.name}[/green]")

    console.print("\n[bold]Setup status[/bold]\n")
    checks = check_prerequisites()
    all_ok = True
    for check in checks:
        indent = "  " * check.indent
        icon = "[green]\u2713[/green]" if check.ok else "[red]\u2717[/red]"
        console.print(f"  {indent}{icon} {check.name}  [dim]{check.detail}[/dim]")
        if not check.ok:
            all_ok = False

    console.print()
    if all_ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print(
            "Some optional integrations still need attention. "
            "Run [bold]cass init[/bold] again after fixing them."
        )


@app.command()
def pull(
    do_students: bool = typer.Option(False, "--students", help="Pull students only"),
    do_assignments: bool = typer.Option(
        False, "--assignments", help="Pull assignments only"
    ),
    do_submissions: bool = typer.Option(
        False, "--submissions", help="Pull submissions only"
    ),
    limit: int = typer.Option(0, "--limit", help="Limit number of students (0 = all)"),
) -> None:
    """Fetch from APIs and update the local database."""
    import asyncio

    from .. import db
    from ..actions import pull as pull_mod
    from ..actions.config import get_config
    from ..apis.github.client import GitHubClient

    cfg = get_config()
    pull_all = not any([do_students, do_assignments, do_submissions])
    if (reason := db.pull_block_reason()) is not None:
        console.print(f"[red]{reason}[/red]")
        raise typer.Exit(code=1)

    if cfg.has_canvas:
        from ..apis.canvas.matching import fetch_course_name
        from ..db import save_meta

        save_meta("course_name", fetch_course_name(cfg.canvas_course_id))

    async def _pull() -> None:
        client = None
        if cfg.has_classroom:
            client = GitHubClient()
        try:
            if pull_all or do_students:
                await pull_mod.pull_students(
                    client, cfg, console, state.ttl, state.no_cache
                )
            if pull_all or do_assignments:
                await pull_mod.pull_assignments(
                    client, cfg, console, state.ttl, state.no_cache
                )
            if pull_all or do_submissions:
                await pull_mod.pull_submissions(
                    client, cfg, console, state.ttl, state.no_cache
                )
        finally:
            if client:
                await client.close()

    try:
        asyncio.run(_pull())
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command()
def push(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Preview and push pending Canvas-managed changes."""
    from .. import db

    require_canvas()

    conn = db.get_db()
    pending = db.get_pending_changes(conn)
    if _pending_count(pending) == 0:
        console.print("[yellow]No pending Canvas changes to push.[/yellow]")
        return

    preview = db.canvas_preview(conn, pending)
    changes = preview.get("changes", [])
    if not changes:
        console.print("[yellow]No pending Canvas changes to push.[/yellow]")
        return

    _render_push_preview(preview)

    if not yes and not typer.confirm("Push these changes to Canvas?", default=False):
        raise typer.Abort()

    result = db.canvas_apply(conn, pending)
    _render_push_results(cast(list[dict[str, object]], result.get("results", [])))


@app.command()
def revert(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Revert local pending Canvas-managed changes since the last sync."""
    from .. import db

    conn = db.get_db()
    pending = db.get_pending_changes(conn)
    if _pending_count(pending) == 0:
        console.print("[yellow]No pending changes to revert.[/yellow]")
        return

    _render_pending_summary(pending, title="Revert Preview")
    if not yes and not typer.confirm("Revert these local changes?", default=False):
        raise typer.Abort()

    count = db.revert_changes(conn, pending)
    console.print(f"[green]Reverted {count} change(s).[/green]")


@app.command()
def query(
    dataset: str = typer.Argument(
        "", help=f"Dataset to query ({', '.join(QUERY_DATASETS)})"
    ),
    where: str = typer.Option("", "--where", help="Filter expression"),
    order: str = typer.Option("", "--order", help="Order expression"),
    limit: int = typer.Option(0, "--limit", help="Limit rows (0 = all)"),
    sql_text: str = typer.Option("", "--sql", help="Raw SQL (advanced usage)"),
) -> None:
    """Query curated datasets, or use raw SQL as an explicit escape hatch."""
    from .. import db
    from . import report

    if dataset and sql_text:
        console.print("[red]Provide either a dataset or --sql, not both.[/red]")
        raise typer.Exit(code=1)
    if not dataset and not sql_text:
        console.print(
            f"[red]Provide a dataset ({', '.join(QUERY_DATASETS)}) or --sql.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        if sql_text:
            typer.echo(render_query(db.db_path(), sql_text), nl=False)
            return

        if dataset not in QUERY_DATASETS:
            console.print(
                f"[red]Unknown dataset '{dataset}'. "
                f"Choose from: {', '.join(QUERY_DATASETS)}[/red]"
            )
            raise typer.Exit(code=1)

        if dataset in TABLE_QUERY_DATASETS:
            typer.echo(
                render_rows(
                    db.db_path(),
                    TABLE_QUERY_DATASETS[dataset],
                    where=where,
                    order=order,
                    limit=limit,
                ),
                nl=False,
            )
            return

        if dataset == "submissions":
            typer.echo(
                render_query(
                    db.db_path(),
                    db.build_submissions_query(where=where, order=order, limit=limit),
                ),
                nl=False,
            )
            return

        if where or order:
            console.print(
                "[red]The gradebook dataset only supports --limit in CLI mode.[/red]"
            )
            raise typer.Exit(code=1)

        conn = db.get_db()
        headers, rows = db.build_canvas_gradebook_matrix(conn)
        if limit:
            rows = rows[:limit]
        report.render_list(headers, rows, title="Gradebook")
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command(name="pull-repos")
def pull_gh(
    assignment: str = typer.Option(
        "", "--assignment", "-a", help="Specific assignment slug (default: all)"
    ),
    limit_students: int = typer.Option(
        0, "--limit-students", "-s", help="Max students to pull (0 = all)"
    ),
    limit_assignments: int = typer.Option(
        0, "--limit-assignments", "-n", help="Max assignments to pull (0 = all)"
    ),
) -> None:
    """Clone or update student repos from GitHub Classroom into gh-classroom/."""
    import asyncio

    from .. import db
    from ..apis.github import fetch as fetch_mod
    from ..apis.github.client import GitHubClient

    require_classroom()
    roster = db.load_students()
    assignments = db.load_assignments()
    gh_assignments = [
        assignment_row
        for assignment_row in assignments
        if assignment_row.gh_assignment_slug
    ]

    if not gh_assignments:
        console.print("[yellow]No GitHub-linked assignments found.[/yellow]")
        raise typer.Exit(code=1)

    if assignment:
        targets = [row for row in gh_assignments if assignment in row.slug]
        if not targets:
            console.print(f"[red]No assignment matching '{assignment}'[/red]")
            raise typer.Exit(code=1)
    else:
        targets = gh_assignments

    async def _pull() -> None:
        async with GitHubClient() as client:
            counts = await fetch_mod.pull_gh(
                client,
                targets,
                roster,
                limit_students=limit_students,
                limit_assignments=limit_assignments,
            )
        console.print(
            f"\n[green]{counts['cloned']} cloned[/green], "
            f"[cyan]{counts['updated']} updated[/cyan], "
            f"[dim]{counts['up_to_date']} up-to-date[/dim], "
            f"[dim]{counts['skipped']} skipped[/dim], "
            f"[red]{counts['errors']} errors[/red]"
        )

    asyncio.run(_pull())


@app.command(name="delete")
def delete(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete the local database (cass.db)."""
    from .. import db

    db_file = Path(db.db_path())
    if not db_file.exists():
        console.print("[dim]No database to delete.[/dim]")
        return

    if not yes:
        size_kb = db_file.stat().st_size / 1024
        if not typer.confirm(f"Delete {db_file} ({size_kb:.0f} KB)?", default=False):
            raise typer.Abort()

    db.reset()
    db_file.unlink()
    console.print(f"[green]Deleted {db_file.name}[/green]")


def ensure_backups_gitignored(project_root: Path) -> None:
    """Append backups/ to .gitignore if not already present."""
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        text = gitignore.read_text()
        if "backups/" in text:
            return
        gitignore.write_text(text.rstrip("\n") + "\nbackups/\n")
    else:
        gitignore.write_text("backups/\n")


@app.command()
def backup(
    tag: str = typer.Option("", "--tag", "-t", help="Tag appended to filename"),
    list_backups: bool = typer.Option(
        False, "--list", "-l", help="List existing backups"
    ),
) -> None:
    """Save a timestamped copy of the database to backups/."""
    import shutil
    from datetime import datetime

    from .. import db
    from ..actions.config import get_config

    project_root = get_config().root
    backups_dir = project_root / "backups"

    if list_backups:
        if not backups_dir.exists():
            console.print("[dim]No backups directory.[/dim]")
            return
        files = sorted(backups_dir.glob("cass_*.db"))
        if not files:
            console.print("[dim]No backups found.[/dim]")
            return
        for file in files:
            size_kb = file.stat().st_size / 1024
            console.print(f"  {file.name}  [dim]({size_kb:.0f} KB)[/dim]")
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_{tag}" if tag else ""
    dest = backups_dir / f"cass_{stamp}{suffix}.db"

    db_file = Path(db.db_path())
    if not db_file.exists():
        console.print(
            "[yellow]No database to back up. Run [bold]cass pull[/bold] first.[/yellow]"
        )
        raise typer.Exit(code=1)

    backups_dir.mkdir(exist_ok=True)
    ensure_backups_gitignored(project_root)
    db.reset()
    shutil.copy2(str(db_file), str(dest))

    size_kb = dest.stat().st_size / 1024
    console.print(
        "[green]Backed up → "
        f"{dest.relative_to(project_root)} ({size_kb:.0f} KB)[/green]"
    )


@app.command()
def restore(
    file: str = typer.Argument(..., help="Path to a .db backup file"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Replace the current database with a backup file."""
    import shutil

    import sqlite_utils

    from .. import db

    src = Path(file)
    if not src.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)
    if src.suffix != ".db":
        console.print("[red]Expected a .db file.[/red]")
        raise typer.Exit(code=1)

    try:
        backup_db = sqlite_utils.Database(str(src))
        row = backup_db.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        version = int(row[0]) if row else 0
        counts: dict[str, int] = {}
        for table in ("students", "assignments"):
            try:
                counts[table] = backup_db[table].count
            except Exception:
                counts[table] = 0
    except Exception as exc:
        console.print(f"[red]Invalid database file: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    src_kb = src.stat().st_size / 1024
    console.print(f"  Backup: [bold]{src.name}[/bold] ({src_kb:.0f} KB)")
    console.print(f"  Schema version: {version}")
    console.print(
        f"  Students: {counts['students']}, Assignments: {counts['assignments']}"
    )

    target = db.db_path()
    db_file = Path(target)
    if db_file.exists():
        cur_kb = db_file.stat().st_size / 1024
        console.print(f"  Current DB: {db_file.name} ({cur_kb:.0f} KB)")
    else:
        console.print("  Current DB: [dim]none[/dim]")

    if not yes and not typer.confirm(
        "\nReplace current database with this backup?", default=False
    ):
        raise typer.Abort()

    db.reset()
    shutil.copy2(str(src), str(Path(target)))
    console.print(f"[green]Restored {src.name} → {Path(target).name}[/green]")


@app.command()
def view(
    filepath: str = typer.Argument("", help="Path to a .duckdb or .db file (optional)"),
    port: int = typer.Option(0, "--port", help="Port number (0 = auto-select)"),
) -> None:
    """Open the database in a browser-based viewer."""
    if filepath:
        path = Path(filepath).resolve()
        if not path.exists():
            raise SystemExit(f"File not found: {path}")
        if path.suffix not in {".duckdb", ".db"}:
            raise SystemExit(f"Unsupported file type: {path.suffix}")
        from ..viewer.nicegui_app import start_nicegui_server

        start_nicegui_server(port=port, generic_file=path)
    else:
        from ..actions.config import get_config
        from ..viewer.nicegui_app import start_nicegui_server

        start_nicegui_server(port=port, project_root=get_config().root)
