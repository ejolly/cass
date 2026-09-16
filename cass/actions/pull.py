"""Pull orchestration — fetch APIs, populate source tables, merge to master tables.

GitHub API calls use async httpx with parallel per-student fetching.
Canvas calls remain synchronous (fewer calls, not the bottleneck).
"""

from __future__ import annotations

__docformat__ = "google"

import typing
from datetime import datetime

import typer
from rich.console import Console

from .. import db
from ..apis.canvas import matching as matching_mod
from ..apis.github import classroom
from ..apis.github.client import GitHubClient
from ..async_utils import gather_bounded
from ..db.schema import (
    Assignment,
    CanvasAssignment,
    CanvasStudent,
    CanvasSubmission,
    GHAssignment,
    GHStudent,
    Student,
)
from .config import Config
from .matching import slug_match, slugify


def _ensure_classroom_ready(cfg: Config) -> None:
    """Raise a clear error when Classroom setup is incomplete."""
    if cfg.classroom_needs_resolution:
        raise RuntimeError(
            "GitHub Classroom URL is saved, but the gh-classroom ID is unresolved. "
            "Fix gh auth/Classroom access and run `cass init` or `cass pull` again."
        )


async def _fetch_gh_submissions(
    client: GitHubClient,
    gh_assignments: list[Assignment],
    students: list[Student],
    ttl_hours: float,
    force_refresh: bool,
    on_status: typing.Callable[[str], None] | None = None,
) -> list[db.GHSubmission]:
    """Fetch GH submissions for all assignments (shared by CLI + viewer).

    The roster is built from the GH Classroom roster (``gh_students``) as the
    authoritative source, merged with Canvas students.  This ensures that:
    - GH-roster students without a Canvas account get submissions
    - Random users who only accepted an assignment are excluded
    """
    # Build merged roster: Canvas students + GH-roster-only students
    gh_handles = db.load_gh_student_handles()
    canvas_handles = {s.handle_lower for s in students if s.github_username}
    gh_only = gh_handles - canvas_handles
    roster = list(students)
    for handle in gh_only:
        roster.append(Student(canvas_id=0, github_username=handle))

    total = len(gh_assignments)

    async def _fetch_one(a: Assignment) -> list[db.GHSubmission]:
        return await classroom.fetch_submissions(
            client,
            a.gh_assignment_slug,
            a.deadline,
            roster,
            ttl_hours=ttl_hours,
            force_refresh=force_refresh,
        )

    def _on_done(result) -> None:  # pyright: ignore[reportUnknownParameterType,reportMissingParameterType]
        if on_status is None:
            return
        if result.error is not None:
            on_status(
                f"GitHub ({result.index}/{total}) {result.key}: ERROR {result.error}"
            )
        else:
            on_status(f"GitHub ({result.index}/{total}) {result.key}")

    coros = {a.slug: _fetch_one(a) for a in gh_assignments}
    results = await gather_bounded(coros, max_concurrent=3, on_complete=_on_done)

    all_subs: list[db.GHSubmission] = []
    for r in results:
        if r.value is not None:
            all_subs.extend(r.value)
    return all_subs


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
    from .matching import find_candidates, match_students

    _ensure_classroom_ready(cfg)

    # Step 1: Canvas students (always — Canvas is required)
    console.print("[bold]Pulling students from Canvas...[/bold]")
    canvas_students_api, sis_section_map = matching_mod.fetch_students_with_sections(
        cfg.canvas_course_id
    )
    sections = sis_section_map or {}
    db.save_canvas_students(
        [
            CanvasStudent.from_api(s, sis_section_id=sections.get(s.id, ""))
            for s in canvas_students_api
        ]
    )
    console.print(f"  Found {len(canvas_students_api)} Canvas students")

    # Step 2: Create/update master students from Canvas (authoritative)
    master_students = [
        Student(canvas_id=cs.id, name=cs.name, email=cs.email)
        for cs in canvas_students_api
    ]
    db.upsert_students(master_students)

    # Step 3: GitHub Classroom students (if configured)
    if cfg.has_classroom and client is not None:
        console.print("[bold]Pulling students from GitHub Classroom...[/bold]")
        gh_students = await classroom.fetch_all_students(
            client, ttl_hours=ttl, force_refresh=no_cache
        )
        db.save_gh_students([GHStudent.from_api(s) for s in gh_students])
        console.print(f"  Found {len(gh_students)} GitHub students")

        # Load existing master students to check for previous mappings
        existing = db.load_students(include_excluded=True)
        already_mapped = {s.github_username for s in existing if s.github_username}

        # Auto-match by name (only for unmapped GH students)
        unmapped_gh = [g for g in gh_students if g.login.lower() not in already_mapped]
        if unmapped_gh:
            result = match_students(unmapped_gh, canvas_students_api)
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
                    candidates = find_candidates(gh_s, unmatched_canvas)
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
    _ensure_classroom_ready(cfg)
    # Step 1: Canvas assignments (always present)
    console.print("[bold]Pulling assignments from Canvas...[/bold]")
    canvas_assignments_api, group_names = matching_mod.fetch_canvas_assignments(
        cfg.canvas_course_id
    )
    groups = group_names or {}
    db.save_canvas_assignments(
        [
            CanvasAssignment.from_api(
                a, group_name=groups.get(a.assignment_group_id, "")
            )
            for a in canvas_assignments_api
        ]
    )
    console.print(f"  Found {len(canvas_assignments_api)} Canvas assignments")

    # Step 2: GitHub assignments (if configured)
    gh_assignments_api = []
    if cfg.has_classroom and client is not None:
        console.print("[bold]Pulling assignments from GitHub Classroom...[/bold]")
        gh_assignments_api = await classroom.fetch_assignments(
            client, ttl_hours=ttl, force_refresh=no_cache
        )
        db.save_gh_assignments(
            [GHAssignment.from_api(a) for a in gh_assignments_api]  # pyright: ignore[reportUnknownMemberType]
        )
        console.print(f"  Found {len(gh_assignments_api)} GitHub assignments")

    # Step 3: Merge into master assignments table
    # Load existing master to preserve manual mappings
    existing_master = {a.slug: a for a in db.load_assignments()}

    master: list[Assignment] = []

    # Start from Canvas assignments as the base
    used_gh_slugs: set[str] = set()
    for ca in canvas_assignments_api:
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
            for ga in gh_assignments_api:
                if ga.slug not in used_gh_slugs and slug_match(ga.slug, slug):
                    gh_slug = ga.slug
                    used_gh_slugs.add(ga.slug)
                    break

        deadline = None
        if ca.due_at:
            try:
                deadline = datetime.fromisoformat(ca.due_at)
            except ValueError:
                pass
        # Fall back to GH assignment deadline when Canvas has none
        if deadline is None and gh_slug:
            matched_ga = next(
                (ga for ga in gh_assignments_api if ga.slug == gh_slug), None
            )
            if matched_ga and matched_ga.deadline:
                try:
                    deadline = datetime.fromisoformat(matched_ga.deadline)
                except ValueError:
                    pass

        master.append(
            Assignment(
                slug=slug,
                title=ca.name,
                gh_assignment_slug=gh_slug,
                canvas_assignment_id=ca.id,
                points_possible=ca.points_possible or 0.0,
                deadline=deadline,
            )
        )

    # Add GH-only assignments (not matched to any Canvas assignment)
    for ga in gh_assignments_api:
        if ga.slug not in used_gh_slugs:
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


async def pull_submissions(
    client: GitHubClient | None,
    cfg: Config,
    console: Console,
    ttl: float,
    no_cache: bool,
) -> None:
    """Fetch submissions for all assignments into source tables."""
    _ensure_classroom_ready(cfg)
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
        all_gh_subs = await _fetch_gh_submissions(
            client,
            gh_assignments,
            students,
            ttl_hours=ttl,
            force_refresh=no_cache,
            on_status=lambda msg: console.print(f"  Fetching GH submissions... {msg}"),
        )
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


async def pull_all_async(
    cfg: Config,
    on_progress: typing.Callable[[str, str], None] | None = None,
) -> None:
    """Run a full pull (students, assignments, submissions).

    Unlike the CLI ``pull`` command this is non-interactive — unmatched
    GitHub students are silently skipped — and reports progress via an
    optional *on_progress(step_name, detail)* callback instead of a Rich
    console.

    Designed to be called from both CLI and viewer contexts.
    """
    from .matching import match_students

    if (reason := db.pull_block_reason()) is not None:
        raise RuntimeError(reason)

    if not cfg.has_classroom_url:
        db.clear_github_data()
    _ensure_classroom_ready(cfg)

    def _report(step: str, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(step, detail)

    # --- course info ---
    course_name = matching_mod.fetch_course_name(cfg.canvas_course_id)
    db.save_meta("course_name", course_name)

    # --- students ---
    _report("students", "Pulling Canvas students...")
    cs_api, sis_section_map = matching_mod.fetch_students_with_sections(
        cfg.canvas_course_id
    )
    sections = sis_section_map or {}
    db.save_canvas_students(
        [
            CanvasStudent.from_api(s, sis_section_id=sections.get(s.id, ""))
            for s in cs_api
        ]
    )
    master_students = [
        Student(canvas_id=cs.id, name=cs.name, email=cs.email) for cs in cs_api
    ]
    db.upsert_students(master_students)
    _report("students", f"{len(cs_api)} Canvas students")

    client: GitHubClient | None = None
    try:
        if cfg.has_classroom:
            client = GitHubClient()
            _report("students", "Pulling GitHub Classroom students...")
            gh_students = await classroom.fetch_all_students(
                client, ttl_hours=6.0, force_refresh=False
            )
            db.save_gh_students([GHStudent.from_api(s) for s in gh_students])
            _report("students", f"{len(gh_students)} GitHub students")

            # Auto-match only (no interactive prompts)
            existing = db.load_students(include_excluded=True)
            already_mapped = {s.github_username for s in existing if s.github_username}
            unmapped_gh = [
                g for g in gh_students if g.login.lower() not in already_mapped
            ]
            if unmapped_gh:
                result = match_students(unmapped_gh, cs_api)
                for gh_login, canvas_id in result.matched.items():
                    db.update_student_github(canvas_id, gh_login)
                if result.matched:
                    _report(
                        "students",
                        f"Auto-matched {len(result.matched)} student(s)",
                    )

        # --- assignments ---
        _report("assignments", "Pulling Canvas assignments...")
        ca_api, group_names = matching_mod.fetch_canvas_assignments(
            cfg.canvas_course_id
        )
        groups = group_names or {}
        db.save_canvas_assignments(
            [
                CanvasAssignment.from_api(
                    a, group_name=groups.get(a.assignment_group_id, "")
                )
                for a in ca_api
            ]
        )
        _report("assignments", f"{len(ca_api)} Canvas assignments")

        gh_assignments_list = []
        if cfg.has_classroom and client is not None:
            _report("assignments", "Pulling GitHub assignments...")
            gh_assignments_list = await classroom.fetch_assignments(
                client, ttl_hours=6.0, force_refresh=False
            )
            db.save_gh_assignments(
                [GHAssignment.from_api(a) for a in gh_assignments_list]  # pyright: ignore[reportUnknownMemberType]
            )

        # Merge to master
        existing_master = {a.slug: a for a in db.load_assignments()}
        master: list[Assignment] = []
        used_gh_slugs: set[str] = set()

        for ca in ca_api:
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

            deadline = None
            if ca.due_at:
                try:
                    deadline = datetime.fromisoformat(ca.due_at)
                except ValueError:
                    pass
            # Fall back to GH assignment deadline when Canvas has none
            if deadline is None and gh_slug:
                matched_ga = next(
                    (ga for ga in gh_assignments_list if ga.slug == gh_slug), None
                )
                if matched_ga and matched_ga.deadline:
                    try:
                        deadline = datetime.fromisoformat(matched_ga.deadline)
                    except ValueError:
                        pass
            master.append(
                Assignment(
                    slug=slug,
                    title=ca.name,
                    gh_assignment_slug=gh_slug,
                    canvas_assignment_id=ca.id,
                    points_possible=ca.points_possible or 0.0,
                    deadline=deadline,
                )
            )
        for ga in gh_assignments_list:
            if ga.slug not in used_gh_slugs:
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
                all_gh_subs = await _fetch_gh_submissions(
                    client,
                    gh_assignments,
                    students,
                    ttl_hours=6.0,
                    force_refresh=False,
                    on_status=lambda msg: _report("submissions", msg),
                )
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

        # --- snapshot synced state ---
        db.snapshot_canvas_synced()
        _report("done", "Pull complete")

    finally:
        if client:
            await client.close()
