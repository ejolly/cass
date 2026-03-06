"""GitHub Classroom API — fetch assignments, submissions, and students.

Async functions (used by pull.py) take a GitHubClient and run in parallel.
Sync _build_repo_map is used by fetch.py for file downloads.
"""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from datetime import datetime

import msgspec

from . import gh
from .config import get_config
from .github_client import GitHubClient
from .models import (
    GHAcceptedAssignment,
    GHAssignment,
    GHCommit,
    GHProfile,
    GHStudentInfo,
    GHSubmission,
    Student,
)


# ---------------------------------------------------------------------------
# Async functions (used by pull.py via GitHubClient)
# ---------------------------------------------------------------------------


async def _resolve_gh_id(client: GitHubClient, slug: str) -> int:
    """Resolve assignment slug to GH Classroom numeric ID."""
    cfg = get_config()
    data = await client.get_cached(
        f"/classrooms/{cfg.classroom_id}/assignments",
        ttl_hours=24,
        paginate=True,
    )
    items = msgspec.convert(data, list[GHAssignment])
    for a in items:
        if a.slug == slug:
            return a.id
    raise RuntimeError(f"Assignment {slug} not found in GH Classroom API")


async def fetch_assignments(
    client: GitHubClient,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHAssignment]:
    """Fetch all assignments from GitHub Classroom (returns API types)."""
    cfg = get_config()
    data = await client.get_cached(
        f"/classrooms/{cfg.classroom_id}/assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    return msgspec.convert(data, list[GHAssignment])


async def fetch_all_students(
    client: GitHubClient,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHStudentInfo]:
    """Aggregate unique students across all assignments."""
    assignments = await fetch_assignments(
        client, ttl_hours=ttl_hours, force_refresh=force_refresh
    )
    seen: dict[str, GHStudentInfo] = {}

    for assignment in assignments:
        gh_id = await _resolve_gh_id(client, assignment.slug)
        data = await client.get_cached(
            f"/assignments/{gh_id}/accepted_assignments",
            ttl_hours=ttl_hours,
            force_refresh=force_refresh,
            paginate=True,
        )
        accepted = msgspec.convert(data, list[GHAcceptedAssignment])
        for entry in accepted:
            for student in entry.students:
                if student.login and student.login.lower() not in seen:
                    seen[student.login.lower()] = GHStudentInfo(
                        login=student.login,
                        id=str(student.id),
                    )

    # Parallel profile lookups
    students = list(seen.values())

    async def lookup_profile(s: GHStudentInfo) -> None:
        try:
            profile_data = await client.get_cached(
                f"/users/{s.login}",
                ttl_hours=ttl_hours,
                force_refresh=force_refresh,
            )
            profile = msgspec.convert(profile_data, GHProfile)
            s.name = profile.name or ""
            s.email = profile.email or ""
        except Exception:
            pass

    await asyncio.gather(*(lookup_profile(s) for s in students))
    return sorted(students, key=lambda s: s.login.lower())


async def fetch_submissions(
    client: GitHubClient,
    assignment_slug: str,
    assignment_deadline: datetime | None,
    roster: list[Student],
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHSubmission]:
    """Fetch per-student submission data for a GitHub Classroom assignment."""
    cfg = get_config()
    gh_id = await _resolve_gh_id(client, assignment_slug)
    data = await client.get_cached(
        f"/assignments/{gh_id}/accepted_assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    accepted = msgspec.convert(data, list[GHAcceptedAssignment])

    # Build per-student info from accepted_assignments
    student_repo_info: dict[str, dict] = {}
    for entry in accepted:
        repo_name = entry.repository.full_name if entry.repository else ""
        for student in entry.students:
            handle = student.login.lower()
            if handle and repo_name:
                student_repo_info[handle] = {
                    "repo_name": repo_name,
                    "repo_short": repo_name.split("/")[-1],
                    "commit_count": entry.commit_count,
                    "passing": entry.passing,
                    "grade": entry.grade or "",
                }

    async def check_student(student: Student) -> GHSubmission | None:
        if not student.github_username:
            return None
        handle = student.handle_lower
        info = student_repo_info.get(handle)
        if not info:
            return GHSubmission(
                github_username=handle,
                assignment_slug=assignment_slug,
                submitted=False,
            )

        repo_short = info["repo_short"]
        commit_count = info["commit_count"]
        submitted = True
        on_time = False
        commits_after_deadline = 0
        late = False
        lateness_seconds = 0

        if assignment_deadline:
            if commit_count == 0:
                on_time = False
            else:
                dl = assignment_deadline.isoformat()
                before = await client.get_cached(
                    f"/repos/{cfg.org}/{repo_short}/commits?until={dl}&per_page=1",
                    ttl_hours=ttl_hours,
                    force_refresh=force_refresh,
                )
                on_time = len(before) > 0

                after_data = await client.get_cached(
                    f"/repos/{cfg.org}/{repo_short}/commits?since={dl}",
                    ttl_hours=ttl_hours,
                    force_refresh=force_refresh,
                    paginate=True,
                )
                after = msgspec.convert(after_data, list[GHCommit])
                commits_after_deadline = len(after)

                if not on_time and after:
                    late = True
                    date_str = after[0].commit.committer.date
                    if date_str:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        delta = dt - assignment_deadline
                        lateness_seconds = max(0, int(delta.total_seconds()))
        else:
            on_time = commit_count > 0

        return GHSubmission(
            github_username=handle,
            assignment_slug=assignment_slug,
            submitted=submitted,
            late=late,
            lateness_seconds=lateness_seconds,
            repo_name=info["repo_name"],
            commits_after_deadline=commits_after_deadline,
            commit_count=commit_count,
            passing=info["passing"],
            gh_autograder_score=info["grade"],
        )

    results = await asyncio.gather(*(check_student(s) for s in roster))
    submissions = [s for s in results if s is not None]
    return sorted(submissions, key=lambda s: s.github_username)


async def fetch_file_submissions(
    client: GitHubClient,
    assignment_slug: str,
    roster: list[Student],
    file_path: str,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHSubmission]:
    """Check if a specific file exists in each student's repo (parallel)."""
    cfg = get_config()
    gh_id = await _resolve_gh_id(client, assignment_slug)
    data = await client.get_cached(
        f"/assignments/{gh_id}/accepted_assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    accepted = msgspec.convert(data, list[GHAcceptedAssignment])

    repo_by_handle: dict[str, str] = {}
    for entry in accepted:
        repo_name = entry.repository.full_name if entry.repository else ""
        for student in entry.students:
            handle = student.login.lower()
            if handle and repo_name:
                repo_by_handle[handle] = repo_name.split("/")[-1]

    async def check_student(student: Student) -> GHSubmission | None:
        if not student.github_username:
            return None
        handle = student.handle_lower
        repo_short = repo_by_handle.get(handle)
        if not repo_short:
            return GHSubmission(
                github_username=handle,
                assignment_slug=assignment_slug,
                submitted=False,
            )

        file_exists = await client.exists_cached(
            f"/repos/{cfg.org}/{repo_short}/contents/{file_path}",
            ttl_hours=ttl_hours,
            force_refresh=force_refresh,
        )
        return GHSubmission(
            github_username=handle,
            assignment_slug=assignment_slug,
            submitted=file_exists,
            repo_name=f"{cfg.org}/{repo_short}",
        )

    results = await asyncio.gather(*(check_student(s) for s in roster))
    submissions = [s for s in results if s is not None]
    return sorted(submissions, key=lambda s: s.github_username)


# ---------------------------------------------------------------------------
# Sync functions (used by fetch.py — subprocess-based, not perf-critical)
# ---------------------------------------------------------------------------


def _resolve_gh_id_sync(slug: str) -> int:
    """Resolve assignment slug to GH Classroom numeric ID (sync, for fetch.py)."""
    cfg = get_config()
    data = gh.api_cached(
        f"/classrooms/{cfg.classroom_id}/assignments",
        ttl_hours=24,
        force_refresh=False,
        paginate=True,
    )
    items = msgspec.convert(data, list[GHAssignment])
    for a in items:
        if a.slug == slug:
            return a.id
    raise RuntimeError(f"Assignment {slug} not found in GH Classroom API")


def build_repo_map(
    assignment_slug: str,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> dict[str, str]:
    """Return ``{handle_lower: repo_short_name}`` for an assignment."""
    gh_id = _resolve_gh_id_sync(assignment_slug)
    data = gh.api_cached(
        f"/assignments/{gh_id}/accepted_assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    accepted = msgspec.convert(data, list[GHAcceptedAssignment])
    repo_map: dict[str, str] = {}
    for entry in accepted:
        repo_name = entry.repository.full_name if entry.repository else ""
        for student in entry.students:
            handle = student.login.lower()
            if handle and repo_name:
                repo_map[handle] = repo_name.split("/")[-1]
    return repo_map
