"""``cass skill install`` CLI tests."""

from __future__ import annotations

__docformat__ = "google"

import typer
from typer.testing import CliRunner

from cass.cli import app, prompts

runner = CliRunner()


def _seed_existing(tmp_path):
    (tmp_path / "cass").mkdir()
    stale = tmp_path / "cass" / "old.md"
    stale.write_text("old")
    return stale


def test_install_into_dir(tmp_path):
    result = runner.invoke(app, ["skill", "install", "--dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "cass" / "SKILL.md").is_file()
    assert f"Installed: {tmp_path / 'cass'}" in result.stdout.replace("\n", "")


def test_existing_target_asks_and_decline_keeps_it(tmp_path, monkeypatch):
    stale = _seed_existing(tmp_path)
    asked: list[str] = []
    monkeypatch.setattr(prompts, "_stdin_is_tty", lambda: True)

    def decline(message, **kwargs):
        asked.append(message)
        return False

    monkeypatch.setattr(typer, "confirm", decline)

    result = runner.invoke(app, ["skill", "install", "--dir", str(tmp_path)])

    assert result.exit_code == 1
    assert len(asked) == 1
    assert "Replace" in asked[0]
    assert stale.exists()


def test_existing_target_asks_and_accept_replaces(tmp_path, monkeypatch):
    stale = _seed_existing(tmp_path)
    monkeypatch.setattr(prompts, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)

    result = runner.invoke(app, ["skill", "install", "--dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert (tmp_path / "cass" / "SKILL.md").is_file()


def test_yes_replaces_without_prompt(tmp_path, monkeypatch):
    stale = _seed_existing(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("typer.confirm must not be called")

    monkeypatch.setattr(typer, "confirm", fail)

    result = runner.invoke(app, ["skill", "install", "--dir", str(tmp_path), "--yes"])

    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert (tmp_path / "cass" / "SKILL.md").is_file()


def test_existing_target_without_tty_fails_fast(tmp_path, monkeypatch):
    stale = _seed_existing(tmp_path)
    monkeypatch.setattr(prompts, "_stdin_is_tty", lambda: False)

    result = runner.invoke(app, ["skill", "install", "--dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "--yes" in result.stderr
    assert stale.exists()


def test_default_dir_is_claude_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    result = runner.invoke(app, ["skill", "install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "cass" / "SKILL.md").is_file()
