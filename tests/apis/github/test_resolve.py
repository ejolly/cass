"""Tests for GitHub Classroom resolution via REST API.

Covers the new resolve_classroom_direct() path that uses ``gh api /classrooms``
instead of ``gh classroom list``, and the shared ClassroomResolutionResult.
"""

from __future__ import annotations

__docformat__ = "google"

import json
import subprocess

from cass.actions.config import parse_classroom_url
from cass.apis.github.service import resolve_classroom_direct

# --- Helpers ----------------------------------------------------------------


def _fake_subprocess_for_api(
    classrooms_json: list[dict[str, object]],
    detail_json: dict[str, object] | None = None,
    auth_account: str = "ejolly",
    auth_ok: bool = True,
) -> object:
    """Build a monkeypatch-ready ``subprocess.run`` that fakes ``gh`` calls."""

    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        cmd = " ".join(args)

        # gh auth status
        if "auth" in cmd and "status" in cmd:
            if auth_ok:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout="",
                    stderr=f"Logged in to github.com account {auth_account} (keyring)",
                )
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="",
                stderr="The token in default is invalid.",
            )

        # gh auth token
        if "auth" in cmd and "token" in cmd:
            if auth_ok:
                return subprocess.CompletedProcess(
                    args, 0, stdout="gho_fake_token\n", stderr=""
                )
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="",
                stderr="The token in default is invalid.",
            )

        # gh api /classrooms/{id}
        if "api" in cmd and "/classrooms/" in cmd:
            # Extract the classroom ID from the URL
            for a in args:
                if a.startswith("/classrooms/"):
                    cid = int(a.split("/")[-1])
                    if detail_json and detail_json.get("id") == cid:
                        return subprocess.CompletedProcess(
                            args, 0, stdout=json.dumps(detail_json), stderr=""
                        )
                    # Check in the list
                    for c in classrooms_json:
                        if c.get("id") == cid:
                            return subprocess.CompletedProcess(
                                args, 0, stdout=json.dumps(c), stderr=""
                            )
                    return subprocess.CompletedProcess(
                        args,
                        1,
                        stdout="",
                        stderr='{"message":"Not Found","status":"404"}',
                    )

        # gh api /classrooms
        if "api" in cmd and "/classrooms" in cmd:
            return subprocess.CompletedProcess(
                args, 0, stdout=json.dumps(classrooms_json), stderr=""
            )

        raise AssertionError(f"Unexpected subprocess call: {args}")

    return fake_run


# --- Tests: parse_classroom_url ---------------------------------------------


class TestParseClassroomUrl:
    def test_valid_url_returns_numeric_id(self):
        assert (
            parse_classroom_url(
                "https://classroom.github.com/classrooms/232475786-201b-w26"
            )
            == 232475786
        )

    def test_url_without_slug(self):
        assert (
            parse_classroom_url("https://classroom.github.com/classrooms/123456")
            == 123456
        )

    def test_malformed_url_returns_none(self):
        assert parse_classroom_url("https://github.com/org/repo") is None

    def test_empty_string_returns_none(self):
        assert parse_classroom_url("") is None


# --- Tests: resolve_classroom_direct ----------------------------------------


class TestResolveClassroomDirect:
    """Test the new REST API-based resolution path."""

    def test_resolves_successfully_via_api_list(self, monkeypatch):
        """Valid URL resolves even when gh classroom list would not work."""
        classrooms = [
            {
                "id": 299058,
                "name": "201b-W26",
                "archived": False,
                "url": "https://classroom.github.com/classrooms/232475786-201b-w26",
                "organization": {
                    "id": 232475786,
                    "login": "psyc-201",
                },
            }
        ]
        detail = {
            "id": 299058,
            "name": "201b-W26",
            "archived": False,
            "url": "https://classroom.github.com/classrooms/232475786-201b-w26",
            "organization": {
                "id": 232475786,
                "login": "psyc-201",
            },
        }
        monkeypatch.setattr(
            "subprocess.run",
            _fake_subprocess_for_api(classrooms, detail),
        )

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/232475786-201b-w26"
        )

        assert result.resolved is not None
        assert result.resolved.url_id == 232475786
        assert result.resolved.gh_id == 299058
        assert result.resolved.org == "psyc-201"
        assert result.gh_account == "ejolly"
        assert result.error_code == ""

    def test_invalid_auth_returns_pending_with_auth_message(self, monkeypatch):
        """Invalid auth returns a pending result with specific recovery message."""
        monkeypatch.setattr(
            "subprocess.run",
            _fake_subprocess_for_api([], auth_ok=False),
        )

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/232475786-201b-w26"
        )

        assert result.resolved is None
        assert result.url_id == 232475786
        assert result.error_code == "gh_auth_invalid"
        assert "gh auth login" in result.recovery_hint

    def test_classroom_not_in_list_returns_pending(self, monkeypatch):
        """Classroom exists but user has no access — returns pending."""
        other_classrooms = [
            {
                "id": 111,
                "name": "Other Course",
                "archived": False,
                "url": "https://classroom.github.com/classrooms/999-other-course",
                "organization": {"id": 999, "login": "other-org"},
            }
        ]
        monkeypatch.setattr(
            "subprocess.run",
            _fake_subprocess_for_api(other_classrooms),
        )

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/232475786-201b-w26"
        )

        assert result.resolved is None
        assert result.url_id == 232475786
        assert result.error_code == "classroom_no_access"
        assert result.gh_account == "ejolly"

    def test_malformed_url_fails_before_api_call(self, monkeypatch):
        """Malformed URL fails at parse time, no API calls made."""
        call_count = 0

        def no_calls(args, **_kw):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", no_calls)

        result = resolve_classroom_direct("https://github.com/org/repo")

        assert result.resolved is None
        assert result.error_code == "classroom_url_invalid"
        assert call_count == 0

    def test_api_response_missing_optional_fields(self, monkeypatch):
        """API response without org details still yields a resolved config."""
        classrooms = [
            {
                "id": 42,
                "name": "Minimal Course",
                "archived": False,
                "url": "https://classroom.github.com/classrooms/100-minimal",
            }
        ]
        monkeypatch.setattr(
            "subprocess.run",
            _fake_subprocess_for_api(classrooms),
        )

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/100-minimal"
        )

        assert result.resolved is not None
        assert result.resolved.gh_id == 42
        assert result.resolved.url_id == 100
        assert result.resolved.org == ""

    def test_gh_missing_returns_error(self, monkeypatch):
        """gh CLI not installed returns appropriate error."""
        monkeypatch.setattr("shutil.which", lambda _cmd: None)

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/232475786-201b-w26"
        )

        assert result.resolved is None
        assert result.error_code == "gh_missing"

    def test_empty_classroom_list_returns_no_access(self, monkeypatch):
        """Empty classroom list means no classrooms accessible."""
        monkeypatch.setattr(
            "subprocess.run",
            _fake_subprocess_for_api([]),
        )

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/232475786-201b-w26"
        )

        assert result.resolved is None
        assert result.error_code == "classroom_no_access"

    def test_preserves_slug_from_url(self, monkeypatch):
        """Slug extracted from URL is preserved in resolved result."""
        classrooms = [
            {
                "id": 299058,
                "name": "201b-W26",
                "url": "https://classroom.github.com/classrooms/232475786-201b-w26",
                "organization": {"id": 232475786, "login": "psyc-201"},
            }
        ]
        monkeypatch.setattr(
            "subprocess.run",
            _fake_subprocess_for_api(classrooms),
        )

        result = resolve_classroom_direct(
            "https://classroom.github.com/classrooms/232475786-201b-w26"
        )

        assert result.resolved is not None
        assert result.resolved.slug == "201b-w26"
        assert result.resolved.title == "201b-W26"
