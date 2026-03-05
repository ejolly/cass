"""Download student assignment files from GitHub repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

import msgspec

from .classroom import build_repo_map
from .config import get_config
from .gh import api_cached
from .models import Assignment, GHContentItem, Student

console = Console()

_CODE_EXTS = {".py", ".qmd"}
_PDF_EXTS = {".pdf"}

# Download destination: {project_root}/students/{student}/{assignment}/
STUDENTS_DIR = "students"

_FINAL_PROJECT_SLUG = "final-project"


def _student_dir(student: Student) -> str:
    return student.identifier.lower().replace(" ", "-")


def _download_file(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-sL", "-o", str(dest), url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        if dest.exists():
            dest.unlink()
        return False
    return True


def _list_contents(
    repo_short: str,
    path: str = "",
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> list[GHContentItem]:
    cfg = get_config()
    endpoint = f"/repos/{cfg.org}/{repo_short}/contents/{path}".rstrip("/")
    try:
        data = api_cached(endpoint, ttl_hours=ttl_hours, force_refresh=force_refresh)
    except RuntimeError:
        return []
    if not isinstance(data, list):
        return []
    return msgspec.convert(data, list[GHContentItem])


def fetch_assignment(
    assignment: Assignment,
    students: list[Student],
    force: bool = False,
    limit: int = 0,
    ttl_hours: float = 6,
    force_refresh: bool = False,
) -> None:
    """Download files for one assignment across all students."""
    repo_map = build_repo_map(
        assignment, ttl_hours=ttl_hours, force_refresh=force_refresh
    )
    is_final = assignment.slug == _FINAL_PROJECT_SLUG
    dest_root = get_config().root / STUDENTS_DIR

    downloaded = 0
    skipped = 0
    errors = 0

    sorted_students = sorted(students, key=lambda s: s.identifier.lower())
    if limit > 0:
        sorted_students = sorted_students[:limit]

    for student in sorted_students:
        repo_short = repo_map.get(student.handle_lower)
        if not repo_short:
            console.print(f"  [dim]{student.identifier}: no repo[/dim]")
            errors += 1
            continue

        student_slug = _student_dir(student)
        dest_dir = dest_root / student_slug / assignment.slug

        if is_final:
            contents = _list_contents(
                repo_short, "pdfs", ttl_hours=ttl_hours, force_refresh=force_refresh
            )
            if not contents:
                console.print(f"  [dim]{student.identifier}: no pdfs/ dir[/dim]")
                errors += 1
                continue
            target_exts = _PDF_EXTS
        else:
            contents = _list_contents(
                repo_short, "", ttl_hours=ttl_hours, force_refresh=force_refresh
            )
            if not contents:
                console.print(f"  [dim]{student.identifier}: empty repo[/dim]")
                errors += 1
                continue
            target_exts = _CODE_EXTS

        for item in contents:
            if item.type != "file":
                continue
            ext = Path(item.name).suffix.lower()
            if ext not in target_exts:
                continue

            dest_path = dest_dir / item.name
            if dest_path.exists() and not force:
                skipped += 1
                continue

            if not item.download_url:
                continue
            download_url = item.download_url

            if _download_file(download_url, dest_path):
                downloaded += 1
            else:
                console.print(
                    f"  [red]{student.identifier}: failed to download {item.name}[/red]"
                )
                errors += 1

    console.print(
        f"  [green]{downloaded} downloaded[/green], "
        f"[dim]{skipped} skipped[/dim], "
        f"[red]{errors} errors[/red]"
    )
