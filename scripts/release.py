#!/usr/bin/env python
"""Cut a cass release: bump version, regenerate changelog, commit, tag, push.

Publishing to PyPI and creating the GitHub Release happen in GitHub Actions
(.github/workflows/release.yml) once the tag reaches origin.

Usage:
    uv run poe release              # next version derived from commit types
    uv run poe release minor        # force a bump level: patch | minor | major
    uv run poe release 1.0.0        # explicit version
    uv run poe release --dry-run    # print the plan and change nothing
"""

from __future__ import annotations

__docformat__ = "google"

import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUMP_LEVELS = ("patch", "minor", "major")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
RELEASE_FILES = ("pyproject.toml", "uv.lock", "CHANGELOG.md")

console = Console()


def abort(msg: str) -> None:
    console.print(f"\n[bold red]Aborted:[/] {msg}")
    sys.exit(1)


def confirm(prompt: str) -> bool:
    try:
        answer = console.input(f"\n{prompt} [bold]\\[y/N][/] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def run(cmd: list[str]) -> str:
    """Run a command in the project root and return stripped stdout; abort on failure."""
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        abort(f"{' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def restore_release_files(root: Path) -> None:
    """Reset the release files in both index and worktree to HEAD after a failed release commit."""
    subprocess.run(["git", "checkout", "HEAD", "--", *RELEASE_FILES], cwd=root, check=False)


def parse_args(argv: list[str]) -> tuple[str | None, bool]:
    """Return (target, dry_run). target is None, a bump level, or an X.Y.Z version."""
    target: str | None = None
    dry_run = False
    for arg in argv:
        if arg == "--dry-run":
            dry_run = True
        elif arg in BUMP_LEVELS or SEMVER.match(arg):
            target = arg
        else:
            abort(f"Unknown argument {arg!r}. Use: [patch|minor|major|X.Y.Z] [--dry-run]")
    return target, dry_run


def preflight() -> None:
    """Fail early on anything that would make the release commit wrong."""
    if shutil.which("git-cliff") is None:
        abort("git-cliff is not installed. Run: brew install git-cliff")
    if run(["git", "status", "--porcelain", "--untracked-files=no"]):
        abort("Working tree has uncommitted changes.")
    if run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) != "main":
        abort("Releases are cut from main.")
    run(["git", "fetch", "origin", "main", "--tags"])
    if run(["git", "rev-parse", "HEAD"]) != run(["git", "rev-parse", "origin/main"]):
        abort("main is not in sync with origin/main. Pull or push first.")


def next_version(target: str | None) -> str:
    """Resolve the version to release from an optional level or explicit version."""
    if target is None:
        return run(["git", "cliff", "--bumped-version"]).removeprefix("v")
    if target in BUMP_LEVELS:
        return run(["git", "cliff", "--bumped-version", "--bump", target]).removeprefix("v")
    return target


def show_plan(current: str, version: str, tag: str, dry_run: bool) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Current", current)
    table.add_row("Release", f"[bold green]{version}[/]")
    table.add_row("Tag", tag)
    table.add_row("Changelog", "CHANGELOG.md regenerated with git-cliff")
    table.add_row("Commit", f"chore(release): {tag}")
    table.add_row("Publish", "GitHub Actions on tag push (release.yml)")
    if dry_run:
        table.add_row("Mode", "[yellow]dry run, nothing will change[/]")
    console.print(table)


def main() -> None:
    target, dry_run = parse_args(sys.argv[1:])
    console.print(Panel("[bold]cass release[/]", style="bold magenta"))

    preflight()
    current = run(["uv", "version", "--short"])
    version = next_version(target)
    if version == current:
        abort(f"Next version {version} equals the current version. Nothing to release.")
    tag = f"v{version}"
    if run(["git", "tag", "--list", tag]):
        abort(f"Tag {tag} already exists.")

    show_plan(current, version, tag, dry_run)
    if dry_run:
        return

    console.print(Panel("[bold]Gate: uv run poe ok[/]", style="blue"))
    gate = subprocess.run(["uv", "run", "poe", "ok"], cwd=PROJECT_ROOT)
    if gate.returncode != 0:
        abort("uv run poe ok failed.")
    if run(["git", "status", "--porcelain", "--untracked-files=no"]):
        abort("poe ok modified files (formatting). Commit them, then rerun.")

    if not confirm(f"Create release commit and tag {tag}?"):
        abort("Cancelled. Nothing changed.")

    try:
        run(["uv", "version", version])
        run(["git", "cliff", "--tag", tag, "-o", "CHANGELOG.md"])
        run(["git", "add", *RELEASE_FILES])
        run(["git", "commit", "-m", f"chore(release): {tag}"])
        run(["git", "tag", "-a", tag, "-m", f"cassroom {version}"])
    except SystemExit:
        restore_release_files(PROJECT_ROOT)
        console.print(f"  Restored {', '.join(RELEASE_FILES)} to HEAD.")
        raise
    console.print(f"  Committed and tagged [bold]{tag}[/]")

    if confirm("Push main and the tag to origin? This publishes to PyPI."):
        run(["git", "push", "origin", "main"])
        run(["git", "push", "origin", tag])
        console.print(
            Panel(
                f"[bold green]{tag} pushed.[/] Watch the release: gh run watch",
                style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"Not pushed. When ready:\n  git push origin main && git push origin {tag}",
                style="yellow",
            )
        )


if __name__ == "__main__":
    main()
