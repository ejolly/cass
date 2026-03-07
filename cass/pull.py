"""Pull orchestration — fetch APIs, populate source tables, merge to master tables.

GitHub API calls use async httpx with parallel per-student fetching.
Canvas calls remain synchronous (fewer calls, not the bottleneck).
"""

from __future__ import annotations

__docformat__ = "google"

import typing

import typer
from rich.console import Console

from . import db
from .canvas import matching as matching_mod
from .config import Config
from .github import classroom
from .github.client import GitHubClient
from .models import (
    Assignment,
    CanvasAssignment,
    CanvasGrade,
    CanvasSubmission,
    GHAssignment,
    GHGrade,
    GHSubmission,
    Student,
)

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
    """Fetch students from Canvas (authoritative) and optionally GitHub Classroom.

    Canvas students are the source of truth. GitHub students are matched to
    Canvas students by name. Previous matches are preserved across repulls.
    """
    # Step 1: Canvas students (always — Canvas is required)
    console.print("[bold]Pulling students from Canvas...[/bold]")
    canvas_students, sis_section_map = matching_mod.fetch_students_with_sections(
        cfg.canvas_course_id
    )
    db.save_canvas_students(canvas_students, sis_section_map=sis_section_map)
    console.print(f"  Found {len(canvas_students)} Canvas students")

    # Step 2: Create/update master students from Canvas (authoritative)
    master_students = [
        Student(canvas_id=cs.id, name=cs.name, email=cs.email) for cs in canvas_students
    ]
    db.upsert_students(master_students)

    # Step 3: GitHub Classroom students (if configured)
    if cfg.has_classroom and client is not None:
        console.print("[bold]Pulling students from GitHub Classroom...[/bold]")
        gh_students = await classroom.fetch_all_students(
            client, ttl_hours=ttl, force_refresh=no_cache
        )
        db.save_gh_students(gh_students)
        console.print(f"  Found {len(gh_students)} GitHub students")

        # Load existing master students to check for previous mappings
        existing = db.load_students(include_excluded=True)
        already_mapped = {s.github_username for s in existing if s.github_username}

        # Auto-match by name (only for unmapped GH students)
        unmapped_gh = [g for g in gh_students if g.login.lower() not in already_mapped]
        if unmapped_gh:
            result = matching_mod.match_students(unmapped_gh, canvas_students)
            # Apply auto-matches
            for gh_login, canvas_id in result.matched.items():
                db.update_student_github(canvas_id, gh_login)
            if result.matched:
                console.print(f"  Auto-matched {len(result.matched)} new student(s)")

            # Interactive resolution for remaining unmatched
            if result.unmatched_gh and result.unmatched_canvas:
                console.print(
                    f"\n  [yellow]{len(result.unmatched_gh)} "
                    "unmatched GitHub student(s)[/yellow]"
                )
                unmatched_canvas = list(result.unmatched_canvas)
                for gh_s in result.unmatched_gh:
                    gh_name = gh_s.name or gh_s.login
                    console.print(f"\n    [bold]{gh_name}[/bold] ({gh_s.login})")
                    candidates = matching_mod.find_candidates(gh_s, unmatched_canvas)
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
                            db.update_student_github(c.id, gh_s.login)
                            unmatched_canvas = [
                                uc for uc in unmatched_canvas if uc.id != c.id
                            ]
                    except ValueError:
                        pass

    # Report final state
    final = db.load_students(include_excluded=True)
    matched = sum(1 for s in final if s.github_username)
    console.print(
        f"  [green]Roster: {len(final)} students ({matched} with GitHub links)[/green]"
    )


async def pull_assignments(
    client: GitHubClient | None,
    cfg: Config,
    console: Console,
    ttl: float,
    no_cache: bool,
) -> None:
    """Fetch assignments from Canvas and/or GitHub Classroom, merge to master table."""
    # Step 1: Canvas assignments (always present)
    console.print("[bold]Pulling assignments from Canvas...[/bold]")
    canvas_assignments, group_names = matching_mod.fetch_canvas_assignments(
        cfg.canvas_course_id
    )
    db.save_canvas_assignments(canvas_assignments, group_names=group_names)
    console.print(f"  Found {len(canvas_assignments)} Canvas assignments")

    # Step 2: GitHub assignments (if configured)
    gh_assignments = []
    if cfg.has_classroom and client is not None:
        console.print("[bold]Pulling assignments from GitHub Classroom...[/bold]")
        gh_assignments = await classroom.fetch_assignments(
            client, ttl_hours=ttl, force_refresh=no_cache
        )
        db.save_gh_assignments(gh_assignments)
        console.print(f"  Found {len(gh_assignments)} GitHub assignments")

    # Step 3: Merge into master assignments table
    # Load existing master to preserve manual mappings
    existing_master = {a.slug: a for a in db.load_assignments()}

    # Build canvas assignment lookup by slug
    from .canvas.matching import slugify

    canvas_by_slug: dict[str, CanvasAssignment] = {}
    for ca in canvas_assignments:
        canvas_by_slug[slugify(ca.name)] = ca

    master: list[Assignment] = []

    # Start from Canvas assignments as the base
    used_gh_slugs: set[str] = set()
    for ca in canvas_assignments:
        slug = slugify(ca.name)

        # Check if there's an existing mapping to preserve
        if slug in existing_master:
            ex = existing_master[slug]
            gh_slug = ex.gh_assignment_slug
            if gh_slug:
                used_gh_slugs.add(gh_slug)
        else:
            # Try to auto-match with GH assignment by slug
            gh_slug = ""
            for ga in gh_assignments:
                if ga.slug not in used_gh_slugs and slug_match(ga.slug, slug):
                    gh_slug = ga.slug
                    used_gh_slugs.add(ga.slug)
                    break

        from datetime import datetime

        deadline = None
        if ca.due_at:
            try:
                deadline = datetime.fromisoformat(ca.due_at)
            except ValueError:
                pass

        master.append(
            Assignment(
                slug=slug,
                title=ca.name,
                gh_assignment_slug=gh_slug,
                canvas_assignment_id=ca.id,
                points_possible=ca.points_possible,
                deadline=deadline,
            )
        )

    # Add GH-only assignments (not matched to any Canvas assignment)
    for ga in gh_assignments:
        if ga.slug not in used_gh_slugs:
            from datetime import datetime

            deadline = None
            if ga.deadline:
                try:
                    deadline = datetime.fromisoformat(ga.deadline)
                except ValueError:
                    pass
            master.append(
                Assignment(
                    slug=ga.slug,
                    title=ga.title,
                    gh_assignment_slug=ga.slug,
                    canvas_assignment_id=0,
                    points_possible=1.0,
                    deadline=deadline,
                )
            )

    db.upsert_assignments(master)
    console.print(f"  [green]Master: {len(master)} assignments[/green]")


def slug_match(gh_slug: str, canvas_slug: str) -> bool:
    """Check if a GH slug matches a Canvas slug by token overlap."""
    gh_tokens = set(gh_slug.replace("-", " ").split())
    cv_tokens = set(canvas_slug.replace("-", " ").split())
    overlap = len(gh_tokens & cv_tokens)
    return overlap > 0 and overlap >= min(len(gh_tokens), len(cv_tokens)) / 2


async def pull_submissions(
    client: GitHubClient | None,
    cfg: Config,
    console: Console,
    ttl: float,
    no_cache: bool,
) -> None:
    """Fetch submissions for all assignments into source tables."""
    if not db.students_exist():
        console.print("[yellow]No roster. Pull students first.[/yellow]")
        return

    students = db.load_students()
    assignments = db.load_assignments()
    if not assignments:
        console.print("[yellow]No assignments. Pull assignments first.[/yellow]")
        return

    # GitHub submissions
    gh_assignments = [a for a in assignments if a.gh_assignment_slug]
    if gh_assignments and cfg.has_classroom and client is not None:
        all_gh_subs: list[GHSubmission] = []
        for i, a in enumerate(gh_assignments, 1):
            console.print(
                f"  Fetching GH submissions... ({i}/{len(gh_assignments)} {a.slug})"
            )
            if a.gh_assignment_slug == FINAL_PROJECT_SLUG:
                for phase_name, file_path in [
                    ("proposal", PROPOSAL_FILE),
                    ("report", REPORT_FILE),
                ]:
                    subs = await classroom.fetch_file_submissions(
                        client,
                        a.gh_assignment_slug,
                        students,
                        file_path,
                        ttl_hours=ttl,
                        force_refresh=no_cache,
                    )
                    for s in subs:
                        all_gh_subs.append(s.with_assignment_slug(phase_name))
                continue
            subs = await classroom.fetch_submissions(
                client,
                a.gh_assignment_slug,
                a.deadline,
                students,
                ttl_hours=ttl,
                force_refresh=no_cache,
            )
            all_gh_subs.extend(subs)
        if all_gh_subs:
            db.save_gh_submissions(all_gh_subs)
            console.print(
                f"  [green]Saved {len(all_gh_subs)} GitHub submissions[/green]"
            )

    # Canvas submissions
    canvas_assignments = [a for a in assignments if a.canvas_assignment_id]
    if canvas_assignments:
        known_ids = {s.canvas_id for s in students}
        all_canvas_subs: list[CanvasSubmission] = []
        for a in canvas_assignments:
            subs = matching_mod.fetch_canvas_submissions(
                cfg.canvas_course_id, a.canvas_assignment_id, known_ids
            )
            all_canvas_subs.extend(subs)
        if all_canvas_subs:
            db.save_canvas_submissions(all_canvas_subs)
            console.print(
                f"  [green]Saved {len(all_canvas_subs)} Canvas submissions[/green]"
            )


def pull_grades(console: Console) -> None:
    """Compute grades from submissions and populate grade tables."""
    from .models import compute_canvas_grade, compute_gh_grade

    assignments = db.load_assignments()

    # GH grades
    gh_subs = db.load_gh_submissions()
    gh_grades: list[GHGrade] = []
    for sub in gh_subs:
        gh_grades.append(compute_gh_grade(sub))
    if gh_grades:
        db.save_gh_grades(gh_grades)
        console.print(f"  [green]Computed {len(gh_grades)} GitHub grades[/green]")

    # Canvas grades from Canvas submissions
    conn = db.get_db()
    canvas_sub_rows = conn.execute(
        "SELECT canvas_user_id, canvas_assignment_id, submitted, submitted_at, "
        "late, lateness_seconds, score, workflow_state FROM canvas_submissions"
    ).fetchall()

    # Build canvas_assignment_id -> points_possible map
    ca_points: dict[int, float] = {}
    for a in assignments:
        if a.canvas_assignment_id:
            ca_points[a.canvas_assignment_id] = a.points_possible

    canvas_grades: list[CanvasGrade] = []
    for r in canvas_sub_rows:
        sub = CanvasSubmission(
            canvas_user_id=r[0],
            canvas_assignment_id=r[1],
            submitted=r[2],
            submitted_at=r[3],
            late=r[4],
            lateness_seconds=r[5],
            score=r[6],
            workflow_state=r[7],
        )
        pts = ca_points.get(sub.canvas_assignment_id, 0.0)
        canvas_grades.append(compute_canvas_grade(sub, pts))

    # Canvas grades from GH grades (mapped through students + assignments)
    if gh_grades:
        students = db.load_students()
        gh_to_canvas_student = {
            s.github_username: s.canvas_id for s in students if s.github_username
        }
        assignment_mapping = db.load_assignment_mappings()

        for g in gh_grades:
            canvas_student_id = gh_to_canvas_student.get(g.github_username)
            canvas_assignment_id = assignment_mapping.get(g.assignment_slug)
            if canvas_student_id and canvas_assignment_id:
                canvas_grades.append(
                    CanvasGrade(
                        canvas_user_id=canvas_student_id,
                        canvas_assignment_id=canvas_assignment_id,
                        score=g.numeric_score,
                        posted_grade=str(int(g.numeric_score))
                        if g.numeric_score is not None
                        else "",
                    )
                )

    if canvas_grades:
        db.save_canvas_grades(canvas_grades)
        console.print(f"  [green]Computed {len(canvas_grades)} Canvas grades[/green]")

    db.snapshot_canvas_synced()


async def pull_all_async(
    cfg: Config,
    on_progress: typing.Callable[[str, str], None] | None = None,
) -> None:
    """Run a full pull (students, assignments, submissions, grades).

    Unlike the CLI ``pull`` command this is non-interactive — unmatched
    GitHub students are silently skipped — and reports progress via an
    optional *on_progress(step_name, detail)* callback instead of a Rich
    console.

    Designed to be called from both CLI and viewer contexts.
    """

    def _report(step: str, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(step, detail)

    # --- course info ---
    course_name = matching_mod.fetch_course_name(cfg.canvas_course_id)
    db.save_meta("course_name", course_name)

    # --- students ---
    _report("students", "Pulling Canvas students...")
    canvas_students, sis_section_map = matching_mod.fetch_students_with_sections(
        cfg.canvas_course_id
    )
    db.save_canvas_students(canvas_students, sis_section_map=sis_section_map)
    master_students = [
        Student(canvas_id=cs.id, name=cs.name, email=cs.email) for cs in canvas_students
    ]
    db.upsert_students(master_students)
    _report("students", f"{len(canvas_students)} Canvas students")

    client: GitHubClient | None = None
    try:
        if cfg.has_classroom:
            client = GitHubClient()
            _report("students", "Pulling GitHub Classroom students...")
            gh_students = await classroom.fetch_all_students(
                client, ttl_hours=6.0, force_refresh=False
            )
            db.save_gh_students(gh_students)
            _report("students", f"{len(gh_students)} GitHub students")

            # Auto-match only (no interactive prompts)
            existing = db.load_students(include_excluded=True)
            already_mapped = {s.github_username for s in existing if s.github_username}
            unmapped_gh = [
                g for g in gh_students if g.login.lower() not in already_mapped
            ]
            if unmapped_gh:
                result = matching_mod.match_students(unmapped_gh, canvas_students)
                for gh_login, canvas_id in result.matched.items():
                    db.update_student_github(canvas_id, gh_login)
                if result.matched:
                    _report(
                        "students",
                        f"Auto-matched {len(result.matched)} student(s)",
                    )

        # --- assignments ---
        _report("assignments", "Pulling Canvas assignments...")
        canvas_assignments, group_names = matching_mod.fetch_canvas_assignments(
            cfg.canvas_course_id
        )
        db.save_canvas_assignments(canvas_assignments, group_names=group_names)
        _report("assignments", f"{len(canvas_assignments)} Canvas assignments")

        gh_assignments_list: list[GHAssignment] = []
        if cfg.has_classroom and client is not None:
            _report("assignments", "Pulling GitHub assignments...")
            gh_assignments_list = await classroom.fetch_assignments(
                client, ttl_hours=6.0, force_refresh=False
            )
            db.save_gh_assignments(gh_assignments_list)

        # Merge to master
        from .canvas.matching import slugify

        existing_master = {a.slug: a for a in db.load_assignments()}
        master: list[Assignment] = []
        used_gh_slugs: set[str] = set()

        for ca in canvas_assignments:
            slug = slugify(ca.name)
            if slug in existing_master:
                gh_slug = existing_master[slug].gh_assignment_slug
                if gh_slug:
                    used_gh_slugs.add(gh_slug)
            else:
                gh_slug = ""
                for ga in gh_assignments_list:
                    if ga.slug not in used_gh_slugs and slug_match(ga.slug, slug):
                        gh_slug = ga.slug
                        used_gh_slugs.add(ga.slug)
                        break

            from datetime import datetime

            deadline = None
            if ca.due_at:
                try:
                    deadline = datetime.fromisoformat(ca.due_at)
                except ValueError:
                    pass
            master.append(
                Assignment(
                    slug=slug,
                    title=ca.name,
                    gh_assignment_slug=gh_slug,
                    canvas_assignment_id=ca.id,
                    points_possible=ca.points_possible,
                    deadline=deadline,
                )
            )
        for ga in gh_assignments_list:
            if ga.slug not in used_gh_slugs:
                from datetime import datetime

                deadline = None
                if ga.deadline:
                    try:
                        deadline = datetime.fromisoformat(ga.deadline)
                    except ValueError:
                        pass
                master.append(
                    Assignment(
                        slug=ga.slug,
                        title=ga.title,
                        gh_assignment_slug=ga.slug,
                        canvas_assignment_id=0,
                        points_possible=1.0,
                        deadline=deadline,
                    )
                )
        db.upsert_assignments(master)
        _report("assignments", f"{len(master)} assignments merged")

        # --- submissions ---
        if db.students_exist():
            _report("submissions", "Pulling submissions...")
            students = db.load_students()
            assignments = db.load_assignments()

            gh_assignments = [a for a in assignments if a.gh_assignment_slug]
            if gh_assignments and cfg.has_classroom and client is not None:
                all_gh_subs: list[GHSubmission] = []
                for i, a in enumerate(gh_assignments, 1):
                    _report(
                        "submissions",
                        f"GitHub ({i}/{len(gh_assignments)}) {a.slug}",
                    )
                    if a.gh_assignment_slug == FINAL_PROJECT_SLUG:
                        for phase_name, file_path in [
                            ("proposal", PROPOSAL_FILE),
                            ("report", REPORT_FILE),
                        ]:
                            subs = await classroom.fetch_file_submissions(
                                client,
                                a.gh_assignment_slug,
                                students,
                                file_path,
                                ttl_hours=6.0,
                                force_refresh=False,
                            )
                            for s in subs:
                                all_gh_subs.append(s.with_assignment_slug(phase_name))
                        continue
                    subs = await classroom.fetch_submissions(
                        client,
                        a.gh_assignment_slug,
                        a.deadline,
                        students,
                        ttl_hours=6.0,
                        force_refresh=False,
                    )
                    all_gh_subs.extend(subs)
                if all_gh_subs:
                    db.save_gh_submissions(all_gh_subs)
                    _report("submissions", f"{len(all_gh_subs)} GitHub submissions")

            canvas_assign = [a for a in assignments if a.canvas_assignment_id]
            if canvas_assign:
                known_ids = {s.canvas_id for s in students}
                all_canvas_subs: list[CanvasSubmission] = []
                for a in canvas_assign:
                    subs = matching_mod.fetch_canvas_submissions(
                        cfg.canvas_course_id, a.canvas_assignment_id, known_ids
                    )
                    all_canvas_subs.extend(subs)
                if all_canvas_subs:
                    db.save_canvas_submissions(all_canvas_subs)
                    _report("submissions", f"{len(all_canvas_subs)} Canvas submissions")

        # --- grades ---
        _report("grades", "Computing grades...")
        pull_grades_headless()
        _report("grades", "Done")

    finally:
        if client:
            await client.close()


def pull_grades_headless() -> None:
    """Compute grades without console output (for viewer use)."""
    from .models import compute_canvas_grade, compute_gh_grade

    assignments = db.load_assignments()

    gh_subs = db.load_gh_submissions()
    gh_grades: list[GHGrade] = []
    for sub in gh_subs:
        gh_grades.append(compute_gh_grade(sub))
    if gh_grades:
        db.save_gh_grades(gh_grades)

    conn = db.get_db()
    canvas_sub_rows = conn.execute(
        "SELECT canvas_user_id, canvas_assignment_id, submitted, submitted_at, "
        "late, lateness_seconds, score, workflow_state FROM canvas_submissions"
    ).fetchall()

    ca_points: dict[int, float] = {}
    for a in assignments:
        if a.canvas_assignment_id:
            ca_points[a.canvas_assignment_id] = a.points_possible

    canvas_grades: list[CanvasGrade] = []
    for r in canvas_sub_rows:
        sub = CanvasSubmission(
            canvas_user_id=r[0],
            canvas_assignment_id=r[1],
            submitted=r[2],
            submitted_at=r[3],
            late=r[4],
            lateness_seconds=r[5],
            score=r[6],
            workflow_state=r[7],
        )
        pts = ca_points.get(sub.canvas_assignment_id, 0.0)
        canvas_grades.append(compute_canvas_grade(sub, pts))

    if gh_grades:
        students = db.load_students()
        gh_to_canvas_student = {
            s.github_username: s.canvas_id for s in students if s.github_username
        }
        assignment_mapping = db.load_assignment_mappings()
        for g in gh_grades:
            canvas_student_id = gh_to_canvas_student.get(g.github_username)
            canvas_assignment_id = assignment_mapping.get(g.assignment_slug)
            if canvas_student_id and canvas_assignment_id:
                canvas_grades.append(
                    CanvasGrade(
                        canvas_user_id=canvas_student_id,
                        canvas_assignment_id=canvas_assignment_id,
                        score=g.numeric_score,
                        posted_grade=str(int(g.numeric_score))
                        if g.numeric_score is not None
                        else "",
                    )
                )

    if canvas_grades:
        db.save_canvas_grades(canvas_grades)

    db.snapshot_canvas_synced()
