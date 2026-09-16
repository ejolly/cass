"""Typer CLI for cass — workflow commands plus curated querying."""

from __future__ import annotations

__docformat__ = "google"

import tomllib
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


def version_callback(value: bool) -> None:
    if value:
        console.print(f"cass {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    """cass — Canvas grading CLI."""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


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
    console.print(
        "Canvas: " + ("configured" if cfg.has_canvas else "[dim]not configured[/dim]")
    )
    if cfg.has_canvas:
        from ..apis.canvas.auth import find_auth

        auth = find_auth(cfg.root)
        auth_label = auth.description if auth else "[red]not found[/red]"
        console.print(f"Canvas auth: {auth_label}")

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
        "  students: "
        f"{conn['canvas_students'].count if 'canvas_students' in tables else 0}"
    )
    console.print(
        "  assignments: "
        f"{conn['canvas_assignments'].count if 'canvas_assignments' in tables else 0}"
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
    """Append the Canvas credential files to .gitignore if not already present."""
    from ..apis.canvas.auth import CREDS_FILENAME, TOKEN_FILENAME

    gitignore = project_root / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [n for n in (TOKEN_FILENAME, CREDS_FILENAME) if n not in existing]
    if not missing:
        return
    text = "\n".join(existing).rstrip("\n")
    prefix = text + "\n" if text else ""
    gitignore.write_text(prefix + "\n".join(missing) + "\n")


def _saved_credentials_file(project_root: Path) -> str | None:
    """Name of the Canvas credentials file already in the project, if any."""
    from ..apis.canvas.auth import CREDS_FILENAME, TOKEN_FILENAME

    for name in (CREDS_FILENAME, TOKEN_FILENAME):
        path = project_root / name
        if path.exists() and path.read_text().strip():
            return name
    return None


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

    needs_canvas = not (canvas_base_url and canvas_course_id)
    saved_credentials = _saved_credentials_file(project_root)
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
    if saved_credentials is None:
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
    elif saved_credentials == token_path.name:
        console.print(f"[green]Using existing {token_path.name}[/green]")
    else:
        console.print(
            f"[green]Using session cookie from {saved_credentials}[/green] "
            "[dim](delete it to switch back to an API token)[/dim]"
        )

    if "classroom" in raw:
        update_config(toml_path)
        changed = True
        console.print("[dim]Removed obsolete \\[classroom] section.[/dim]")

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
            "Some checks failed. Run [bold]cass init[/bold] again after fixing them."
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
) -> None:
    """Fetch from Canvas and update the local database."""
    from .. import db
    from ..actions import pull as pull_mod
    from ..actions.config import get_config

    cfg = get_config()
    if (reason := db.pull_block_reason()) is not None:
        console.print(f"[red]{reason}[/red]")
        raise typer.Exit(code=1)

    try:
        if not any([do_students, do_assignments, do_submissions]):
            pull_mod.pull_all(
                cfg,
                on_progress=lambda step, detail: console.print(
                    f"  [dim]{step}[/dim] {detail}"
                ),
            )
            return
        if do_students:
            pull_mod.pull_students(cfg, console)
        if do_assignments:
            pull_mod.pull_assignments(cfg, console)
        if do_submissions:
            pull_mod.pull_submissions(cfg, console)
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


def run() -> None:
    """Console-script entry point: run the CLI, reporting auth failures cleanly."""
    import httpx

    from ..apis.canvas.auth import CanvasAuthError

    try:
        app()
    except CanvasAuthError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from None
    except httpx.HTTPStatusError as exc:
        resp = exc.response
        console.print(
            f"[red]Canvas returned {resp.status_code} for "
            f"{exc.request.method} {exc.request.url.path}[/red]"
        )
        raise SystemExit(1) from None
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from None
