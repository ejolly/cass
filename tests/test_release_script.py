"""Tests for scripts/release.py argument handling."""

from __future__ import annotations

import importlib.util
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
