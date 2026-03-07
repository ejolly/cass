"""Download student repos from GitHub Classroom via git clone/pull.

Clones student forks into ``gh-classroom/{last-first}/{assignment-slug}/``
next to ``cass.toml``. Re-pulls use ``git fetch + reset --hard`` so the
remote always wins — no merge conflicts.
"""

from __future__ import annotations

__docformat__ = "google"

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from ..config import get_config
from ..models import Assignment, Student
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


def _get_sortable_names() -> dict[int, str]:
    """Load canvas_id → sortable_name from the canvas_students table."""
    from .. import db

    conn = db.get_db()
    rows = conn.execute(
        "SELECT canvas_id, sortable_name FROM canvas_students"
    ).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def _student_dir_name(student: Student, sortable_map: dict[int, str]) -> str:
    """Resolve directory name for a student."""
    sortable = sortable_map.get(student.canvas_id, "")
    return sanitize_student_dir(sortable, student.github_username)


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
    dest_root = cfg.root / GH_CLASSROOM_DIR
    sortable_map = _get_sortable_names()

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

        for student in sorted_students:
            if not student.github_username:
                counts["skipped"] += 1
                continue

            repo_short = repo_map.get(student.handle_lower)
            if not repo_short:
                _report(f"  {student.display_name}: no repo")
                counts["skipped"] += 1
                continue

            dir_name = _student_dir_name(student, sortable_map)
            dest = dest_root / dir_name / slug
            repo_url = f"https://github.com/{cfg.org}/{repo_short}.git"

            try:
                status = _clone_or_pull(repo_url, dest)
                counts[status.replace("-", "_")] += 1
                if status != "up-to-date":
                    _report(f"  {student.display_name}: {status}")
            except RuntimeError as exc:
                _report(f"  {student.display_name}: ERROR {exc}")
                counts["errors"] += 1

    return counts
