from __future__ import annotations

import pytest
import typer

from cass.cli import prompts


@pytest.fixture
def no_prompt(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("typer.confirm must not be called")

    monkeypatch.setattr(typer, "confirm", fail)


def test_dry_run_skips_prompt(no_prompt):
    assert prompts.confirm("Delete?", yes=False, dry_run=True) is None


def test_yes_skips_prompt(no_prompt):
    assert prompts.confirm("Delete?", yes=True) is None


def test_non_tty_without_yes_exits_1(monkeypatch, no_prompt, capsys):
    monkeypatch.setattr(prompts, "_stdin_is_tty", lambda: False)
    with pytest.raises(typer.Exit) as exc:
        prompts.confirm("Delete?", yes=False)
    assert exc.value.exit_code == 1
    assert "--yes" in capsys.readouterr().err


def test_tty_decline_aborts(monkeypatch):
    monkeypatch.setattr(prompts, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)
    with pytest.raises(typer.Abort):
        prompts.confirm("Delete?", yes=False)


def test_tty_accept_returns(monkeypatch):
    monkeypatch.setattr(prompts, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
    assert prompts.confirm("Delete?", yes=False) is None
