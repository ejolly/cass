"""``cass skill`` — install the agent skill that ships with cass."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

import typer

skill_app = typer.Typer(
    no_args_is_help=True,
    help="Agent skill — install the Claude Code skill that ships with cass.",
)


@skill_app.command()
def install(
    directory: str = typer.Option(
        "",
        "--dir",
        help="Skills directory to install into (default: ~/.claude/skills)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Replace without asking"),
) -> None:
    """Copy the cass skill to DIR/cass, asking before replacing an old copy."""
    from ..actions.skill import SKILL_NAME, default_skills_dir, install_skill
    from .prompts import confirm

    target_dir = Path(directory).expanduser() if directory else default_skills_dir()
    exists = (target_dir / SKILL_NAME).exists()
    if exists:
        confirm(f"Replace the existing skill at {target_dir / SKILL_NAME}?", yes=yes)
    target = install_skill(target_dir, replace=exists)
    typer.echo(f"Installed: {target}")
