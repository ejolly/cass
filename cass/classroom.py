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
    Assignment,
    GHAcceptedAssignment,
    GHAssignment,
    GHCommit,
    GHProfile,
    GHStudentInfo,
    Student,
    Submission,
)


# ---------------------------------------------------------------------------
# Async functions (used by pull.py via GitHubClient)
# ---------------------------------------------------------------------------


async def _resolve_gh_id(client: GitHubClient, assignment: Assignment) -> int:
    """Resolve assignment slug to GH Classroom numeric ID."""
    cfg = get_config()
    data = await client.get_cached(
        f"/classrooms/{cfg.classroom_id}/assignments",
        ttl_hours=24,
        paginate=True,
    )
    items = msgspec.convert(data, list[GHAssignment])
    for a in items:
        if a.slug == assignment.slug:
            return a.id
    raise RuntimeError(f"Assignment {assignment.slug} not found in GH Classroom API")


async def fetch_assignments(
    client: GitHubClient,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[Assignment]:
    """Fetch all assignments from GitHub Classroom.

    Args:
        client: Async GitHub API client.
        ttl_hours: Cache TTL in hours.
        force_refresh: Bypass cache if True.

    Returns:
        Domain ``Assignment`` objects sorted by slug ID.
    """
    cfg = get_config()
    data = await client.get_cached(
        f"/classrooms/{cfg.classroom_id}/assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    items = msgspec.convert(data, list[GHAssignment])
    assignments = []
    for a in items:
        deadline = None
        if a.deadline:
            deadline = datetime.fromisoformat(a.deadline.replace("Z", "+00:00"))
        assignments.append(
            Assignment(
                id=a.slug,
                source="github",
                title=a.title,
                slug=a.slug,
                deadline=deadline,
                points_possible=1.0,
                accepted=a.accepted,
                submissions_count=a.submissions,
                passing_count=a.passing,
            )
        )
    return sorted(assignments, key=lambda a: a.id)


async def fetch_all_students(
    client: GitHubClient,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHStudentInfo]:
    """Aggregate unique students across all assignments.

    Iterates every assignment's accepted list to discover students, then
    fetches GitHub profiles in parallel to fill in name/email.

    Args:
        client: Async GitHub API client.
        ttl_hours: Cache TTL in hours.
        force_refresh: Bypass cache if True.

    Returns:
        De-duplicated students sorted by login (lowercase).
    """
    assignments = await fetch_assignments(
        client, ttl_hours=ttl_hours, force_refresh=force_refresh
    )
    seen: dict[str, GHStudentInfo] = {}

    for assignment in assignments:
        gh_id = await _resolve_gh_id(client, assignment)
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
    assignment: Assignment,
    roster: list[Student],
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[Submission]:
    """Fetch per-student submission data for a GitHub Classroom assignment.

    For each student, checks commit timestamps against the deadline to
    determine on-time/late status. Per-student commit checks are
    parallelized (up to ``MAX_CONCURRENCY``).

    Args:
        client: Async GitHub API client.
        assignment: The assignment to fetch submissions for.
        roster: Students to check (skips students without repos).
        ttl_hours: Cache TTL in hours.
        force_refresh: Bypass cache if True.

    Returns:
        Submissions sorted by student_id.
    """
    cfg = get_config()
    gh_id = await _resolve_gh_id(client, assignment)
    data = await client.get_cached(
        f"/assignments/{gh_id}/accepted_assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    accepted = msgspec.convert(data, list[GHAcceptedAssignment])

    # Build per-student info from accepted_assignments (includes free fields)
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

    async def check_student(student: Student) -> Submission:
        info = student_repo_info.get(student.handle_lower)
        if not info:
            return Submission(
                student_id=student.handle_lower or student.identifier,
                assignment_id=assignment.id,
                source="github",
                submitted=False,
            )

        repo_short = info["repo_short"]
        commit_count = info["commit_count"]
        submitted = True
        on_time = False
        commits_after_deadline = 0
        late = False
        lateness_seconds = 0

        if assignment.deadline:
            # If commit_count is 0, no commits exist — skip API calls
            if commit_count == 0:
                on_time = False
            else:
                dl = assignment.deadline.isoformat()
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
                        delta = dt - assignment.deadline
                        lateness_seconds = max(0, int(delta.total_seconds()))
        else:
            # No deadline: commit_count > 0 means submitted — no API call needed
            on_time = commit_count > 0

        return Submission(
            student_id=student.handle_lower or student.identifier,
            assignment_id=assignment.id,
            source="github",
            submitted=submitted,
            late=late,
            lateness_seconds=lateness_seconds,
            repo_name=info["repo_name"],
            commits_after_deadline=commits_after_deadline,
            commit_count=commit_count,
            passing=info["passing"],
            gh_autograder_score=info["grade"],
        )

    submissions = await asyncio.gather(*(check_student(s) for s in roster))
    return sorted(submissions, key=lambda s: s.student_id)


async def fetch_file_submissions(
    client: GitHubClient,
    assignment: Assignment,
    roster: list[Student],
    file_path: str,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[Submission]:
    """Check if a specific file exists in each student's repo (parallel).

    Args:
        client: Async GitHub API client.
        assignment: The assignment whose repos to check.
        roster: Students to check.
        file_path: Path within the repo to look for (e.g. ``pdfs/proposal.pdf``).
        ttl_hours: Cache TTL in hours.
        force_refresh: Bypass cache if True.

    Returns:
        Submissions sorted by student_id, with ``submitted=True`` if
        the file exists.
    """
    cfg = get_config()
    gh_id = await _resolve_gh_id(client, assignment)
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

    async def check_student(student: Student) -> Submission:
        repo_short = repo_by_handle.get(student.handle_lower)
        if not repo_short:
            return Submission(
                student_id=student.handle_lower or student.identifier,
                assignment_id=assignment.id,
                source="github",
                submitted=False,
            )

        file_exists = await client.exists_cached(
            f"/repos/{cfg.org}/{repo_short}/contents/{file_path}",
            ttl_hours=ttl_hours,
            force_refresh=force_refresh,
        )
        return Submission(
            student_id=student.handle_lower or student.identifier,
            assignment_id=assignment.id,
            source="github",
            submitted=file_exists,
            repo_name=f"{cfg.org}/{repo_short}",
        )

    submissions = await asyncio.gather(*(check_student(s) for s in roster))
    return sorted(submissions, key=lambda s: s.student_id)


# ---------------------------------------------------------------------------
# Sync functions (used by fetch.py — subprocess-based, not perf-critical)
# ---------------------------------------------------------------------------


def _resolve_gh_id_sync(assignment: Assignment) -> int:
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
        if a.slug == assignment.slug:
            return a.id
    raise RuntimeError(f"Assignment {assignment.slug} not found in GH Classroom API")


def build_repo_map(
    assignment: Assignment,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> dict[str, str]:
    """Return ``{handle_lower: repo_short_name}`` for an assignment.

    Sync version used by ``fetch.py`` for file downloads.

    Args:
        assignment: Assignment to look up repos for.
        ttl_hours: Cache TTL in hours.
        force_refresh: Bypass cache if True.

    Returns:
        Mapping from lowercase GitHub handle to short repo name.
    """
    gh_id = _resolve_gh_id_sync(assignment)
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
