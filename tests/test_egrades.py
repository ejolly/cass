"""Tests for cass.egrades — grading scheme conversion and eGrades export."""

import pytest

from cass.canvas.egrades import EGRADES_HEADER, parse_sortable_name, score_to_letter
from cass.models import CanvasGradingSchemeEntry


# --- Standard UCSD-style grading scheme ---


@pytest.fixture
def ucsd_scheme():
    """UCSD-style grading scheme (A+ through F)."""
    return [
        CanvasGradingSchemeEntry(name="A+", value=0.97),
        CanvasGradingSchemeEntry(name="A", value=0.93),
        CanvasGradingSchemeEntry(name="A-", value=0.90),
        CanvasGradingSchemeEntry(name="B+", value=0.87),
        CanvasGradingSchemeEntry(name="B", value=0.83),
        CanvasGradingSchemeEntry(name="B-", value=0.80),
        CanvasGradingSchemeEntry(name="C+", value=0.77),
        CanvasGradingSchemeEntry(name="C", value=0.73),
        CanvasGradingSchemeEntry(name="C-", value=0.70),
        CanvasGradingSchemeEntry(name="D", value=0.60),
        CanvasGradingSchemeEntry(name="F", value=0.0),
    ]


# --- score_to_letter ---


class TestScoreToLetter:
    def test_a_plus(self, ucsd_scheme):
        assert score_to_letter(97.0, ucsd_scheme) == "A+"
        assert score_to_letter(100.0, ucsd_scheme) == "A+"

    def test_a(self, ucsd_scheme):
        assert score_to_letter(93.0, ucsd_scheme) == "A"
        assert score_to_letter(96.9, ucsd_scheme) == "A"

    def test_a_minus(self, ucsd_scheme):
        assert score_to_letter(90.0, ucsd_scheme) == "A-"

    def test_b_plus(self, ucsd_scheme):
        assert score_to_letter(87.0, ucsd_scheme) == "B+"

    def test_c(self, ucsd_scheme):
        assert score_to_letter(75.0, ucsd_scheme) == "C"

    def test_f(self, ucsd_scheme):
        assert score_to_letter(50.0, ucsd_scheme) == "F"
        assert score_to_letter(0.0, ucsd_scheme) == "F"

    def test_none_score(self, ucsd_scheme):
        assert score_to_letter(None, ucsd_scheme) == ""

    def test_empty_scheme(self):
        assert score_to_letter(95.0, []) == ""

    def test_boundary_exact(self, ucsd_scheme):
        """Exact boundary should earn the higher grade."""
        assert score_to_letter(93.0, ucsd_scheme) == "A"
        assert score_to_letter(90.0, ucsd_scheme) == "A-"
        assert score_to_letter(80.0, ucsd_scheme) == "B-"

    def test_just_below_boundary(self, ucsd_scheme):
        """Just below boundary earns the lower grade."""
        assert score_to_letter(92.99, ucsd_scheme) == "A-"
        assert score_to_letter(89.99, ucsd_scheme) == "B+"


# --- parse_sortable_name ---


class TestParseSortableName:
    def test_normal(self):
        assert parse_sortable_name("Smith, Alice") == ("Smith", "Alice")

    def test_extra_spaces(self):
        assert parse_sortable_name("  Doe ,  Jane  ") == ("Doe", "Jane")

    def test_no_comma(self):
        assert parse_sortable_name("Madonna") == ("Madonna", "")

    def test_multiple_commas(self):
        assert parse_sortable_name("De La Cruz, Maria") == ("De La Cruz", "Maria")

    def test_empty(self):
        assert parse_sortable_name("") == ("", "")


# --- Header constant ---


def test_egrades_header():
    assert EGRADES_HEADER == [
        "Last Name",
        "First Name",
        "Student ID",
        "SectionId",
        "Final_Assigned_Egrade",
    ]
