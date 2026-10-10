"""Tests for copying the packaged agent skill."""

from __future__ import annotations

__docformat__ = "google"

from importlib.resources import files
from pathlib import Path

import pytest

from cass.actions.skill import install_skill, skill_files


def _package_skill() -> dict[str, bytes]:
    return dict(skill_files())


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_skill_files_include_skill_md():
    paths = {path for path, _ in skill_files()}
    assert "SKILL.md" in paths


def test_install_copies_the_tree(tmp_path):
    target = install_skill(tmp_path, replace=False)

    assert target == tmp_path / "cass"
    assert _tree(target) == _package_skill()


def test_installed_skill_md_matches_package_copy(tmp_path):
    target = install_skill(tmp_path, replace=False)

    packaged = (files("cass") / "skill" / "SKILL.md").read_bytes()
    assert (target / "SKILL.md").read_bytes() == packaged


def test_existing_target_without_replace_raises(tmp_path):
    (tmp_path / "cass").mkdir()
    (tmp_path / "cass" / "old.md").write_text("old")

    with pytest.raises(FileExistsError):
        install_skill(tmp_path, replace=False)

    assert (tmp_path / "cass" / "old.md").read_text() == "old"


def test_replace_removes_stale_files(tmp_path):
    (tmp_path / "cass").mkdir()
    (tmp_path / "cass" / "old.md").write_text("old")

    target = install_skill(tmp_path, replace=True)

    assert _tree(target) == _package_skill()


def test_install_creates_missing_parent_dirs(tmp_path):
    target = install_skill(tmp_path / "a" / "b", replace=False)

    assert (target / "SKILL.md").is_file()
