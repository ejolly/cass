"""Tests for cass domain models — display helpers and struct methods."""

__docformat__ = "google"

import pytest

from cass.db.schema import (
    GHSubmission,
    Student,
)


class TestStudent:
    @pytest.mark.parametrize(
        "canvas_id, name, github_username, expected",
        [
            (100, "Alice Smith", "", "Alice Smith"),
            (100, "", "alice-gh", "alice-gh"),
            (100, "", "", "100"),
        ],
        ids=["name", "github-fallback", "canvas-id-fallback"],
    )
    def test_display_name(self, canvas_id, name, github_username, expected):
        s = Student(
            canvas_id=canvas_id,
            name=name,
            github_username=github_username,
        )
        assert s.display_name == expected

    def test_handle_lower(self):
        s = Student(canvas_id=100, github_username="AliceSmith")
        assert s.handle_lower == "alicesmith"


class TestGHSubmission:
    def test_with_assignment_slug(self):
        sub = GHSubmission(
            github_username="alice",
            assignment_slug="final-project",
            submitted=True,
        )
        new = sub.with_assignment_slug("proposal")
        assert new.assignment_slug == "proposal"
        assert new.github_username == "alice"
        assert new.submitted is True
