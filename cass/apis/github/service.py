"""Shared gh-classroom service helpers."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
import csv
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ...actions.config import parse_classroom_url
from .client import check_auth, check_available
from .schema import GHAssignmentResponse, GHRosterEntry, GHStarterCodeRepo

_COLUMN_SPLIT_RE = re.compile(r"\s{2,}")
_DETAIL_RE = re.compile(r"^([^:]+):\s*(.*)$")
_URL_SLUG_RE = re.compile(
    r"^https?://classroom\.github\.com/classrooms/\d+(?:-([^/?#]+))?(?:[/?#].*)?$"
)


class GitHubServiceError(RuntimeError):
    """High-level GitHub Classroom error with actionable messaging."""

    def __init__(self, code: str, detail: str, hint: str = "") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.hint = hint

    @property
    def display_message(self) -> str:
        if self.hint:
            return f"{self.detail} {self.hint}"
        return self.detail


@dataclass(frozen=True)
class ResolvedClassroom:
    url: str
    url_id: int
    gh_id: int
    slug: str = ""
    title: str = ""
    org: str = ""


@dataclass(frozen=True)
class GHClassroom:
    gh_id: int
    url: str = ""
    slug: str = ""
    title: str = ""
    org: str = ""


@dataclass(frozen=True)
class ClassroomResolutionResult:
    """Result of attempting to resolve a GitHub Classroom URL.

    ``resolved`` is set when the classroom was fully resolved (gh_id obtained).
    On failure, ``error_code`` and ``error_detail`` describe what went wrong,
    and ``recovery_hint`` suggests the fix.
    """

    url: str = ""
    url_id: int = 0
    resolved: ResolvedClassroom | None = None
    gh_account: str = ""
    error_code: str = ""
    error_detail: str = ""
    recovery_hint: str = ""


@dataclass(frozen=True)
class GHAcceptedAssignmentInfo:
    github_username: str = ""
    repository_full_name: str = ""
    commit_count: int = 0
    submitted: bool = False
    passing: bool = False
    grade: str | None = None


def check_classroom_extension() -> tuple[bool, str]:
    """Return whether the gh-classroom extension is installed."""
    if not check_available():
        return False, "Install GitHub CLI: https://cli.github.com/"
    try:
        result = subprocess.run(
            ["gh", "extension", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "Install GitHub CLI: https://cli.github.com/"
    output = "\n".join([result.stdout, result.stderr]).lower()
    if "github/gh-classroom" in output or "gh classroom" in output:
        return True, "installed"
    return (
        False,
        "Install the GitHub Classroom extension: "
        "gh extension install github/gh-classroom",
    )


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "y", "submitted", "passing"}


def _to_int(value: str) -> int:
    digits = re.sub(r"[^\d-]+", "", value)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _normalize_classroom_url(url: str) -> str:
    match = _URL_SLUG_RE.match(url.strip())
    if not match:
        return ""
    return url.strip().rstrip("/")


def _classroom_url_match(classroom: GHClassroom, url: str) -> bool:
    normalized_url = _normalize_classroom_url(url)
    normalized_classroom_url = _normalize_classroom_url(classroom.url)
    return bool(normalized_url and normalized_classroom_url == normalized_url)


def _preflight() -> None:
    if not check_available():
        raise GitHubServiceError(
            "gh_missing",
            "GitHub CLI is not installed.",
            "Install GitHub CLI: https://cli.github.com/",
        )
    ext_ok, ext_detail = check_classroom_extension()
    if not ext_ok:
        raise GitHubServiceError(
            "gh_classroom_missing",
            "GitHub Classroom extension is not installed.",
            ext_detail,
        )
    authed, _detail = check_auth()
    if not authed:
        raise GitHubServiceError(
            "gh_auth_missing",
            "GitHub authentication is invalid.",
            "Run `gh auth login -h github.com`.",
        )


def _map_command_error(args: list[str], stderr: str, stdout: str) -> GitHubServiceError:
    combined = "\n".join(part for part in [stderr, stdout] if part).strip()
    lowered = combined.lower()
    if "authentication token not found" in lowered or "gh auth login" in lowered:
        return GitHubServiceError(
            "gh_auth_missing",
            "GitHub authentication is invalid.",
            "Run `gh auth login -h github.com`.",
        )
    if "unknown command" in lowered and "classroom" in lowered:
        return GitHubServiceError(
            "gh_classroom_missing",
            "GitHub Classroom extension is not installed.",
            "Install the GitHub Classroom extension: "
            "gh extension install github/gh-classroom",
        )
    if "http 404" in lowered or "not found" in lowered:
        subject = (
            " ".join(args[2:])
            if len(args) > 2
            else "requested GitHub Classroom resource"
        )
        return GitHubServiceError(
            "classroom_no_access",
            f"Authenticated, but this account cannot access {subject}.",
        )
    return GitHubServiceError(
        "gh_command_failed",
        f"`{' '.join(args)}` failed.",
        combined or "The gh-classroom command returned a non-zero exit code.",
    )


def _run_gh(args: list[str]) -> str:
    _preflight()
    try:
        result = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitHubServiceError(
            "gh_missing",
            "GitHub CLI is not installed.",
            "Install GitHub CLI: https://cli.github.com/",
        ) from exc
    if result.returncode != 0:
        raise _map_command_error(["gh", *args], result.stderr, result.stdout)
    return result.stdout


def _parse_table(output: str) -> list[dict[str, str]]:
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    headers = [
        _normalize_header(part) for part in _COLUMN_SPLIT_RE.split(lines[0].strip())
    ]
    if not headers:
        return []
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = _COLUMN_SPLIT_RE.split(line.strip(), maxsplit=max(len(headers) - 1, 0))
        if len(parts) != len(headers):
            continue
        rows.append(dict(zip(headers, parts, strict=True)))
    return rows


def _parse_details(output: str) -> dict[str, str]:
    details: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DETAIL_RE.match(line)
        if not match:
            continue
        details[_normalize_header(match.group(1))] = match.group(2).strip()
    return details


def _get_first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return value
    return ""


def _coerce_classroom(row: dict[str, str]) -> GHClassroom:
    gh_id = _to_int(_get_first(row, "id", "classroom_id"))
    return GHClassroom(
        gh_id=gh_id,
        url=_get_first(row, "url", "classroom_url"),
        slug=_get_first(row, "slug", "classroom_slug"),
        title=_get_first(row, "title", "name", "classroom"),
        org=_get_first(row, "organization", "org"),
    )


def _coerce_assignment_from_details(
    details: dict[str, str], assignment_id: int
) -> GHAssignmentResponse:
    starter = _get_first(details, "starter_code_repository", "starter_code_repo")
    accepted = _to_int(_get_first(details, "accepted", "accepted_assignments"))
    submissions = _to_int(_get_first(details, "submissions", "submissions_count"))
    passing = _to_int(_get_first(details, "passing", "passing_count"))
    return GHAssignmentResponse(
        id=assignment_id,
        slug=_get_first(details, "slug"),
        title=_get_first(details, "title", "name"),
        deadline=_get_first(details, "deadline", "due_at") or None,
        accepted=accepted,
        submissions=submissions,
        passing=passing,
        starter_code_repository=(
            None if not starter else GHStarterCodeRepo(id=0, full_name=starter)
        ),
    )


def _parse_repository_name(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("https://github.com/"):
        cleaned = cleaned.removeprefix("https://github.com/")
    return cleaned.removesuffix(".git").strip("/")


def list_classrooms(per_page: int = 100) -> list[GHClassroom]:
    """Return classrooms visible to the authenticated gh-classroom user."""
    classrooms: list[GHClassroom] = []
    page = 1
    while True:
        output = _run_gh(
            [
                "classroom",
                "list",
                "--page",
                str(page),
                "--per-page",
                str(per_page),
            ]
        )
        rows = _parse_table(output)
        if not rows:
            break
        if rows and all(not _get_first(row, "url", "classroom_url") for row in rows):
            raise GitHubServiceError(
                "classroom_url_missing",
                "`gh classroom list` did not include a URL column.",
                "Update or reinstall the GitHub Classroom extension and try again.",
            )
        classrooms.extend(
            classroom
            for row in rows
            if (classroom := _coerce_classroom(row)).gh_id and classroom.url
        )
        if len(rows) < per_page:
            break
        page += 1
    return classrooms


def view_classroom(gh_id: int) -> GHClassroom:
    """Return detailed classroom metadata for a resolved gh-classroom ID."""
    details = _parse_details(
        _run_gh(["classroom", "view", "--classroom-id", str(gh_id)])
    )
    return GHClassroom(
        gh_id=gh_id,
        url=_get_first(details, "url", "classroom_url"),
        slug=_get_first(details, "slug", "classroom_slug"),
        title=_get_first(details, "title", "name"),
        org=_get_first(details, "organization", "org"),
    )


def _build_resolved_classroom(url: str, classroom: GHClassroom) -> ResolvedClassroom:
    url_id = parse_classroom_url(url)
    if url_id is None:
        raise GitHubServiceError(
            "classroom_url_invalid",
            "That doesn't look like a GitHub Classroom URL.",
            "Expected format: https://classroom.github.com/classrooms/123456-course-name",
        )
    return ResolvedClassroom(
        url=url.strip(),
        url_id=url_id,
        gh_id=classroom.gh_id,
        slug=classroom.slug,
        title=classroom.title,
        org=classroom.org,
    )


def resolve_classroom_from_url_sync(url: str) -> ResolvedClassroom:
    """Resolve a user-provided classroom URL to the hidden gh-classroom ID."""
    url_id = parse_classroom_url(url)
    if url_id is None:
        raise GitHubServiceError(
            "classroom_url_invalid",
            "That doesn't look like a GitHub Classroom URL.",
            "Expected format: https://classroom.github.com/classrooms/123456-course-name",
        )
    classrooms = list_classrooms()
    resolved = next((row for row in classrooms if _classroom_url_match(row, url)), None)
    if resolved is None:
        raise GitHubServiceError(
            "classroom_unresolved",
            f"Authenticated, but no owned classroom matched URL ID {url_id}.",
            "Confirm the URL is correct and that the authenticated GitHub "
            "account owns or administers this classroom.",
        )
    classroom = view_classroom(resolved.gh_id)
    if not classroom.url:
        classroom = GHClassroom(
            gh_id=classroom.gh_id,
            url=resolved.url,
            slug=classroom.slug,
            title=classroom.title,
            org=classroom.org,
        )
    return _build_resolved_classroom(url, classroom)


async def resolve_classroom_from_url(url: str) -> ResolvedClassroom:
    """Async wrapper for Classroom URL resolution."""
    return await asyncio.to_thread(resolve_classroom_from_url_sync, url)


def _gh_api(endpoint: str) -> tuple[int, str]:
    """Call ``gh api <endpoint>`` and return (exit_code, stdout_or_stderr)."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return 1, "gh not found"
    if result.returncode != 0:
        return result.returncode, result.stderr.strip() or result.stdout.strip()
    return 0, result.stdout


def _extract_slug_from_url(url: str) -> str:
    """Extract the slug portion from a classroom URL, if present."""
    match = _URL_SLUG_RE.match(url.strip())
    if match and match.group(1):
        return match.group(1)
    return ""


def resolve_classroom_direct(url: str) -> ClassroomResolutionResult:
    """Resolve a classroom URL using the GitHub REST API (no gh-classroom extension).

    Uses ``gh api /classrooms`` to list accessible classrooms and matches by URL.
    Returns a ``ClassroomResolutionResult`` with diagnostics on any failure.
    """
    url = url.strip()
    url_id = parse_classroom_url(url)
    if url_id is None:
        return ClassroomResolutionResult(
            url=url,
            error_code="classroom_url_invalid",
            error_detail="That doesn't look like a GitHub Classroom URL.",
            recovery_hint=(
                "Expected format: "
                "https://classroom.github.com/classrooms/123456-course-name"
            ),
        )

    # Check gh CLI available
    if not check_available():
        return ClassroomResolutionResult(
            url=url,
            url_id=url_id,
            error_code="gh_missing",
            error_detail="GitHub CLI is not installed.",
            recovery_hint="Install GitHub CLI: https://cli.github.com/",
        )

    # Check auth
    authed, auth_detail = check_auth()
    gh_account = auth_detail if authed else ""
    if not authed:
        return ClassroomResolutionResult(
            url=url,
            url_id=url_id,
            gh_account="",
            error_code="gh_auth_invalid",
            error_detail="GitHub authentication is invalid or missing.",
            recovery_hint="Run `gh auth login -h github.com`.",
        )

    # List classrooms via REST API
    exit_code, output = _gh_api("/classrooms")
    if exit_code != 0:
        return ClassroomResolutionResult(
            url=url,
            url_id=url_id,
            gh_account=gh_account,
            error_code="gh_api_error",
            error_detail="Failed to list classrooms via GitHub API.",
            recovery_hint=output or "Check gh auth and network connectivity.",
        )

    try:
        classrooms = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return ClassroomResolutionResult(
            url=url,
            url_id=url_id,
            gh_account=gh_account,
            error_code="gh_api_parse_error",
            error_detail="Could not parse GitHub API response.",
            recovery_hint="The gh CLI may need updating.",
        )

    if not isinstance(classrooms, list):
        return ClassroomResolutionResult(
            url=url,
            url_id=url_id,
            gh_account=gh_account,
            error_code="gh_api_parse_error",
            error_detail="Unexpected GitHub API response format.",
            recovery_hint="The gh CLI may need updating.",
        )

    # Match by URL
    normalized_url = _normalize_classroom_url(url)
    matched: dict[str, object] | None = None
    for classroom in classrooms:
        if not isinstance(classroom, dict):
            continue
        classroom_url = classroom.get("url", "")
        if isinstance(classroom_url, str) and (
            _normalize_classroom_url(classroom_url) == normalized_url
        ):
            matched = classroom
            break

    if matched is None:
        return ClassroomResolutionResult(
            url=url,
            url_id=url_id,
            gh_account=gh_account,
            error_code="classroom_no_access",
            error_detail=(
                f"Authenticated as {gh_account}, but no accessible classroom "
                f"matched URL ID {url_id}."
            ),
            recovery_hint=(
                "Confirm the URL is correct and that the authenticated GitHub "
                "account owns or administers this classroom."
            ),
        )

    # Extract metadata
    gh_id = int(matched.get("id", 0))  # pyright: ignore[reportArgumentType]
    title = str(matched.get("name", ""))
    org_data = matched.get("organization")
    org_login = ""
    if isinstance(org_data, dict):
        org_login = str(org_data.get("login", ""))

    slug = _extract_slug_from_url(url)

    resolved = ResolvedClassroom(
        url=url,
        url_id=url_id,
        gh_id=gh_id,
        slug=slug,
        title=title,
        org=org_login,
    )

    return ClassroomResolutionResult(
        url=url,
        url_id=url_id,
        resolved=resolved,
        gh_account=gh_account,
    )


async def resolve_classroom_direct_async(url: str) -> ClassroomResolutionResult:
    """Async wrapper for direct Classroom URL resolution."""
    return await asyncio.to_thread(resolve_classroom_direct, url)


def list_assignments(gh_id: int, per_page: int = 100) -> list[GHAssignmentResponse]:
    """Return detailed assignments for a resolved gh-classroom classroom ID."""
    assignments: list[GHAssignmentResponse] = []
    page = 1
    while True:
        output = _run_gh(
            [
                "classroom",
                "assignments",
                "--classroom-id",
                str(gh_id),
                "--page",
                str(page),
                "--per-page",
                str(per_page),
            ]
        )
        rows = _parse_table(output)
        if not rows:
            break
        for row in rows:
            assignment_id = _to_int(_get_first(row, "id", "assignment_id"))
            if assignment_id:
                assignments.append(get_assignment(assignment_id))
        if len(rows) < per_page:
            break
        page += 1
    return assignments


def get_assignment(assignment_id: int) -> GHAssignmentResponse:
    """Return assignment details for a gh-classroom assignment ID."""
    details = _parse_details(
        _run_gh(["classroom", "assignment", "--assignment-id", str(assignment_id)])
    )
    if not details:
        raise GitHubServiceError(
            "gh_parse_error",
            "Could not parse `gh classroom assignment` output.",
            "The gh-classroom output format may have changed.",
        )
    return _coerce_assignment_from_details(details, assignment_id)


def list_accepted_assignments(
    assignment_id: int,
    per_page: int = 100,
) -> list[GHAcceptedAssignmentInfo]:
    """Return accepted-assignment rows for a gh-classroom assignment."""
    accepted: list[GHAcceptedAssignmentInfo] = []
    page = 1
    while True:
        output = _run_gh(
            [
                "classroom",
                "accepted-assignments",
                "--assignment-id",
                str(assignment_id),
                "--page",
                str(page),
                "--per-page",
                str(per_page),
            ]
        )
        rows = _parse_table(output)
        if not rows:
            break
        for row in rows:
            accepted.append(
                GHAcceptedAssignmentInfo(
                    github_username=_get_first(
                        row,
                        "github_username",
                        "github",
                        "student",
                        "students",
                        "login",
                    ),
                    repository_full_name=_parse_repository_name(
                        _get_first(row, "repository", "student_repository", "repo")
                    ),
                    commit_count=_to_int(_get_first(row, "commit_count", "commits")),
                    submitted=_to_bool(_get_first(row, "submitted", "submission")),
                    passing=_to_bool(_get_first(row, "passing")),
                    grade=_get_first(row, "grade", "points_awarded") or None,
                )
            )
        if len(rows) < per_page:
            break
        page += 1
    return accepted


def assignment_grades(assignment_id: int) -> list[GHRosterEntry]:
    """Return CSV roster-grade rows for a gh-classroom assignment."""
    with tempfile.TemporaryDirectory(prefix="cass-gh-grades-") as temp_dir:
        csv_path = Path(temp_dir) / "grades.csv"
        _run_gh(
            [
                "classroom",
                "assignment-grades",
                "--assignment-id",
                str(assignment_id),
                "--file-name",
                str(csv_path),
            ]
        )
        if not csv_path.exists():
            raise GitHubServiceError(
                "gh_parse_error",
                "GitHub Classroom did not write the grades CSV.",
                "The gh-classroom output format may have changed.",
            )
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows: list[GHRosterEntry] = []
            for raw_row in reader:
                rows.append(
                    GHRosterEntry(
                        github_username=(raw_row.get("github_username") or "").strip(),
                        roster_identifier=(
                            raw_row.get("roster_identifier") or ""
                        ).strip(),
                        student_repository_name=(
                            raw_row.get("student_repository_name") or ""
                        ).strip(),
                        student_repository_url=(
                            raw_row.get("student_repository_url") or ""
                        ).strip(),
                        submission_timestamp=(
                            raw_row.get("submission_timestamp") or ""
                        ).strip(),
                        points_awarded=(raw_row.get("points_awarded") or "").strip(),
                        points_available=(
                            raw_row.get("points_available") or ""
                        ).strip(),
                    )
                )
        return rows


async def list_classrooms_async(per_page: int = 100) -> list[GHClassroom]:
    return await asyncio.to_thread(list_classrooms, per_page)


async def view_classroom_async(gh_id: int) -> GHClassroom:
    return await asyncio.to_thread(view_classroom, gh_id)


async def list_assignments_async(
    gh_id: int, per_page: int = 100
) -> list[GHAssignmentResponse]:
    return await asyncio.to_thread(list_assignments, gh_id, per_page)


async def get_assignment_async(assignment_id: int) -> GHAssignmentResponse:
    return await asyncio.to_thread(get_assignment, assignment_id)


async def list_accepted_assignments_async(
    assignment_id: int,
    per_page: int = 100,
) -> list[GHAcceptedAssignmentInfo]:
    return await asyncio.to_thread(list_accepted_assignments, assignment_id, per_page)


async def assignment_grades_async(assignment_id: int) -> list[GHRosterEntry]:
    return await asyncio.to_thread(assignment_grades, assignment_id)
