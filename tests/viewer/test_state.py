"""Tests for viewer startup state detection."""

from __future__ import annotations

__docformat__ = "google"

import pytest

from cass.actions.config import reset_config
from cass.viewer.nicegui_app import _detect_state


@pytest.fixture(autouse=True)
def _reset_config_cache():
    yield
    reset_config()


class TestDetectState:
    def test_setup_when_no_config(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert _detect_state() == "setup"

    def test_pull_when_config_but_no_db(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        assert _detect_state() == "pull"

    def test_ready_when_db_exists(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        (tmp_path / "cass.db").write_bytes(b"")
        monkeypatch.chdir(tmp_path)
        assert _detect_state() == "ready"
