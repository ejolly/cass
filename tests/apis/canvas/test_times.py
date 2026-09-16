"""Tests for course-local time parsing and formatting."""

from __future__ import annotations

__docformat__ = "google"

import pytest

from cass.apis.canvas.times import format_when, parse_when, same_instant

LA = "America/Los_Angeles"


class TestParseWhen:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2026-09-25", "2026-09-25T00:00:00-07:00"),
            ("2026-09-25 14:15", "2026-09-25T14:15:00-07:00"),
            ("2026-09-25T14:15", "2026-09-25T14:15:00-07:00"),
            ("2026-12-01 09:00", "2026-12-01T09:00:00-08:00"),
            ("2026-09-25T14:15:00-07:00", "2026-09-25T14:15:00-07:00"),
            ("2026-09-25T21:15:00Z", "2026-09-25T21:15:00Z"),
        ],
    )
    def test_forms(self, value, expected):
        assert parse_when(value, LA) == expected

    def test_dst_boundary(self):
        assert parse_when("2026-03-08 01:30", LA).endswith("-08:00")
        assert parse_when("2026-03-08 03:30", LA).endswith("-07:00")

    def test_empty_passes_through(self):
        assert parse_when("", LA) == ""

    def test_bad_value(self):
        with pytest.raises(RuntimeError, match="Unrecognized time"):
            parse_when("next friday", LA)

    def test_missing_tz(self):
        with pytest.raises(RuntimeError, match="time zone"):
            parse_when("2026-09-25", "")


class TestFormatWhen:
    def test_inverse(self):
        assert format_when("2026-09-26T00:00:00Z", LA) == "2026-09-25 17:00"
        assert format_when("2026-09-26T00:00:00Z", LA, date_only=True) == "2026-09-25"
        assert format_when("", LA) == ""
        assert format_when(None, LA) == ""

    def test_round_trip(self):
        assert format_when(parse_when("2026-09-25 14:15", LA), LA) == "2026-09-25 14:15"


class TestSameInstant:
    def test_offset_forms_match(self):
        assert same_instant("2026-10-01T23:59:00-07:00", "2026-10-02T06:59:00Z")
        assert same_instant("", None)
        assert not same_instant("2026-10-01T23:59:00Z", None)
