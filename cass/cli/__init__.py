"""Typer CLI for cass — classroom assignment grading toolkit."""

from __future__ import annotations

__docformat__ = "google"

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from ..models import CanvasGrade

from .. import __version__
from .canvas import canvas_app

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
)
grades_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Show the gradebook as a student x assignment matrix, "
    "or push grades to Canvas.",
)
app.add_typer(grades_app, name="grades")
db_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Database tools: interactive REPL and cache management.",
)
app.add_typer(db_app, name="db")
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
        status_display()


def require_classroom() -> None:
    from ..config import get_config

    cfg = get_config()
    if not cfg.has_classroom:
        console.print(
            "[red]This command requires GitHub Classroom configuration.[/red]"
        )
        console.print("Add a \\[classroom] section to cass.toml.")
        raise typer.Exit(code=1)


def require_canvas() -> None:
    from ..config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        console.print("[red]This command requires Canvas configuration.[/red]")
        console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# cass status
# ---------------------------------------------------------------------------


def status_display() -> None:
    from .. import cache, db
    from ..config import config_file_path, get_config

    cfg_path = config_file_path()
    if not cfg_path:
        console.print(
            "[yellow]No cass.toml found.[/yellow] "
            "Run [bold]cass init[/bold] to create one."
        )
        return

    cfg = get_config()
    console.print("[bold]cass[/bold] project status\n")
    console.print(f"  Config: {cfg_path}")

    if cfg.has_classroom:
        console.print(
            f"  GitHub Classroom: org=[bold]{cfg.org}[/bold] id={cfg.classroom_id}"
        )
    else:
        console.print("  GitHub Classroom: [dim]not configured[/dim]")

    if cfg.has_canvas:
        console.print(
            f"  Canvas: [bold]{cfg.canvas_base_url}[/bold] "
            f"course={cfg.canvas_course_id}"
        )
    else:
        console.print("  Canvas: [dim]not configured[/dim]")

    if db.is_remote():
        console.print(f"\n  Database: [bold]{db.db_path()}[/bold] (MotherDuck)")
    else:
        db_file = Path(db.db_path())
        if db_file.exists():
            size_kb = db_file.stat().st_size / 1024
            console.print(f"\n  Database: {db_file.name} ({size_kb:.0f} KB)")
        else:
            console.print("\n  Database: [dim]not created yet[/dim]")

    if db.is_remote() or Path(db.db_path()).exists():
        cache_kb = cache.cache_size_kb()
        if cache_kb > 0:
            console.print(
                f"    Cache: {cache.cache_count()} entries ({cache_kb:.0f} KB)"
            )
        if db.students_exist():
            students = db.load_students()
            gh_count = sum(1 for s in students if s.github_username)
            console.print(
                f"    Students: {len(students)} ({gh_count} with GitHub links)"
            )
        else:
            console.print("    Students: [dim]none[/dim]")
        assignments = db.load_assignments()
        if assignments:
            console.print(f"    Assignments: {len(assignments)}")

    console.print()


# ---------------------------------------------------------------------------
# cass init
# ---------------------------------------------------------------------------

_INIT_TOML = """\
# Configure at least one of [classroom] or [canvas]

# GitHub Classroom integration (requires `gh` CLI)
# [classroom]
# id = 0          # GitHub Classroom ID (from URL or API)
# org = "my-org"  # GitHub organization name

# Canvas LMS integration
# [canvas]
# base_url = "https://canvas.example.edu"
# course_id = 0
"""


@app.command()
def init() -> None:
    """Initialize a new project or check an existing setup."""
    from ..canvas.matching import save_token as canvas_save_token
    from ..config import (
        check_prerequisites,
        config_file_path,
        reset_config,
        write_config,
    )

    cfg_path = config_file_path()

    if cfg_path is None:
        cwd = Path.cwd()
        toml_path = cwd / "cass.toml"
        console.print("[bold]Setting up cass...[/bold]\n")
        classroom_id = 0
        org = ""
        canvas_base_url = ""
        canvas_course_id = 0

        if typer.confirm("Configure GitHub Classroom?", default=True):
            raw = typer.prompt("  Classroom ID", default="0")
            classroom_id = int(raw) if raw.strip() and raw.strip() != "0" else 0
            org = typer.prompt("  GitHub org", default="").strip()

        if typer.confirm("Configure Canvas LMS?", default=False):
            canvas_base_url = typer.prompt(
                "  Canvas base URL (e.g. https://canvas.ucsd.edu)"
            )
            raw = typer.prompt("  Canvas course ID", default="0")
            canvas_course_id = int(raw) if raw.strip() and raw.strip() != "0" else 0
            if canvas_base_url and canvas_course_id:
                token = typer.prompt(
                    "  Canvas API token (or Enter to skip)", default="", hide_input=True
                )
                if token.strip():
                    write_config(
                        toml_path, classroom_id, org, canvas_base_url, canvas_course_id
                    )
                    canvas_save_token(token)
                    reset_config()
                    console.print(f"\n[green]Created {toml_path.name}[/green]")
                    return

        has_cc = bool(classroom_id and org)
        has_cv = bool(canvas_base_url and canvas_course_id)

        if not has_cc and not has_cv:
            toml_path.write_text(_INIT_TOML)
            console.print(f"\n[green]Created {toml_path.name}[/green]")
            console.print(
                "Edit it with your settings, then run [bold]cass init[/bold] again."
            )
            return

        write_config(toml_path, classroom_id, org, canvas_base_url, canvas_course_id)
        console.print(f"\n[green]Created {toml_path.name}[/green]")
        return

    console.print("[bold]Checking setup...[/bold]\n")
    checks = check_prerequisites()
    all_ok = True
    for c in checks:
        indent = "  " * c.indent
        icon = "[green]\u2713[/green]" if c.ok else "[red]\u2717[/red]"
        console.print(f"  {indent}{icon} {c.name}  [dim]{c.detail}[/dim]")
        if not c.ok:
            all_ok = False

    console.print()
    if all_ok:
        console.print("[green]All checks passed![/green]")
    else:
        console.print("Fix the issues above and run [bold]cass init[/bold] again.")


# ---------------------------------------------------------------------------
# cass pull
# ---------------------------------------------------------------------------


@app.command()
def pull(
    do_students: bool = typer.Option(False, "--students", help="Pull students only"),
    do_assignments: bool = typer.Option(
        False, "--assignments", help="Pull assignments only"
    ),
    do_submissions: bool = typer.Option(
        False, "--submissions", help="Pull submissions only"
    ),
    do_grades: bool = typer.Option(False, "--grades", help="Pull grades only"),
    do_fetch: bool = typer.Option(False, "--fetch", help="Also download student files"),
    limit: int = typer.Option(0, "--limit", help="Limit number of students (0 = all)"),
) -> None:
    """Fetch from APIs and update the local database."""
    import asyncio

    from .. import pull as pull_mod
    from ..config import get_config
    from ..github.client import GitHubClient

    cfg = get_config()
    pull_all = not any([do_students, do_assignments, do_submissions, do_grades])

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

    asyncio.run(_pull())

    if pull_all or do_grades:
        pull_mod.pull_grades(console)
    if do_fetch:
        require_classroom()

        async def _fetch() -> None:
            async with GitHubClient() as c:
                await pull_mod.pull_fetch(c, console, state.ttl, state.no_cache, limit)

        asyncio.run(_fetch())


# ---------------------------------------------------------------------------
# cass students
# ---------------------------------------------------------------------------


@app.command()
def students(
    all_students: bool = typer.Option(
        False, "--all", help="Show all students including excluded"
    ),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option(
        "", "--where", help="SQL WHERE filter (e.g. --where \"github_username != ''\")"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """Show the student roster."""
    from .. import db
    from . import report

    if not db.students_exist():
        console.print("[yellow]No roster. Run [bold]cass pull[/bold] first.[/yellow]")
        raise typer.Exit(code=1)

    conn = db.get_db()
    where_clause = "WHERE excluded = false" if not all_students else ""
    if where:
        where_clause = (
            f"WHERE {where}" if not where_clause else f"{where_clause} AND ({where})"
        )

    result = conn.sql(
        f"SELECT canvas_id, github_username, name, email"
        f"{', excluded' if all_students else ''} "
        f"FROM students {where_clause} ORDER BY lower(name)"
    )

    if csv_out:
        report.write_csv_file(csv_out, relation=result)
    elif save:
        report.save_relation_markdown(save, "Students", result)
    else:
        report.render_table(result, title="Students")


# ---------------------------------------------------------------------------
# cass assignments
# ---------------------------------------------------------------------------


@app.command()
def assignments(
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option(
        "",
        "--where",
        help="SQL WHERE filter (e.g. --where \"gh_assignment_slug != ''\")",
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """Show assignment metadata."""
    from .. import db
    from . import report

    conn = db.get_db()
    where_clause = f"WHERE {where}" if where else ""
    result = conn.sql(
        f"SELECT slug, title, gh_assignment_slug, canvas_assignment_id, "
        f"points_possible, deadline "
        f"FROM assignments {where_clause} ORDER BY slug"
    )

    if csv_out:
        report.write_csv_file(csv_out, relation=result)
    elif save:
        report.save_relation_markdown(save, "Assignments", result)
    else:
        report.render_table(result, title="Assignments")


# ---------------------------------------------------------------------------
# cass submissions [SLUG]
# ---------------------------------------------------------------------------


@app.command()
def submissions(
    slug: str = typer.Argument("", help="Assignment slug to filter (or empty for all)"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option(
        "", "--where", help="SQL WHERE filter (e.g. --where \"source='github'\")"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """View submission status from source tables."""
    from .. import db
    from . import report

    conn = db.get_db()
    conditions: list[str] = []
    if slug:
        conditions.append(f"assignment LIKE '%{slug}%'")
    if where:
        conditions.append(f"({where})")
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = conn.sql(
        f"SELECT * FROM ("
        f"  SELECT s.name AS student, a.slug AS assignment, 'github' AS source,"
        f"    gs.submitted, gs.late, gs.lateness_seconds,"
        f"    gs.repo_name, gs.commits_after_deadline, gs.commit_count"
        f"  FROM gh_submissions gs"
        f"  JOIN students s ON s.github_username = gs.github_username"
        f"  JOIN assignments a ON a.gh_assignment_slug = gs.assignment_slug"
        f"  UNION ALL"
        f"  SELECT s.name AS student, a.slug AS assignment, 'canvas' AS source,"
        f"    cs.submitted, cs.late, cs.lateness_seconds,"
        f"    '' AS repo_name, 0 AS commits_after_deadline, 0 AS commit_count"
        f"  FROM canvas_submissions cs"
        f"  JOIN students s ON s.canvas_id = cs.canvas_user_id"
        f"  JOIN assignments a ON a.canvas_assignment_id = cs.canvas_assignment_id"
        f") sub {where_clause} ORDER BY assignment, student"
    )

    if csv_out:
        report.write_csv_file(csv_out, relation=result)
    elif save:
        report.save_relation_markdown(
            save, f"Submissions{' — ' + slug if slug else ''}", result
        )
    else:
        report.render_table(result, title=f"Submissions{' — ' + slug if slug else ''}")


# ---------------------------------------------------------------------------
# cass grades / cass grades push
# ---------------------------------------------------------------------------


@grades_app.callback()
def grades_callback(
    ctx: typer.Context,
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option("", "--where", help="SQL WHERE filter"),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """Show the gradebook as a student x assignment matrix with computed grades."""
    if ctx.invoked_subcommand is not None:
        return

    from .. import db
    from . import report

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT s.name AS student, a.slug AS assignment,"
            "  cg.posted_grade AS display_grade"
            " FROM canvas_grades cg"
            " JOIN students s ON s.canvas_id = cg.canvas_user_id"
            " JOIN assignments a ON a.canvas_assignment_id = cg.canvas_assignment_id"
        ).fetchall()
    except Exception as exc:
        console.print("[yellow]No grades. Run [bold]cass pull[/bold] first.[/yellow]")
        raise typer.Exit(code=1) from exc

    if not rows:
        console.print("[yellow]No grades. Run [bold]cass pull[/bold] first.[/yellow]")
        raise typer.Exit(code=1)

    students_set: dict[str, None] = {}
    assignments_set: dict[str, None] = {}
    grade_map: dict[tuple[str, str], str] = {}
    for student_name, assignment_slug, display_grade in rows:
        students_set[student_name] = None
        assignments_set[assignment_slug] = None
        grade_map[(student_name, assignment_slug)] = display_grade

    assignment_ids = sorted(assignments_set)
    student_ids = sorted(students_set)

    headers = ["Student", *assignment_ids]
    matrix_rows: list[list[str]] = []
    for sid in student_ids:
        row = [sid] + [grade_map.get((sid, aid), "-") for aid in assignment_ids]
        matrix_rows.append(row)

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=matrix_rows)
    elif save:
        report.save_markdown(save, "Grades", headers, matrix_rows)
    else:
        report.render_list(headers, matrix_rows, title="Grades")


@grades_app.command()
def push(
    post: bool = typer.Option(
        False, "--post", help="Actually push grades (default: dry-run)"
    ),
) -> None:
    """Sync grades to Canvas LMS (dry-run by default, use --post to submit)."""
    from collections import defaultdict

    from rich.table import Table

    from .. import db

    require_canvas()

    canvas_grades = db.load_canvas_grades()
    if not canvas_grades:
        console.print("[yellow]No Canvas grades to push.[/yellow]")
        raise typer.Exit(code=1)

    # Build {aid: {uid: grade_string}}, skipping empty/placeholder grades
    grade_data_by_aid: dict[int, dict[int, str]] = {}
    by_assignment: dict[int, list[CanvasGrade]] = defaultdict(list)
    total_skipped = 0
    for g in canvas_grades:
        by_assignment[g.canvas_assignment_id].append(g)
        if not g.posted_grade or g.posted_grade in ("-", "?"):
            total_skipped += 1
            continue
        grade_data_by_aid.setdefault(g.canvas_assignment_id, {})[g.canvas_user_id] = (
            g.posted_grade
        )

    assignments = db.load_assignments()
    aid_to_title = {
        a.canvas_assignment_id: a.title for a in assignments if a.canvas_assignment_id
    }

    # Preview table
    conn = db.get_db()
    manual_rows = conn.execute(
        "SELECT canvas_id, post_manually FROM canvas_assignments"
    ).fetchall()
    post_manually_map = {r[0]: r[1] for r in manual_rows}

    table = Table(title="Grade Push Preview", show_edge=False, pad_edge=False)
    table.add_column("Canvas Assignment")
    table.add_column("Canvas ID", justify="right")
    table.add_column("Grades")
    table.add_column("Post Policy")

    for aid, grades in sorted(by_assignment.items()):
        title = aid_to_title.get(aid, f"Assignment {aid}")
        pushable = [
            g for g in grades if g.posted_grade and g.posted_grade not in ("-", "?")
        ]
        policy = "[yellow]manual[/yellow]" if post_manually_map.get(aid) else "auto"
        table.add_row(title, str(aid), str(len(pushable)), policy)

    console.print()
    console.print(table)
    console.print()

    if not post:
        console.print(
            "[yellow]Dry run — no grades posted. Use --post to push to Canvas.[/yellow]"
        )
        return

    from ..canvas.client import CanvasClient
    from ..canvas.sync import push_grades

    with CanvasClient() as c:
        results = push_grades(c, conn, grade_data_by_aid)

    total_posted = 0
    failed: list[str] = []
    for r in results:
        aid: int = r["canvas_assignment_id"]  # type: ignore[assignment]
        title = aid_to_title.get(aid, f"Assignment {aid}")
        if r.get("ok"):
            if r.get("action") == "posted_to_students":
                console.print(
                    f"  [green]✓[/green] {title}: grades now visible to students"
                )
            else:
                count: int = r.get("count", 0)  # type: ignore[assignment]
                total_posted += count
                console.print(f"  [green]✓[/green] {title}: {count} grades")
        else:
            action = f" ({r['action']})" if r.get("action") else ""
            failed.append(f"{title}{action}: {r.get('error')}")
            console.print(f"  [red]✗[/red] {title}{action}: {r.get('error')}")

    if failed:
        console.print(f"\n[red]Failed {len(failed)} operation(s).[/red]")
    console.print(
        f"\n[green]Pushed {total_posted} grades, skipped {total_skipped}.[/green]"
    )


# ---------------------------------------------------------------------------
# cass fetch SLUG
# ---------------------------------------------------------------------------


@app.command()
def fetch(
    slug: str = typer.Argument(..., help="Assignment slug (or 'all')"),
    force: bool = typer.Option(False, "--force", help="Re-download existing files"),
    limit: int = typer.Option(0, "--limit", help="Limit number of students (0 = all)"),
) -> None:
    """Download student submission files."""
    import asyncio

    from .. import db
    from ..github import fetch as fetch_mod
    from ..github.client import GitHubClient

    require_classroom()
    students = db.load_students()
    assignments = db.load_assignments()
    gh_assignments = [a for a in assignments if a.gh_assignment_slug]

    if slug == "all":
        targets = gh_assignments
    else:
        targets = [a for a in gh_assignments if slug in a.slug]
        if not targets:
            console.print(f"[red]No assignment matching '{slug}'[/red]")
            raise typer.Exit(code=1)

    async def _fetch() -> None:
        async with GitHubClient() as client:
            for target in targets:
                console.print(f"\n[bold]{target.gh_assignment_slug}[/bold]")
                await fetch_mod.fetch_assignment(
                    client,
                    target,
                    students,
                    force=force,
                    limit=limit,
                    ttl_hours=state.ttl,
                    force_refresh=state.no_cache,
                )

    asyncio.run(_fetch())


# ---------------------------------------------------------------------------
# cass drop
# ---------------------------------------------------------------------------


@app.command()
def drop(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete the local database (cass.duckdb). Not supported for MotherDuck."""
    from .. import db

    if db.is_remote():
        console.print(
            "[yellow]Database is on MotherDuck "
            "— use the MotherDuck UI to manage it.[/yellow]"
        )
        raise typer.Exit(code=1)

    db_file = Path(db.db_path())
    if not db_file.exists():
        console.print("[dim]No database to delete.[/dim]")
        return

    if not yes:
        size_kb = db_file.stat().st_size / 1024
        if not typer.confirm(f"Delete {db_file} ({size_kb:.0f} KB)?"):
            raise typer.Abort()

    db.reset()
    db_file.unlink()
    console.print(f"[green]Deleted {db_file.name}[/green]")


# ---------------------------------------------------------------------------
# cass backup / cass restore
# ---------------------------------------------------------------------------


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
    from ..config import get_config

    project_root = get_config().root
    backups_dir = project_root / "backups"

    if list_backups:
        if not backups_dir.exists():
            console.print("[dim]No backups directory.[/dim]")
            return
        files = sorted(backups_dir.glob("cass_*.duckdb"))
        if not files:
            console.print("[dim]No backups found.[/dim]")
            return
        for f in files:
            size_kb = f.stat().st_size / 1024
            console.print(f"  {f.name}  [dim]({size_kb:.0f} KB)[/dim]")
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_{tag}" if tag else ""
    dest = backups_dir / f"cass_{stamp}{suffix}.duckdb"

    if db.is_remote():
        # Snapshot MotherDuck to a local file via hybrid attach
        backups_dir.mkdir(exist_ok=True)
        ensure_backups_gitignored(project_root)
        conn = db.get_db()
        conn.execute(f"ATTACH '{dest}' AS _backup")
        for (name,) in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall():
            conn.execute(f"CREATE TABLE _backup.{name} AS SELECT * FROM main.{name}")
        conn.execute("DETACH _backup")
    else:
        db_file = Path(db.db_path())
        if not db_file.exists():
            console.print(
                "[yellow]No database to back up. "
                "Run [bold]cass pull[/bold] first.[/yellow]"
            )
            raise typer.Exit(code=1)

        backups_dir.mkdir(exist_ok=True)
        ensure_backups_gitignored(project_root)
        db.reset()
        shutil.copy2(str(db_file), str(dest))

    size_kb = dest.stat().st_size / 1024
    console.print(
        f"[green]Backed up → "
        f"{dest.relative_to(project_root)} ({size_kb:.0f} KB)[/green]"
    )


@app.command()
def restore(
    file: str = typer.Argument(..., help="Path to a .duckdb backup file"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Replace the current database with a backup file."""
    import shutil

    import duckdb as _duckdb

    from .. import db

    src = Path(file)
    if not src.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)
    if src.suffix != ".duckdb":
        console.print("[red]Expected a .duckdb file.[/red]")
        raise typer.Exit(code=1)

    # Validate the backup
    try:
        backup_conn = _duckdb.connect(str(src), read_only=True)
        row = backup_conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        version = int(row[0]) if row else 0
        counts: dict[str, int] = {}
        for tbl in ("students", "assignments"):
            try:
                r = backup_conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
                counts[tbl] = r[0] if r else 0
            except Exception:
                counts[tbl] = 0
        backup_conn.close()
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
    if db.is_remote():
        console.print(f"  Current DB: [bold]{target}[/bold] (MotherDuck)")
    else:
        db_file = Path(target)
        if db_file.exists():
            cur_kb = db_file.stat().st_size / 1024
            console.print(f"  Current DB: {db_file.name} ({cur_kb:.0f} KB)")
        else:
            console.print("  Current DB: [dim]none[/dim]")

    if not yes and not typer.confirm("\nReplace current database with this backup?"):
        raise typer.Abort()

    if db.is_remote():
        # Restore into MotherDuck via hybrid attach
        conn = db.get_db()
        conn.execute(f"ATTACH '{src}' AS _restore (READ_ONLY)")
        # Drop and recreate each table from the backup
        for (name,) in conn.execute(
            "SELECT table_name FROM _restore.information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall():
            conn.execute(f"DROP TABLE IF EXISTS main.{name}")
            conn.execute(
                f"CREATE TABLE main.{name} AS SELECT * FROM _restore.main.{name}"
            )
        conn.execute("DETACH _restore")
        console.print(f"[green]Restored {src.name} → {target}[/green]")
    else:
        db.reset()
        shutil.copy2(str(src), str(Path(target)))
        console.print(f"[green]Restored {src.name} → {Path(target).name}[/green]")


# ---------------------------------------------------------------------------
# cass query
# ---------------------------------------------------------------------------


def run_repl() -> None:
    import shutil
    import subprocess

    from .. import db
    from . import report

    db_file = db.db_path()
    tables = (
        "students, assignments, gh_students, canvas_students, "
        "gh_assignments, canvas_assignments, gh_submissions, "
        "canvas_submissions, gh_grades, canvas_grades"
    )

    if shutil.which("duckdb"):
        console.print(f"[bold]cass DuckDB REPL[/bold] — {db_file}")
        console.print(f"Tables: {tables}")

        console.print("Type .quit to exit\n")
        subprocess.run(["duckdb", db_file])
        return

    console.print(f"[bold]cass DuckDB REPL[/bold] — {db_file}")
    console.print(f"Tables: {tables}")
    console.print("Views: v_submissions, v_grades")
    console.print("Type .quit to exit\n")
    while True:
        try:
            line = input("D> ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        line = line.strip()
        if not line:
            continue
        if line.lower() in (".quit", ".exit", "quit", "exit"):
            break
        if line.lower() == ".tables":
            line = "SHOW TABLES"
        try:
            result = db.run_query(line)
            report.render_table(result)
        except Exception as e:
            console.print(f"[red]{e}[/red]")


@app.command()
def query(
    sql: str = typer.Argument(
        "", help="SQL query to execute (empty for interactive REPL)"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export results as CSV file"),
) -> None:
    """Run a DuckDB SQL query against the project database."""
    from .. import db
    from . import report

    if not sql:
        run_repl()
        return

    result = db.run_query(sql)
    if csv_out:
        report.write_csv_file(csv_out, relation=result)
    else:
        report.render_table(result)


_VALID_TABLES = (
    "students",
    "assignments",
    "gh_students",
    "canvas_students",
    "gh_assignments",
    "canvas_assignments",
    "gh_submissions",
    "canvas_submissions",
    "gh_grades",
    "canvas_grades",
)


@app.command(name="export")
def export_table(
    table: str = typer.Argument(
        ...,
        help="Table to export (students, assignments, gh_grades, canvas_grades, etc.)",
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    markdown_out: str = typer.Option(
        "", "--markdown", "--md", help="Export as markdown file"
    ),
) -> None:
    """Export a database table to CSV or markdown."""
    from .. import db
    from . import report

    if table not in _VALID_TABLES:
        console.print(
            f"[red]Unknown table '{table}'. "
            f"Choose from: {', '.join(_VALID_TABLES)}[/red]"
        )
        raise typer.Exit(code=1)

    conn = db.get_db()
    result = conn.sql(f"SELECT * FROM {table} ORDER BY 1")

    if csv_out:
        report.write_csv_file(csv_out, relation=result)
    elif markdown_out:
        report.save_relation_markdown(markdown_out, table.title(), result)
    else:
        report.write_csv_file(f"{table}.csv", relation=result)


@app.command()
def egrades(
    output: str = typer.Option("egrades.csv", "--output", "-o", help="Output CSV path"),
) -> None:
    """Export eGrades CSV for UCSD final grade submission.

    Fetches computed final scores from Canvas enrollments, applies the course
    grading scheme to convert to letter grades, and writes the 5-column CSV
    (Last Name, First Name, Student ID, SectionId, Final_Assigned_Egrade).
    """
    from ..canvas.egrades import generate_egrades

    require_canvas()

    try:
        path, count, warnings = generate_egrades(output)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    for w in warnings:
        console.print(f"[yellow]  ⚠ {w}[/yellow]")

    console.print(f"\n[green]Wrote {count} student grades to {path}[/green]")


@app.command(name="import")
def import_csv(
    file: str = typer.Argument(..., help="CSV file to import"),
    table: str = typer.Option(
        "", "--table", help="Target table (auto-detected from headers if omitted)"
    ),
) -> None:
    """Import a CSV file into the database."""
    import csv as csv_mod

    from .. import db

    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)

    with open(path, newline="") as f:
        reader = csv_mod.DictReader(f)
        if reader.fieldnames is None:
            console.print("[red]CSV file has no headers.[/red]")
            raise typer.Exit(code=1)
        headers = set(reader.fieldnames)
        rows = list(reader)

    if not rows:
        console.print("[yellow]CSV file is empty.[/yellow]")
        return

    if not table:
        _TABLE_SIGNATURES = {
            "students": {"canvas_id", "name"},
            "canvas_grades": {"canvas_user_id", "canvas_assignment_id"},
            "gh_grades": {"github_username", "assignment_slug", "grade"},
            "gh_submissions": {"github_username", "assignment_slug", "submitted"},
            "canvas_submissions": {
                "canvas_user_id",
                "canvas_assignment_id",
                "submitted",
            },
            "assignments": {"slug", "title"},
        }
        for tbl, required in _TABLE_SIGNATURES.items():
            if required.issubset(headers):
                table = tbl
                break
        if not table:
            console.print("[red]Cannot auto-detect table. Use --table flag.[/red]")
            raise typer.Exit(code=1)

    if table not in _VALID_TABLES:
        console.print(
            f"[red]Unknown table '{table}'. "
            f"Choose from: {', '.join(_VALID_TABLES)}[/red]"
        )
        raise typer.Exit(code=1)

    conn = db.get_db()
    table_cols = [col[0] for col in conn.execute(f"DESCRIBE {table}").fetchall()]
    import_cols = [c for c in table_cols if c in headers]

    if not import_cols:
        console.print("[red]No matching columns between CSV and table.[/red]")
        raise typer.Exit(code=1)

    placeholders = ", ".join("?" for _ in import_cols)
    col_names = ", ".join(import_cols)
    insert_sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"

    for row in rows:
        values = [row.get(c, "") for c in import_cols]
        conn.execute(insert_sql, values)

    console.print(f"[green]Imported {len(rows)} rows into {table}.[/green]")


@app.command()
def view(
    port: int = typer.Option(0, "--port", help="Port number (0 = auto-select)"),
) -> None:
    """Open the database in a browser-based viewer."""
    from .. import db

    if not db.is_remote():
        db_file = Path(db.db_path())
        if not db_file.exists():
            console.print(
                "[yellow]No database yet. Run [bold]cass pull[/bold] first.[/yellow]"
            )
            raise typer.Exit(code=1)

    from ..viewer.nicegui_app import start_nicegui_server

    start_nicegui_server(port=port)


@db_app.callback()
def db_callback(ctx: typer.Context) -> None:
    """Open an interactive DuckDB REPL against the project database."""
    if ctx.invoked_subcommand is None:
        run_repl()


@db_app.command()
def clean() -> None:
    """Clear API cache to keep the shared DB lean for git commits."""
    from .. import cache

    count = cache.cache_count()
    cache.cache_clear()
    console.print(f"[green]Cleared {count} cache entries.[/green]")
