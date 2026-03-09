"""GitHub Classroom CLI integration used by pull and repo workflows."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from datetime import datetime
from typing import TypedDict

import msgspec

from ...actions.config import get_config
from ...db.schema import GHSubmission, Student
from .client import GitHubClient
from .schema import (
    GHAcceptedAssignment,
    GHAssignmentResponse,
    GHCommit,
    GHRosterEntry,
    GHStarterCodeRepo,
    GHStudentInfo,
)


class RepoInfo(TypedDict):
    repo_name: str
    commit_count: int
    passing: bool
    grade: str
    submitted: bool


def _repo_full_name_from_grade(entry_repo_name: str, entry_repo_url: str) -> str:
    if entry_repo_url.startswith("https://github.com/"):
        return entry_repo_url.removeprefix("https://github.com/").strip("/")
    return entry_repo_name.strip("/")


async def _assignment_map(client: GitHubClient) -> dict[str, GHAssignmentResponse]:
    cfg = get_config()
    data = await client.get_cached(
        f"/classrooms/{cfg.classroom_gh_id}/assignments", paginate=True
    )
    assignments = msgspec.convert(data, list[GHAssignmentResponse])
    return {
        assignment.slug: assignment for assignment in assignments if assignment.slug
    }


async def resolve_gh_id(client: GitHubClient, slug: str) -> int:
    """Resolve assignment slug to the gh-classroom assignment ID."""
    items = await _assignment_map(client)
    assignment = items.get(slug)
    if assignment is None:
        raise RuntimeError(f"Assignment {slug} not found in GitHub Classroom")
    return assignment.id


async def fetch_assignments(
    client: GitHubClient,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHAssignmentResponse]:
    """Fetch all assignments from GitHub Classroom REST API."""
    cfg = get_config()
    data = await client.get_cached(
        f"/classrooms/{cfg.classroom_gh_id}/assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    assignments = msgspec.convert(data, list[GHAssignmentResponse])
    normalized: list[GHAssignmentResponse] = []
    for assignment in assignments:
        starter = assignment.starter_code_repository
        if isinstance(starter, dict):
            starter = msgspec.convert(starter, GHStarterCodeRepo)
        normalized.append(
            GHAssignmentResponse(
                id=assignment.id,
                slug=assignment.slug,
                title=assignment.title,
                deadline=assignment.deadline,
                accepted=assignment.accepted,
                submissions=assignment.submissions,
                passing=assignment.passing,
                starter_code_repository=starter,
            )
        )
    return normalized


async def fetch_all_students(
    client: GitHubClient,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHStudentInfo]:
    """Aggregate unique students from assignment grade exports."""
    assignments = await fetch_assignments(
        client, ttl_hours=ttl_hours, force_refresh=force_refresh
    )
    seen: dict[str, GHStudentInfo] = {}

    for assignment in assignments:
        grades_data = await client.get_cached(
            f"/assignments/{assignment.id}/grades",
            ttl_hours=ttl_hours,
            force_refresh=force_refresh,
            paginate=True,
        )
        entries = msgspec.convert(grades_data, list[GHRosterEntry])
        for entry in entries:
            login = entry.github_username
            if not login:
                continue
            key = login.lower()
            if key not in seen:
                seen[key] = GHStudentInfo(
                    login=login,
                    name=entry.roster_identifier,
                )
            elif not seen[key].name and entry.roster_identifier:
                seen[key].name = entry.roster_identifier

    return sorted(seen.values(), key=lambda s: s.login.lower())


def _username_from_accepted(entry: GHAcceptedAssignment) -> str:
    """Extract the first student login from an accepted assignment."""
    if entry.students:
        return entry.students[0].login
    return ""


def _repo_name_from_accepted(entry: GHAcceptedAssignment) -> str:
    """Extract the repository full_name from an accepted assignment."""
    if entry.repository is not None:
        return entry.repository.full_name
    return ""


def _accepted_by_repo(
    accepted: list[GHAcceptedAssignment],
) -> tuple[dict[str, GHAcceptedAssignment], dict[str, GHAcceptedAssignment]]:
    by_repo: dict[str, GHAcceptedAssignment] = {}
    by_user: dict[str, GHAcceptedAssignment] = {}
    for entry in accepted:
        repo_name = _repo_name_from_accepted(entry).strip().lower()
        user = _username_from_accepted(entry).strip().lower()
        if repo_name and repo_name not in by_repo:
            by_repo[repo_name] = entry
        if user and user not in by_user:
            by_user[user] = entry
    return by_repo, by_user


async def fetch_submissions(
    client: GitHubClient,
    assignment_slug: str,
    assignment_deadline: datetime | str | None,
    roster: list[Student],
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHSubmission]:
    """Fetch per-student submission data for a GitHub Classroom assignment."""
    # Normalize deadline: SQLite may return a string instead of datetime
    if isinstance(assignment_deadline, str):
        try:
            assignment_deadline = datetime.fromisoformat(assignment_deadline)
        except ValueError:
            assignment_deadline = None
    gh_id = await resolve_gh_id(client, assignment_slug)
    accepted_data = await client.get_cached(
        f"/assignments/{gh_id}/accepted_assignments",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    accepted = msgspec.convert(accepted_data, list[GHAcceptedAssignment])
    grades_data = await client.get_cached(
        f"/assignments/{gh_id}/grades",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    grades = msgspec.convert(grades_data, list[GHRosterEntry])
    accepted_by_repo, accepted_by_user = _accepted_by_repo(accepted)

    student_repo_info: dict[str, RepoInfo] = {}
    for entry in grades:
        handle = entry.github_username.strip().lower()
        if not handle:
            continue
        repo_name = _repo_full_name_from_grade(
            entry.student_repository_name,
            entry.student_repository_url,
        )
        accepted_info = accepted_by_repo.get(repo_name.lower()) or accepted_by_user.get(
            handle
        )
        student_repo_info[handle] = {
            "repo_name": repo_name,
            "commit_count": accepted_info.commit_count if accepted_info else 0,
            "passing": accepted_info.passing if accepted_info else False,
            "grade": str(
                accepted_info.grade
                if accepted_info and accepted_info.grade is not None
                else entry.points_awarded
            ),
            "submitted": bool(entry.submission_timestamp)
            or (accepted_info.submitted if accepted_info else False),
        }

    async def check_handle(handle: str) -> GHSubmission | None:
        if not handle:
            return None
        info = student_repo_info.get(handle)
        if not info:
            return GHSubmission(
                github_username=handle,
                assignment_slug=assignment_slug,
                submitted=False,
            )

        repo_name = info["repo_name"]
        commit_count = info["commit_count"]
        submitted = info["submitted"]
        on_time = False
        commits_after_deadline = 0
        late = False
        lateness_seconds = 0
        last_commit_at = ""
        last_commit_sha = ""

        if assignment_deadline and repo_name:
            if commit_count == 0:
                on_time = False
            else:
                dl = assignment_deadline.isoformat()
                before_raw = await client.get_cached(
                    f"/repos/{repo_name}/commits?until={dl}&per_page=1",
                    ttl_hours=ttl_hours,
                    force_refresh=force_refresh,
                )
                on_time = isinstance(before_raw, list) and len(before_raw) > 0  # pyright: ignore[reportUnknownArgumentType]
                after_data = await client.get_cached(
                    f"/repos/{repo_name}/commits?since={dl}",
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
                        dt = datetime.fromisoformat(date_str)
                        delta = dt - assignment_deadline
                        lateness_seconds = max(0, int(delta.total_seconds()))

                if after:
                    last_commit_at = after[0].commit.committer.date
                    last_commit_sha = after[0].sha
                elif on_time and isinstance(before_raw, list) and before_raw:
                    before_commits = msgspec.convert(before_raw, list[GHCommit])
                    if before_commits:
                        last_commit_at = before_commits[0].commit.committer.date
                        last_commit_sha = before_commits[0].sha
        elif repo_name and commit_count > 0:
            latest_data = await client.get_cached(
                f"/repos/{repo_name}/commits?per_page=1",
                ttl_hours=ttl_hours,
                force_refresh=force_refresh,
            )
            if isinstance(latest_data, list) and latest_data:
                latest = msgspec.convert(latest_data, list[GHCommit])
                if latest:
                    last_commit_at = latest[0].commit.committer.date
                    last_commit_sha = latest[0].sha

        return GHSubmission(
            github_username=handle,
            assignment_slug=assignment_slug,
            submitted=submitted,
            late=late,
            lateness_seconds=lateness_seconds,
            repo_name=repo_name,
            commits_after_deadline=commits_after_deadline,
            commit_count=commit_count,
            passing=info["passing"],
            gh_autograder_score=info["grade"],
            last_commit_at=last_commit_at,
            last_commit_sha=last_commit_sha,
        )

    handles = [s.handle_lower for s in roster if s.github_username]
    results = await asyncio.gather(*(check_handle(h) for h in handles))
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
    """Check whether a specific file exists in each student's repo."""
    repo_by_handle = await build_repo_map(
        client,
        assignment_slug,
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
    )

    async def check_handle(handle: str) -> GHSubmission | None:
        if not handle:
            return None
        repo_name = repo_by_handle.get(handle)
        if not repo_name:
            return GHSubmission(
                github_username=handle,
                assignment_slug=assignment_slug,
                submitted=False,
            )

        file_exists = await client.exists_cached(
            f"/repos/{repo_name}/contents/{file_path}",
            ttl_hours=ttl_hours,
            force_refresh=force_refresh,
        )
        return GHSubmission(
            github_username=handle,
            assignment_slug=assignment_slug,
            submitted=file_exists,
            repo_name=repo_name,
        )

    handles = [s.handle_lower for s in roster if s.github_username]
    results = await asyncio.gather(*(check_handle(h) for h in handles))
    submissions = [s for s in results if s is not None]
    return sorted(submissions, key=lambda s: s.github_username)


async def build_repo_map(
    client: GitHubClient,
    assignment_slug: str,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> dict[str, str]:
    """Return ``{handle_lower: repo_full_name}`` for an assignment."""
    gh_id = await resolve_gh_id(client, assignment_slug)
    grades_data = await client.get_cached(
        f"/assignments/{gh_id}/grades",
        ttl_hours=ttl_hours,
        force_refresh=force_refresh,
        paginate=True,
    )
    grades = msgspec.convert(grades_data, list[GHRosterEntry])
    repo_map: dict[str, str] = {}
    for entry in grades:
        handle = entry.github_username.strip().lower()
        repo_name = _repo_full_name_from_grade(
            entry.student_repository_name,
            entry.student_repository_url,
        )
        if handle and repo_name:
            repo_map[handle] = repo_name
    return repo_map
