"""Install the agent skill that ships inside the cass package."""

from __future__ import annotations

__docformat__ = "google"

import shutil
from collections.abc import Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

SKILL_NAME = "cass"


def default_skills_dir() -> Path:
    """Return Claude Code's user skills directory, ``~/.claude/skills``."""
    return Path.home() / ".claude" / "skills"


def _walk(node: Traversable, prefix: str) -> Iterator[tuple[str, bytes]]:
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        path = f"{prefix}{child.name}"
        if child.is_dir():
            if child.name != "__pycache__":
                yield from _walk(child, f"{path}/")
        else:
            yield path, child.read_bytes()


def skill_files() -> list[tuple[str, bytes]]:
    """Return every file in the packaged skill as (relative path, contents)."""
    return list(_walk(files("cass") / "skill", ""))


def install_skill(target_dir: Path, *, replace: bool) -> Path:
    """Copy the packaged skill to ``target_dir/cass`` and return that path.

    Args:
        target_dir: Skills directory to install into; created if missing.
        replace: Delete an existing ``target_dir/cass`` first.

    Raises:
        FileExistsError: The target exists and ``replace`` is false.
    """
    target = target_dir / SKILL_NAME
    if target.exists():
        if not replace:
            raise FileExistsError(target)
        shutil.rmtree(target)
    for relative, data in skill_files():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return target
