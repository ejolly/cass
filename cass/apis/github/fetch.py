"""Download student repos from GitHub Classroom via git clone/pull.

Clones student forks into ``gh-classroom/{last-first}/{assignment-slug}/``
next to ``cass.toml``. Re-pulls use ``git fetch + reset --hard`` so the
remote always wins — no merge conflicts.
"""

from __future__ import annotations

__docformat__ = "google"

import asyncio
import re
import shutil
import subprocess
import typing
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from ...actions.config import get_config
from ...async_utils import gather_bounded
from ...db.schema import Assignment, Student
from .classroom import build_repo_map
from .client import GitHubClient

GH_CLASSROOM_DIR = "gh-classroom"

console = Console()

ProgressCallback = Callable[[str], None]


def sanitize_student_dir(sortable_name: str, github_username: str) -> str:
    """Convert a student identity into a filesystem-safe directory name.

    Uses Canvas ``sortable_name`` ("Last, First") when available,
    falling back to ``github_username``.  Result is lowercased with
    spaces/commas replaced by hyphens and non-alphanumeric chars stripped.

    Examples:
        >>> sanitize_student_dir("Smith, Alice", "asmith")
        'smith-alice'
        >>> sanitize_student_dir("De La Cruz, Maria", "mcruz")
        'de-la-cruz-maria'
        >>> sanitize_student_dir("", "asmith")
        'asmith'
    """
    raw = sortable_name or github_username
    # Replace commas and whitespace runs with a single hyphen
    name = re.sub(r"[,\s]+", "-", raw.strip())
    # Strip anything that isn't alphanumeric or hyphen
    name = re.sub(r"[^a-zA-Z0-9-]", "", name)
    # Collapse multiple hyphens, strip leading/trailing
    name = re.sub(r"-{2,}", "-", name).strip("-").lower()
    return name or github_username.lower()


def get_sortable_names() -> dict[int, str]:
    """Load canvas_id → sortable_name from the canvas_students table."""
    from ... import db

    conn = db.get_db()
    rows = conn.execute(
        "SELECT canvas_id, sortable_name FROM canvas_students"
    ).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def student_dir_name(student: Student, sortable_map: dict[int, str]) -> str:
    """Resolve directory name for a student."""
    sortable = sortable_map.get(student.canvas_id, "")
    return sanitize_student_dir(sortable, student.github_username)


def gh_classroom_dir(root: Path) -> Path:
    """Return the project-local GitHub Classroom mirror directory."""
    return root / GH_CLASSROOM_DIR


def remove_gh_classroom_repos(root: Path) -> int:
    """Remove all cloned GitHub Classroom student directories."""
    dest_root = gh_classroom_dir(root)
    if not dest_root.exists():
        return 0
    subdirs = [path for path in dest_root.iterdir() if path.is_dir()]
    for path in subdirs:
        shutil.rmtree(path)
    return len(subdirs)


def _clone_or_pull(repo_url: str, dest: Path) -> str:
    """Clone (shallow) or force-pull a repo into *dest*.

    Returns:
        "cloned", "updated", or "up-to-date".
    """
    if (dest / ".git").exists():
        # Fetch latest and hard-reset to remote HEAD
        result = subprocess.run(
            ["git", "-C", str(dest), "fetch", "origin"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git fetch failed: {result.stderr.strip()}")

        # Check if there are changes
        diff = subprocess.run(
            ["git", "-C", str(dest), "diff", "HEAD", "origin/HEAD", "--stat"],
            capture_output=True,
            text=True,
        )
        if not diff.stdout.strip():
            return "up-to-date"

        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", "origin/HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return "updated"

    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr.strip()}")
    return "cloned"


async def pull_gh(
    client: GitHubClient,
    assignments: list[Assignment],
    students: list[Student],
    *,
    limit_students: int = 0,
    limit_assignments: int = 0,
    on_progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Clone/pull student repos for the given assignments.

    Args:
        client: Authenticated GitHub API client (for ``build_repo_map``).
        assignments: Assignments to fetch (already filtered to GH-linked).
        students: Student roster.
        limit_students: Cap number of students (0 = all).
        limit_assignments: Cap number of assignments (0 = all).
        on_progress: Optional callback for status messages (viewer use).

    Returns:
        Counts dict with keys: cloned, updated, up_to_date, skipped, errors.
    """
    cfg = get_config()
    dest_root = gh_classroom_dir(cfg.root)
    sortable_map = get_sortable_names()

    def _report(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)
        else:
            console.print(msg)

    sorted_students = sorted(students, key=lambda s: s.display_name.lower())
    if limit_students > 0:
        sorted_students = sorted_students[:limit_students]

    if limit_assignments > 0:
        assignments = assignments[:limit_assignments]

    counts = {"cloned": 0, "updated": 0, "up_to_date": 0, "skipped": 0, "errors": 0}

    for a in assignments:
        slug = a.gh_assignment_slug or a.slug
        _report(f"[bold]{slug}[/bold]")

        repo_map = await build_repo_map(client, slug)

        # Separate students with repos from those to skip
        skipped_this_round = 0

        async def _clone_student(repo_url: str, dest: Path) -> str:
            return await asyncio.to_thread(_clone_or_pull, repo_url, dest)

        coros: dict[str, typing.Coroutine[typing.Any, typing.Any, str]] = {}
        for student in sorted_students:
            if not student.github_username:
                skipped_this_round += 1
                continue

            repo_name = repo_map.get(student.handle_lower)
            if not repo_name:
                _report(f"  {student.display_name}: no repo")
                skipped_this_round += 1
                continue

            dir_name = student_dir_name(student, sortable_map)
            dest = dest_root / dir_name / slug
            repo_url = f"https://github.com/{repo_name}.git"
            coros[student.display_name] = _clone_student(repo_url, dest)

        counts["skipped"] += skipped_this_round

        def _on_done(result) -> None:  # pyright: ignore[reportUnknownParameterType,reportMissingParameterType]
            if result.error is not None:
                _report(f"  {result.key}: ERROR {result.error}")
            elif result.value != "up-to-date":
                _report(f"  {result.key}: {result.value}")

        results = await gather_bounded(coros, max_concurrent=8, on_complete=_on_done)

        for r in results:
            if r.error is not None:
                counts["errors"] += 1
            else:
                status_key = (r.value or "").replace("-", "_")
                if status_key in counts:
                    counts[status_key] += 1

    return counts
