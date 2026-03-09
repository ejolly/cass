"""Tests for build_preview_html() — Tier 2A pure function tests."""

from __future__ import annotations

__docformat__ = "google"

from cass.viewer.actions import build_preview_html


class TestNormalChanges:
    def test_assignment_table(self):
        """Assignment changes produce a table with correct headers and values."""
        changes = [
            {
                "name": "Homework 1",
                "column": "points_possible",
                "baseline": 10.0,
                "current": 20.0,
                "live": 10.0,
                "conflict": False,
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=False)
        assert "<th>Assignment</th>" in html
        assert "<th>Field</th>" in html
        assert "<th>On Canvas</th>" in html
        assert "<th>New value</th>" in html
        assert "Homework 1" in html
        assert "points_possible" in html
        assert "10.0" in html
        assert "20.0" in html

    def test_grade_table(self):
        """Grade changes produce a table with student-assignment headers."""
        changes = [
            {
                "name": "Alice \u2014 Homework 1",
                "column": "posted_grade",
                "baseline": "9",
                "current": "10",
                "live": "9",
                "conflict": False,
            }
        ]
        html = build_preview_html([], changes, has_conflicts=False)
        assert "Student \u2014 Assignment" in html
        assert "On Canvas" in html
        assert "New grade" in html
        assert "Alice \u2014 Homework 1" in html
        assert "10" in html

    def test_both_tables(self):
        """Both assignment and grade tables appear when both have changes."""
        a_ch = [
            {
                "name": "HW1",
                "column": "due_at",
                "baseline": "old",
                "current": "new",
                "live": "old",
                "conflict": False,
            }
        ]
        g_ch = [
            {
                "name": "Bob \u2014 HW1",
                "column": "posted_grade",
                "baseline": "5",
                "current": "7",
                "live": "5",
                "conflict": False,
            }
        ]
        html = build_preview_html(a_ch, g_ch, has_conflicts=False)
        assert "Assignment changes" in html
        assert "Grade changes" in html

    def test_empty_changes(self):
        """No changes at all returns empty HTML."""
        html = build_preview_html([], [], has_conflicts=False)
        assert html == ""


class TestConflicts:
    def test_conflict_row_css(self):
        """Conflict rows get the conflict-row CSS class."""
        changes = [
            {
                "name": "HW1",
                "column": "points_possible",
                "baseline": 10.0,
                "current": 20.0,
                "live": 15.0,
                "conflict": True,
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=True)
        assert 'class="conflict-row"' in html
        assert "\u26a0" in html  # warning symbol in column cell

    def test_grade_conflict_row(self):
        """Grade conflict rows get conflict-row CSS and warning symbol."""
        changes = [
            {
                "name": "Alice \u2014 HW1",
                "column": "posted_grade",
                "baseline": "9",
                "current": "10",
                "live": "8",
                "conflict": True,
            }
        ]
        html = build_preview_html([], changes, has_conflicts=True)
        assert 'class="conflict-row"' in html
        assert "\u26a0" in html

    def test_warning_banner(self):
        """has_conflicts=True adds the yellow warning banner."""
        html = build_preview_html(
            [
                {
                    "name": "HW1",
                    "column": "name",
                    "baseline": "a",
                    "current": "b",
                    "live": "c",
                    "conflict": True,
                }
            ],
            [],
            has_conflicts=True,
        )
        assert "differ from when you last pulled" in html
        assert "v-conflict-warning" in html

    def test_no_banner(self):
        """has_conflicts=False omits the warning banner."""
        html = build_preview_html(
            [
                {
                    "name": "HW1",
                    "column": "name",
                    "baseline": "a",
                    "current": "b",
                    "live": "a",
                    "conflict": False,
                }
            ],
            [],
            has_conflicts=False,
        )
        assert "differ from when you last pulled" not in html


class TestErrorRows:
    def test_assignment(self):
        """Assignment error rows get error-row CSS and colspan."""
        changes = [
            {
                "name": "HW1",
                "error": "API timeout",
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=False)
        assert 'class="error-row"' in html
        assert 'colspan="4"' in html
        assert "v-text-error" in html
        assert "HW1: API timeout" in html

    def test_grade(self):
        """Grade error rows get error-row CSS and colspan=3."""
        changes = [
            {
                "name": "Homework 1",
                "error": "Connection refused",
            }
        ]
        html = build_preview_html([], changes, has_conflicts=False)
        assert 'class="error-row"' in html
        assert 'colspan="3"' in html
        assert "Connection refused" in html


class TestHtmlEscaping:
    def test_special_chars(self):
        """HTML-special characters in names/values are escaped."""
        changes = [
            {
                "name": '<script>alert("xss")</script>',
                "column": "name",
                "baseline": "old",
                "current": "new & improved",
                "live": "old",
                "conflict": False,
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=False)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp; improved" in html

    def test_error_message(self):
        """Error messages with HTML chars are escaped."""
        changes = [
            {
                "name": "HW1",
                "error": '<img onerror="alert(1)">',
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=False)
        assert "<img" not in html
        assert "&lt;img" in html

    def test_null_values(self):
        """None values display as 'None' (via str()); missing keys as 'null'."""
        changes = [
            {
                "name": "HW1",
                "column": "due_at",
                "baseline": None,
                "current": "2026-03-01",
                "live": None,
                "conflict": False,
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=False)
        # live=None -> str(None) -> "None"
        assert "None" in html

    def test_missing_live_key(self):
        """When 'live' key is absent, fallback 'null' is displayed."""
        changes = [
            {
                "name": "HW1",
                "column": "due_at",
                "baseline": "old",
                "current": "new",
                "conflict": False,
                # no "live" key
            }
        ]
        html = build_preview_html(changes, [], has_conflicts=False)
        assert "null" in html
