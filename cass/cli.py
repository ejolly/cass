"""Typer CLI for cass — classroom assignment grading toolkit."""

from __future__ import annotations

__docformat__ = "google"

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from .cli_canvas import canvas_app

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
)
grades_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Gradebook matrix and grade sync to Canvas.",
)
app.add_typer(grades_app, name="grades", rich_help_panel="View Data")
db_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Interactive DuckDB REPL and cache management.",
)
app.add_typer(db_app, name="db", rich_help_panel="Database")
app.add_typer(canvas_app, name="canvas", rich_help_panel="Canvas LMS")

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
    # Default to status when no subcommand given
    if ctx.invoked_subcommand is None:
        _status()


def _require_classroom() -> None:
    from .config import get_config

    cfg = get_config()
    if not cfg.has_classroom:
        console.print(
            "[red]This command requires GitHub Classroom configuration.[/red]"
        )
        console.print("Add a \\[classroom] section to cass.toml.")
        raise typer.Exit(code=1)


def _require_canvas() -> None:
    from .config import get_config

    cfg = get_config()
    if not cfg.has_canvas:
        console.print("[red]This command requires Canvas configuration.[/red]")
        console.print("Add a \\[canvas] section to cass.toml.")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# cass status — project dashboard (default command)
# ---------------------------------------------------------------------------


def _status() -> None:
    """Show project overview with command guide."""
    from rich.panel import Panel

    from . import db
    from .config import config_file_path, get_config

    cfg_path = config_file_path()
    if not cfg_path:
        console.print()
        console.print(
            "[yellow]No cass.toml found.[/yellow] Run [bold]cass init[/bold] to get started."
        )
        console.print()
        return

    cfg = get_config()

    # Build status lines for the panel
    lines: list[str] = []
    lines.append(f"  [dim]Config[/dim]      {cfg_path.name}")

    if cfg.has_classroom:
        lines.append(
            f"  [dim]GitHub[/dim]      {cfg.org} [dim](classroom {cfg.classroom_id})[/dim]"
        )

    if cfg.has_canvas:
        host = cfg.canvas_base_url.replace("https://", "").replace("http://", "")
        lines.append(
            f"  [dim]Canvas[/dim]      {host} [dim](course {cfg.canvas_course_id})[/dim]"
        )

    # DB stats
    db_file = Path(db.db_path())
    if db_file.exists():
        size_kb = db_file.stat().st_size / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        db_parts = [size_str]
        try:
            if db.students_exist():
                students = db.load_students()
                db_parts.append(f"{len(students)} students")
            assignments = db.load_assignments()
            if assignments:
                db_parts.append(f"{len(assignments)} assignments")
        except Exception:
            pass
        lines.append(
            f"  [dim]Database[/dim]    {db_file.name} [dim]({' · '.join(db_parts)})[/dim]"
        )
    else:
        lines.append("  [dim]Database[/dim]    [italic]not yet created[/italic]")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold]cass[/bold] [dim]v{__version__}[/dim]",
        title_align="left",
        border_style="blue",
        padding=(1, 1),
    )
    console.print()
    console.print(panel)

    # Command guide
    _print_guide(
        "Common commands",
        [
            ("cass pull", "Fetch data from APIs"),
            ("cass students", "Student roster"),
            ("cass grades", "Gradebook matrix"),
        ],
    )
    if cfg.has_canvas:
        _print_guide(
            "Canvas",
            [("cass canvas", "Course overview & management")],
        )
    _print_guide(
        "More",
        [("cass --help", "All commands and options")],
    )
    console.print()


def _print_guide(heading: str, commands: list[tuple[str, str]]) -> None:
    """Print a section of the command guide."""
    console.print(f"\n  [bold]{heading}[/bold]")
    for cmd, desc in commands:
        console.print(f"    [green]{cmd:<24s}[/green] [dim]{desc}[/dim]")


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


@app.command(rich_help_panel="Setup")
def init() -> None:
    """Initialize a new project or check an existing setup."""
    from . import canvas
    from .config import (
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
                    canvas.save_token(token)
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

    # Config exists — run checks
    console.print("[bold]Checking setup...[/bold]\n")
    checks = check_prerequisites()
    all_ok = True
    for c in checks:
        indent = "  " * c.indent
        icon = "[green]✓[/green]" if c.ok else "[red]✗[/red]"
        console.print(f"  {indent}{icon} {c.name}  [dim]{c.detail}[/dim]")
        if not c.ok:
            all_ok = False

    console.print()
    if all_ok:
        console.print("[green]All checks passed![/green]")
    else:
        console.print("Fix the issues above and run [bold]cass init[/bold] again.")


# ---------------------------------------------------------------------------
# cass pull — fetch APIs → populate DuckDB
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Setup")
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
    """Fetch from APIs and update the local database.

    Pipeline order: students → assignments → submissions → grades.
    Use flags to run individual phases.
    """
    import asyncio

    from . import pull as pull_mod
    from .config import get_config
    from .github_client import GitHubClient

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
        _require_classroom()
        pull_mod.pull_fetch(console, state.ttl, state.no_cache, limit)


# ---------------------------------------------------------------------------
# cass students
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="View Data")
def students(
    all_students: bool = typer.Option(
        False, "--all", help="Show all students including excluded"
    ),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option(
        "", "--where", help="SQL WHERE filter (e.g. --where \"source='github'\")"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """Show the student roster."""
    from . import db, report

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
        f"SELECT identifier, github_username, github_id, name, email, canvas_id"
        f"{', excluded' if all_students else ''} "
        f"FROM students {where_clause} ORDER BY lower(identifier)"
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


@app.command(rich_help_panel="View Data")
def assignments(
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option(
        "", "--where", help="SQL WHERE filter (e.g. --where \"source='github'\")"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """Show assignment metadata."""
    from . import db, report

    conn = db.get_db()
    where_clause = f"WHERE {where}" if where else ""
    result = conn.sql(
        f"SELECT id, source, title, deadline, points_possible, accepted "
        f"FROM assignments {where_clause} ORDER BY id"
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


@app.command(rich_help_panel="View Data")
def submissions(
    slug: str = typer.Argument("", help="Assignment slug to filter (or empty for all)"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    where: str = typer.Option(
        "", "--where", help="SQL WHERE filter (e.g. --where \"source='github'\")"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """View submission status (student, assignment, on-time, late, score)."""
    from . import db, report

    conn = db.get_db()
    conditions = []
    if slug:
        conditions.append(f"assignment_id LIKE '%{slug}%'")
    if where:
        conditions.append(f"({where})")
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = conn.sql(
        f"SELECT student_id, assignment_id, source, submitted, late, "
        f"lateness_seconds, repo_name, commits_after_deadline, score, workflow_state "
        f"FROM submissions {where_clause} ORDER BY assignment_id, student_id"
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
    where: str = typer.Option(
        "", "--where", help="SQL WHERE filter (e.g. --where \"source='github'\")"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
) -> None:
    """Show the gradebook as a student x assignment matrix with computed grades."""
    if ctx.invoked_subcommand is not None:
        return

    from . import db, report

    grades = db.load_grades()
    if not grades:
        console.print("[yellow]No grades. Run [bold]cass pull[/bold] first.[/yellow]")
        raise typer.Exit(code=1)

    # Build matrix
    students_set: dict[str, None] = {}
    assignments_set: dict[str, None] = {}
    grade_map: dict[tuple[str, str], str] = {}
    for g in grades:
        students_set[g.student_id] = None
        assignments_set[g.assignment_id] = None
        grade_map[(g.student_id, g.assignment_id)] = g.grade

    assignment_ids = sorted(assignments_set)
    student_ids = sorted(students_set)

    # Build display name mapping from DB
    all_students = db.load_students(include_excluded=True)
    id_to_name: dict[str, str] = {}
    for s in all_students:
        if s.handle_lower:
            id_to_name[s.handle_lower] = s.display_name
        id_to_name[s.identifier] = s.display_name

    headers = ["Student"] + assignment_ids
    rows = []
    for sid in student_ids:
        display = id_to_name.get(sid, sid)
        row = [display] + [grade_map.get((sid, aid), "-") for aid in assignment_ids]
        rows.append(row)

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Grades", headers, rows)
    else:
        report.render_list(headers, rows, title="Grades")


@grades_app.command()
def push(
    post: bool = typer.Option(
        False, "--post", help="Actually push grades (default: dry-run)"
    ),
) -> None:
    """Sync grades to Canvas LMS (dry-run by default, use --post to submit)."""
    from . import canvas as canvas_mod
    from . import db
    from .config import get_config
    from .models.grading import numeric_grade

    _require_classroom()
    _require_canvas()
    cfg = get_config()

    students = db.load_students()
    assignments = db.load_assignments()
    grades = db.load_grades()

    if not grades:
        console.print("[yellow]No grades to push.[/yellow]")
        raise typer.Exit(code=1)

    # Build mappings
    gh_to_canvas: dict[str, int] = canvas_mod.mapping_from_roster(students)
    grade_map: dict[tuple[str, str], str] = {
        (g.student_id, g.assignment_id): g.grade for g in grades
    }

    # Match GH assignments to Canvas assignments by token overlap
    gh_assignments = [a for a in assignments if a.source == "github"]
    canvas_assignments = [a for a in assignments if a.source == "canvas"]

    from rich.table import Table

    table = Table(title="Grade Sync Preview", show_edge=False, pad_edge=False)
    table.add_column("GH Assignment")
    table.add_column("Canvas Assignment")
    table.add_column("Canvas ID", justify="right")
    table.add_column("Grades")

    matched_pairs: list[tuple] = []
    for gh_a in gh_assignments:
        # Find best Canvas match by token overlap
        gh_tokens = set(gh_a.id.replace("-", " ").split())
        best_match = None
        best_overlap = 0
        for cv_a in canvas_assignments:
            cv_tokens = set(cv_a.id.replace("-", " ").split())
            overlap = len(gh_tokens & cv_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = cv_a

        if best_match and best_overlap > 0:
            grade_count = sum(
                1 for s in students if (s.handle_lower, gh_a.id) in grade_map
            )
            table.add_row(
                gh_a.id, best_match.id, str(best_match.canvas_id), str(grade_count)
            )
            matched_pairs.append((gh_a, best_match))

    console.print()
    console.print(table)
    console.print()

    if not post:
        console.print(
            "[yellow]Dry run — no grades posted. Use --post to push to Canvas.[/yellow]"
        )
        return

    total_posted = 0
    total_skipped = 0
    failed: list[str] = []
    for gh_a, cv_a in matched_pairs:
        for student in students:
            grade_str = grade_map.get((student.handle_lower, gh_a.id))
            if not grade_str:
                total_skipped += 1
                continue

            numeric = numeric_grade(grade_str)
            if numeric is None:
                total_skipped += 1
                continue

            canvas_id = gh_to_canvas.get(student.github_username)
            if not canvas_id:
                total_skipped += 1
                continue

            ok = canvas_mod.push_grade(
                cfg.canvas_course_id, cv_a.canvas_id, canvas_id, str(int(numeric))
            )
            if ok:
                total_posted += 1
            else:
                failed.append(f"{student.identifier} / {gh_a.id}")

    if failed:
        console.print(f"[red]Failed to post {len(failed)} grade(s):[/red]")
        for entry in failed:
            console.print(f"  [red]• {entry}[/red]")
    console.print(
        f"[green]Posted {total_posted} grades, skipped {total_skipped}.[/green]"
    )


# ---------------------------------------------------------------------------
# cass fetch SLUG
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Setup")
def fetch(
    slug: str = typer.Argument(..., help="Assignment slug (or 'all')"),
    force: bool = typer.Option(False, "--force", help="Re-download existing files"),
    limit: int = typer.Option(0, "--limit", help="Limit number of students (0 = all)"),
) -> None:
    """Download student submission files."""
    from . import db
    from . import fetch as fetch_mod

    _require_classroom()
    students = db.load_students()
    assignments = db.load_assignments()
    gh_assignments = [a for a in assignments if a.source == "github"]

    if slug == "all":
        targets = gh_assignments
    else:
        targets = [a for a in gh_assignments if slug in a.slug]
        if not targets:
            console.print(f"[red]No assignment matching '{slug}'[/red]")
            raise typer.Exit(code=1)

    for target in targets:
        console.print(f"\n[bold]{target.slug}[/bold]")
        fetch_mod.fetch_assignment(
            target,
            students,
            force=force,
            limit=limit,
            ttl_hours=state.ttl,
            force_refresh=state.no_cache,
        )


# ---------------------------------------------------------------------------
# cass drop — wipe the database
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Database")
def drop(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete the local database (cass.db)."""
    from . import db

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
# cass query — raw DuckDB SQL
# ---------------------------------------------------------------------------


def _run_repl() -> None:
    """Launch interactive DuckDB REPL (CLI binary or Python fallback)."""
    import shutil
    import subprocess

    from . import db, report

    db_file = db.db_path()

    # Prefer the native duckdb CLI if available
    if shutil.which("duckdb"):
        console.print(f"[bold]cass DuckDB REPL[/bold] — {db_file}")
        console.print("Tables: students, assignments, submissions, grades, api_cache")
        console.print("Type .quit to exit\n")
        subprocess.run(["duckdb", db_file])
        return

    # Python-based fallback
    console.print(f"[bold]cass DuckDB REPL[/bold] — {db_file}")
    console.print("Tables: students, assignments, submissions, grades, api_cache")
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


@app.command(rich_help_panel="Database")
def query(
    sql: str = typer.Argument(
        "", help="SQL query to execute (empty for interactive REPL)"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export results as CSV file"),
) -> None:
    """Run a DuckDB SQL query against the project database."""
    from . import db, report

    if not sql:
        _run_repl()
        return

    result = db.run_query(sql)
    if csv_out:
        report.write_csv_file(csv_out, relation=result)
    else:
        report.render_table(result)


_VALID_TABLES = ("students", "assignments", "submissions", "grades")


@app.command(name="export", rich_help_panel="Database")
def export_table(
    table: str = typer.Argument(
        ..., help="Table to export (students, assignments, submissions, grades)"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    markdown_out: str = typer.Option(
        "", "--markdown", "--md", help="Export as markdown file"
    ),
) -> None:
    """Export a database table to CSV or markdown."""
    from . import db, report

    if table not in _VALID_TABLES:
        console.print(
            f"[red]Unknown table '{table}'. Choose from: {', '.join(_VALID_TABLES)}[/red]"
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


@app.command(name="import", rich_help_panel="Database")
def import_csv(
    file: str = typer.Argument(..., help="CSV file to import"),
    table: str = typer.Option(
        "", "--table", help="Target table (auto-detected from headers if omitted)"
    ),
) -> None:
    """Import a CSV file into the database."""
    import csv as csv_mod

    from . import db

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

    # Auto-detect table from column headers
    if not table:
        _TABLE_SIGNATURES = {
            "students": {"identifier"},
            "grades": {"student_id", "assignment_id", "grade"},
            "submissions": {"student_id", "assignment_id", "source", "submitted"},
            "assignments": {"id", "source", "title"},
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
            f"[red]Unknown table '{table}'. Choose from: {', '.join(_VALID_TABLES)}[/red]"
        )
        raise typer.Exit(code=1)

    conn = db.get_db()
    # Get table columns from schema
    table_cols = [col[0] for col in conn.execute(f"DESCRIBE {table}").fetchall()]
    # Only use columns present in both CSV and table
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


@app.command(rich_help_panel="Database")
def view() -> None:
    """Open the database in Dataflare (GUI viewer)."""
    import subprocess

    from . import db

    db_file = Path(db.db_path())
    if not db_file.exists():
        console.print(
            "[yellow]No database yet. Run [bold]cass pull[/bold] first.[/yellow]"
        )
        raise typer.Exit(code=1)

    # Check if Dataflare is installed
    result = subprocess.run(
        ["open", "-Ra", "Dataflare"], capture_output=True, text=True
    )
    if result.returncode != 0:
        console.print("[red]Dataflare is not installed.[/red]")
        console.print("Install it with: [bold]brew install --cask dataflare[/bold]")
        console.print("Or download from: https://dataflare.app/")
        raise typer.Exit(code=1)

    console.print(f"Opening [bold]{db_file.name}[/bold] in Dataflare...")
    subprocess.run(["open", "-a", "Dataflare", str(db_file.resolve())])


@db_app.callback()
def db_callback(ctx: typer.Context) -> None:
    """Open an interactive DuckDB REPL against the project database."""
    if ctx.invoked_subcommand is None:
        _run_repl()


@db_app.command()
def clean() -> None:
    """Drop api_cache contents to shrink the .db for git commits."""
    from . import db

    count = db.cache_count()
    db.cache_clear()
    console.print(f"[green]Cleared {count} cache entries.[/green]")
