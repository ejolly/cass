"""Removed ``cass canvas`` command forms must fail as usage errors."""

from __future__ import annotations

__docformat__ = "google"

import pytest
from typer.testing import CliRunner

from cass.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "args",
    [
        ["canvas", "quizzes", "--id", "20"],
        ["canvas", "modules", "--id", "1"],
        ["canvas", "assignments", "--id", "7"],
    ],
)
def test_old_id_selectors_removed(args):
    assert runner.invoke(app, args).exit_code == 2
