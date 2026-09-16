"""Tests for scripts/release.py argument handling."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"


def _load():
    spec = importlib.util.spec_from_file_location("release_script", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_args_defaults_to_derived_version():
    release = _load()
    assert release.parse_args([]) == (None, False)


@pytest.mark.parametrize("level", ["patch", "minor", "major"])
def test_parse_args_accepts_bump_levels(level):
    release = _load()
    assert release.parse_args([level]) == (level, False)


def test_parse_args_accepts_explicit_semver_and_dry_run():
    release = _load()
    assert release.parse_args(["1.2.3", "--dry-run"]) == ("1.2.3", True)


def test_parse_args_rejects_unknown_argument():
    release = _load()
    with pytest.raises(SystemExit):
        release.parse_args(["--yolo"])


def test_restore_release_files_resets_index_and_worktree(tmp_path):
    release = _load()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    for name in release.RELEASE_FILES:
        (tmp_path / name).write_text("original\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    for name in release.RELEASE_FILES:
        (tmp_path / name).write_text("bumped\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    release.restore_release_files(tmp_path)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""
    assert all(
        (tmp_path / name).read_text() == "original\n" for name in release.RELEASE_FILES
    )
