"""Tests for viewer setup helpers and unresolved Classroom flow."""

from __future__ import annotations

__docformat__ = "google"

import asyncio

import pytest

from cass.actions.config import reset_config
from cass.apis.github.service import (
    ClassroomResolutionResult,
    ResolvedClassroom,
)
from cass.viewer.nicegui_app import _detect_state
from cass.viewer.setup import resolve_viewer_classroom_setup


@pytest.fixture(autouse=True)
def _reset_config_cache():
    yield
    reset_config()


class TestViewerSetupResolution:
    def test_resolve_viewer_classroom_setup_keeps_partial_on_failure(
        self, monkeypatch
    ) -> None:
        def fake_resolve(_url: str) -> ClassroomResolutionResult:
            return ClassroomResolutionResult(
                url=_url,
                url_id=42,
                error_code="gh_auth_invalid",
                error_detail="GitHub authentication is invalid.",
                recovery_hint="Run `gh auth login -h github.com`.",
            )

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            fake_resolve,
        )

        result = asyncio.run(
            resolve_viewer_classroom_setup(
                "https://classroom.github.com/classrooms/42-test-course"
            )
        )

        assert result.classroom_url_id == 42
        assert result.classroom_gh_id == 0
        assert result.warning == (
            "GitHub authentication is invalid. Run `gh auth login -h github.com`."
        )

    def test_resolve_viewer_classroom_setup_returns_resolved_values(
        self, monkeypatch
    ) -> None:
        def fake_resolve(url: str) -> ClassroomResolutionResult:
            return ClassroomResolutionResult(
                url=url,
                url_id=42,
                resolved=ResolvedClassroom(
                    url=url,
                    url_id=42,
                    gh_id=4200,
                    slug="test-course",
                    title="Test Course",
                    org="test-org",
                ),
                gh_account="ejolly",
            )

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            fake_resolve,
        )

        result = asyncio.run(
            resolve_viewer_classroom_setup(
                "https://classroom.github.com/classrooms/42-test-course"
            )
        )

        assert result.classroom_url_id == 42
        assert result.classroom_gh_id == 4200
        assert result.classroom_slug == "test-course"
        assert result.org == "test-org"
        assert result.warning == ""

    def test_viewer_uses_same_resolver_as_cli(self, monkeypatch) -> None:
        """Viewer and CLI both use resolve_classroom_direct (shared path)."""
        calls: list[str] = []

        def tracking_resolve(url: str) -> ClassroomResolutionResult:
            calls.append(url)
            return ClassroomResolutionResult(
                url=url,
                url_id=42,
                resolved=ResolvedClassroom(
                    url=url,
                    url_id=42,
                    gh_id=4200,
                    slug="test-course",
                    title="Test Course",
                    org="test-org",
                ),
                gh_account="ejolly",
            )

        monkeypatch.setattr(
            "cass.apis.github.service.resolve_classroom_direct",
            tracking_resolve,
        )

        asyncio.run(
            resolve_viewer_classroom_setup(
                "https://classroom.github.com/classrooms/42-test-course"
            )
        )

        assert len(calls) == 1
        assert "42-test-course" in calls[0]


class TestViewerStateDetection:
    def test_detect_state_stays_on_setup_when_classroom_needs_resolution(
        self, tmp_path, monkeypatch
    ) -> None:
        (tmp_path / "cass.toml").write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\n"
            "gh_id = 0\n"
            '\n[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)

        assert _detect_state() == "setup"
