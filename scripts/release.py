#!/usr/bin/env python
"""cass release orchestrator.

Workflow: run tests, bump version, build, publish to PyPI/TestPyPI,
commit + tag.

Usage:
    uv run poe release              # PyPI (default), patch bump
    uv run poe release testpypi     # TestPyPI
    uv run poe release pypi minor   # minor version bump
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
DIST_DIR = PROJECT_ROOT / "dist"

VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)

PYPI_URL = "https://pypi.org/pypi/cassroom/json"
TESTPYPI_URL = "https://test.pypi.org/pypi/cassroom/json"

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def abort(msg: str) -> None:
    console.print(f"\n[bold red]Aborted:[/] {msg}")
    sys.exit(1)


def confirm(prompt: str) -> bool:
    try:
        answer = console.input(f"\n{prompt} [bold]\\[y/N][/] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=merged_env,
        capture_output=capture,
        text=True,
    )


def parse_version(text: str) -> str:
    m = VERSION_RE.search(text)
    if not m:
        abort("Cannot parse version from pyproject.toml")
    return m.group(1)


def bump_version(version: str, part: str) -> str:
    """Bump a semver version string.

    Args:
        version: Current version like "0.2.0" or "0.2.0.dev3"
        part: "patch", "minor", or "major"
    """
    # Strip any dev/pre suffix for bumping
    base = re.sub(r"(\.dev\d+|a\d+|b\d+|rc\d+)$", "", version)
    parts = base.split(".")
    if len(parts) != 3:
        abort(f"Version {version!r} is not semver (major.minor.patch)")

    major, minor, patch = (int(p) for p in parts)

    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def fetch_pypi_version(index_url: str) -> str | None:
    try:
        with urlopen(index_url, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("info", {}).get("version")
    except (URLError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_tests() -> bool:
    """Step 1: Run lint + tests."""
    console.print(Panel("[bold]Step 1: Lint & Tests[/]", style="blue"))

    console.print("  Running lint...")
    result = run(["uv", "run", "poe", "lint"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        console.print("  [bold red]Lint failed[/]")
        if not confirm("Continue despite lint failure?"):
            abort("Fix lint issues before releasing.")

    console.print("  Running tests...")
    result = run(["uv", "run", "poe", "test"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        console.print("  [bold red]Tests failed[/]")
        if not confirm("Continue despite test failure?"):
            abort("Fix test failures before releasing.")
        return False

    console.print("  [green]All checks passed[/]")
    return True


def step_version_review(target: str, bump_part: str) -> tuple[str, str]:
    """Step 2: Review versions and determine next version."""
    console.print(Panel("[bold]Step 2: Version Review[/]", style="blue"))

    source_version = parse_version(PYPROJECT.read_text())

    index_url = TESTPYPI_URL if target == "testpypi" else PYPI_URL
    pypi_version = fetch_pypi_version(index_url) or "not published"
    next_version = bump_version(source_version, bump_part)

    table = Table(show_header=True, header_style="bold")
    table.add_column("", style="cyan")
    table.add_column("Version")
    target_label = "TestPyPI" if target == "testpypi" else "PyPI"
    table.add_row(f"Published ({target_label})", str(pypi_version))
    table.add_row("Source (current)", source_version)
    table.add_row(f"Next ({bump_part} bump)", f"[bold green]{next_version}[/]")
    console.print(table)

    custom = console.input(
        f"\nAccept [bold]{next_version}[/] or enter custom version (Enter to accept): "
    ).strip()
    if custom:
        next_version = custom

    return source_version, next_version


def step_bump_version(old_version: str, new_version: str) -> None:
    """Step 3: Bump version in pyproject.toml."""
    console.print(Panel("[bold]Step 3: Bump Version[/]", style="blue"))

    text = PYPROJECT.read_text()
    new_text = text.replace(f'version = "{old_version}"', f'version = "{new_version}"')
    if new_text == text:
        abort(f"Failed to replace version in {PYPROJECT}")
    PYPROJECT.write_text(new_text)
    console.print(f"  pyproject.toml: [red]{old_version}[/] -> [green]{new_version}[/]")


def step_build() -> list[str]:
    """Step 4: Build sdist + wheel."""
    console.print(Panel("[bold]Step 4: Build Package[/]", style="blue"))

    result = run(["uv", "build", "--clear"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        abort("uv build failed")

    artifacts = sorted(DIST_DIR.iterdir())
    wheels = [f for f in artifacts if f.suffix == ".whl"]
    sdists = [f for f in artifacts if f.name.endswith(".tar.gz")]

    if len(wheels) != 1 or len(sdists) != 1:
        abort(
            f"Expected 1 wheel + 1 sdist, found "
            f"{len(wheels)} wheels and {len(sdists)} sdists"
        )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Artifact", style="cyan")
    table.add_column("Size", justify="right")
    for f in [wheels[0], sdists[0]]:
        size_kb = f.stat().st_size / 1024
        table.add_row(f.name, f"{size_kb:.0f} KB")
    console.print(table)

    return [f.name for f in [wheels[0], sdists[0]]]


def step_confirm(
    old_version: str,
    new_version: str,
    target: str,
    artifacts: list[str],
    tests_ok: bool,
) -> bool:
    """Step 5: Show summary and get final confirmation."""
    console.print(Panel("[bold]Step 5: Release Summary[/]", style="blue"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()

    target_label = "TestPyPI" if target == "testpypi" else "PyPI"
    table.add_row("Version", f"{old_version} -> [bold green]{new_version}[/]")
    table.add_row("Target", target_label)
    for a in artifacts:
        table.add_row("Artifact", a)
    tests_status = "[green]PASSED[/]" if tests_ok else "[red]FAILED[/]"
    table.add_row("Tests", tests_status)

    console.print(table)

    return confirm(f"Publish {new_version} to {target_label}?")


def step_publish(target: str) -> None:
    """Step 6: Publish to PyPI or TestPyPI."""
    console.print(Panel("[bold]Step 6: Publish[/]", style="blue"))

    env_file = PROJECT_ROOT / (
        f".env.{target}" if target == "testpypi" else ".env.pypi"
    )
    if not env_file.exists():
        abort(
            f"Token file {env_file} not found. "
            f"Copy .env.example to {env_file.name} and add your token."
        )

    # Parse env file
    publish_env: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            publish_env[key.strip()] = value.strip()

    cmd = ["uv", "publish"]
    if target == "testpypi":
        cmd.extend(["--index", "testpypi"])

    target_label = "TestPyPI" if target == "testpypi" else "PyPI"
    console.print(f"  Publishing to {target_label}...")
    result = run(cmd, cwd=PROJECT_ROOT, env=publish_env)

    if result.returncode == 0:
        console.print(f"\n[bold green]Published to {target_label}![/]")
    else:
        abort("uv publish failed")


def step_git_commit_and_tag(new_version: str) -> None:
    """Step 7: Commit version bump and create git tag."""
    console.print(Panel("[bold]Step 7: Git Commit & Tag[/]", style="blue"))

    tag = f"v{new_version}"

    result = run(["git", "add", "pyproject.toml"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        abort("git add failed")

    result = run(["git", "commit", "-m", f"release: {tag}"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        abort("git commit failed")
    console.print(f"  Committed: [bold]release: {tag}[/]")

    result = run(["git", "tag", tag], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        abort(f"git tag {tag} failed")
    console.print(f"  Tagged: [bold]{tag}[/]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    target = "pypi"
    bump_part = "patch"

    args = sys.argv[1:]
    for arg in args:
        if arg.lower() in ("pypi", "testpypi"):
            target = arg.lower()
        elif arg.lower() in ("patch", "minor", "major"):
            bump_part = arg.lower()
        else:
            abort(f"Unknown argument {arg!r}. Use: [pypi|testpypi] [patch|minor|major]")

    target_label = "TestPyPI" if target == "testpypi" else "PyPI"
    console.print(
        Panel(
            f"[bold]cass release -> {target_label} ({bump_part} bump)[/]",
            style="bold magenta",
        )
    )

    # Step 1: Lint + tests
    tests_ok = step_tests()

    # Step 2: Version review
    old_version, new_version = step_version_review(target, bump_part)

    # Step 3: Bump version
    step_bump_version(old_version, new_version)

    # Step 4: Build
    artifacts = step_build()

    # Step 5: Confirmation
    approved = step_confirm(old_version, new_version, target, artifacts, tests_ok)
    if not approved:
        console.print("\n[yellow]Release cancelled. Version bump remains in place.[/]")
        console.print(
            f"  To revert: change version back to {old_version} in pyproject.toml"
        )
        sys.exit(0)

    # Step 6: Publish
    step_publish(target)

    # Step 7: Git commit + tag
    step_git_commit_and_tag(new_version)

    console.print(
        Panel(
            f"[bold green]Release v{new_version} complete![/]\n"
            f"Published to {target_label}, committed, and tagged.\n"
            f"Don't forget to push: git push && git push --tags",
            style="green",
        )
    )


if __name__ == "__main__":
    main()
