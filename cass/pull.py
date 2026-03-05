"""Pull orchestration — fetch APIs → populate DuckDB.

GitHub API calls use async httpx with parallel per-student fetching.
Canvas calls remain synchronous (fewer calls, not the bottleneck).
"""

from __future__ import annotations

import typer
from rich.console import Console

from . import canvas as canvas_mod
from . import classroom, db
from . import fetch as fetch_mod
from .config import Config
from .github_client import GitHubClient
from .models import Student, compute_grade

# Course-specific constants for final project handling
FINAL_PROJECT_SLUG = "final-project"
PROPOSAL_FILE = "pdfs/proposal.pdf"
REPORT_FILE = "pdfs/final-report.pdf"


async def pull_students(
    client: GitHubClient | None,
    cfg: Config,
    console: Console,
    ttl: float,
    no_cache: bool,
) -> None:
    """Fetch students from GitHub Classroom and/or Canvas."""
    students_list: list[Student] = []
    if cfg.has_classroom:
        assert client is not None
        console.print("[bold]Pulling students from GitHub Classroom...[/bold]")
        gh_students = await classroom.fetch_all_students(
            client, ttl_hours=ttl, force_refresh=no_cache
        )
        console.print(f"  Found {len(gh_students)} via GitHub")

        canvas_mapping: dict[str, int] = {}
        if cfg.has_canvas:
            console.print("  Fetching Canvas enrollment...")
            canvas_students = canvas_mod.fetch_students(cfg.canvas_course_id)
            console.print(f"  Found {len(canvas_students)} on Canvas")
            result = canvas_mod.match_students(gh_students, canvas_students)
            canvas_mapping = result.matched
            console.print(f"  Auto-matched {len(canvas_mapping)}/{len(gh_students)}")

            # Interactive resolution
            if result.unmatched_gh and result.unmatched_canvas:
                console.print(
                    f"\n  [yellow]{len(result.unmatched_gh)} unmatched GitHub student(s)[/yellow]"
                )
                unmatched_canvas = list(result.unmatched_canvas)
                for gh_s in result.unmatched_gh:
                    gh_name = gh_s.name or gh_s.login
                    console.print(f"\n    [bold]{gh_name}[/bold] ({gh_s.login})")
                    candidates = canvas_mod.find_candidates(gh_s, unmatched_canvas)
                    if not candidates:
                        console.print("      No Canvas candidates found — skipping")
                        continue
                    for i, c in enumerate(candidates[:5], 1):
                        console.print(f"      {i}) {c.name}  ({c.email or 'no email'})")
                    console.print("      0) Skip")
                    choice = typer.prompt("      Select", default="0")
                    try:
                        idx = int(choice)
                        if 1 <= idx <= len(candidates[:5]):
                            c = candidates[idx - 1]
                            canvas_mapping[gh_s.login] = c.id
                            unmatched_canvas = [
                                uc for uc in unmatched_canvas if uc.id != c.id
                            ]
                    except ValueError:
                        pass

        for gh_s in gh_students:
            cid = canvas_mapping.get(gh_s.login, "")
            identifier = gh_s.name if gh_s.name else gh_s.login
            students_list.append(
                Student(
                    identifier=identifier,
                    github_username=gh_s.login,
                    github_id=gh_s.id,
                    name=gh_s.name,
                    canvas_id=str(cid) if cid else "",
                )
            )

    elif cfg.has_canvas:
        console.print("[bold]Pulling students from Canvas...[/bold]")
        canvas_students = canvas_mod.fetch_students(cfg.canvas_course_id)
        students_list = [
            Student(
                identifier=cs.name,
                name=cs.name,
                canvas_id=str(cs.id),
            )
            for cs in canvas_students
        ]
        console.print(f"  Found {len(students_list)} students")

    if students_list:
        db.save_students(students_list)
        matched = sum(1 for s in students_list if s.canvas_id)
        console.print(
            f"  [green]Saved {len(students_list)} students ({matched} with Canvas IDs)[/green]"
        )


async def pull_assignments(
    client: GitHubClient | None,
    cfg: Config,
    console: Console,
    ttl: float,
    no_cache: bool,
) -> None:
    """Fetch assignments from GitHub Classroom and/or Canvas."""
    all_assignments = []
    if cfg.has_classroom:
        assert client is not None
        console.print("[bold]Pulling assignments from GitHub Classroom...[/bold]")
        gh_assignments = await classroom.fetch_assignments(
            client, ttl_hours=ttl, force_refresh=no_cache
        )
        all_assignments.extend(gh_assignments)
        console.print(f"  Found {len(gh_assignments)} GitHub assignments")

    if cfg.has_canvas:
        console.print("[bold]Pulling assignments from Canvas...[/bold]")
        canvas_assignments = canvas_mod.fetch_assignments(cfg.canvas_course_id)
        all_assignments.extend(canvas_assignments)
        console.print(f"  Found {len(canvas_assignments)} Canvas assignments")

    if all_assignments:
        db.save_assignments(all_assignments)
        console.print(f"  [green]Saved {len(all_assignments)} assignments[/green]")


async def pull_submissions(
    client: GitHubClient | None,
    cfg: Config,
    console: Console,
    ttl: float,
    no_cache: bool,
) -> None:
    """Fetch submissions for all assignments.

    GitHub submissions are fetched with parallel per-student commit checks.
    """
    if not db.students_exist():
        console.print("[yellow]No roster. Pull students first.[/yellow]")
        return

    students = db.load_students()
    assignments = db.load_assignments()
    if not assignments:
        console.print("[yellow]No assignments. Pull assignments first.[/yellow]")
        return

    all_subs = []

    # GitHub submissions — async with parallel per-student checks
    gh_assignments = [a for a in assignments if a.source == "github"]
    if gh_assignments and cfg.has_classroom and client is not None:
        for i, a in enumerate(gh_assignments, 1):
            console.print(f"  Fetching submissions… ({i}/{len(gh_assignments)} {a.id})")
            if a.slug == FINAL_PROJECT_SLUG:
                for phase_name, file_path in [
                    ("proposal", PROPOSAL_FILE),
                    ("report", REPORT_FILE),
                ]:
                    subs = await classroom.fetch_file_submissions(
                        client,
                        a,
                        students,
                        file_path,
                        ttl_hours=ttl,
                        force_refresh=no_cache,
                    )
                    for s in subs:
                        all_subs.append(s.with_assignment_id(phase_name))
                continue
            subs = await classroom.fetch_submissions(
                client, a, students, ttl_hours=ttl, force_refresh=no_cache
            )
            all_subs.extend(subs)

    # Canvas submissions — sync (single paginated call per assignment)
    canvas_assignments = [
        a for a in assignments if a.source == "canvas" and a.canvas_id
    ]
    if canvas_assignments and cfg.has_canvas:
        for a in canvas_assignments:
            subs = canvas_mod.fetch_submissions(
                cfg.canvas_course_id, a.canvas_id, students
            )
            for s in subs:
                all_subs.append(s.with_assignment_id(a.id))

    if all_subs:
        db.save_submissions(all_subs)
        console.print(f"  [green]Saved {len(all_subs)} submissions[/green]")


def pull_grades(console: Console) -> None:
    """Compute grades from submissions."""
    assignments = db.load_assignments()
    all_submissions = db.load_submissions()
    if not all_submissions:
        console.print("[yellow]No submissions. Pull submissions first.[/yellow]")
        return

    assign_map = {a.id: a for a in assignments}
    grades = []
    for sub in all_submissions:
        assign = assign_map.get(sub.assignment_id)
        if assign:
            grades.append(compute_grade(sub, assign))
    if grades:
        db.save_grades(grades)
        console.print(f"  [green]Computed {len(grades)} grades[/green]")


def pull_fetch(console: Console, ttl: float, no_cache: bool, limit: int) -> None:
    """Download student files from GitHub repos."""
    students = db.load_students()
    assignments = db.load_assignments()
    gh_assignments = [a for a in assignments if a.source == "github"]
    for a in gh_assignments:
        console.print(f"\n[bold]{a.slug}[/bold]")
        fetch_mod.fetch_assignment(
            a,
            students,
            limit=limit,
            ttl_hours=ttl,
            force_refresh=no_cache,
        )
