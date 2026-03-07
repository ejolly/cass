"""Tests for cass.classroom — typed struct decoding via msgspec.convert."""

import msgspec
import pytest

from cass.github.fetch import sanitize_student_dir
from cass.models import (
    GHAcceptedAssignment,
    GHAssignment,
    GHCommit,
    GHContentItem,
    GHRosterEntry,
)


def test_convert_gh_assignment():
    data = {
        "id": 123,
        "slug": "hw-01",
        "title": "Homework 01",
        "deadline": "2025-01-15T23:59:00Z",
        "accepted": 25,
        "submissions": 20,
        "passing": 18,
    }
    result = msgspec.convert(data, GHAssignment)
    assert result.id == 123
    assert result.slug == "hw-01"
    assert result.title == "Homework 01"
    assert result.deadline == "2025-01-15T23:59:00Z"
    assert result.accepted == 25
    assert result.submissions == 20
    assert result.passing == 18


def test_convert_accepted_assignment():
    data = {
        "id": 456,
        "students": [{"id": 1, "login": "alice-gh"}, {"id": 2, "login": "bob-gh"}],
        "repository": {"id": 789, "full_name": "my-org/hw-01-alice-gh"},
        "commit_count": 15,
        "submitted": True,
        "passing": True,
        "grade": "10/10",
    }
    result = msgspec.convert(data, GHAcceptedAssignment)
    assert result.id == 456
    assert len(result.students) == 2
    assert result.students[0].login == "alice-gh"
    assert result.repository is not None
    assert result.repository.full_name == "my-org/hw-01-alice-gh"
    assert result.commit_count == 15
    assert result.submitted is True
    assert result.passing is True
    assert result.grade == "10/10"


def test_convert_gh_commit():
    data = {
        "commit": {
            "committer": {"date": "2025-01-16T02:30:00Z"},
        },
    }
    result = msgspec.convert(data, GHCommit)
    assert result.commit.committer.date == "2025-01-16T02:30:00Z"


def test_convert_content_item():
    data = {
        "type": "file",
        "name": "proposal.pdf",
        "download_url": "https://raw.githubusercontent.com/org/repo/main/proposal.pdf",
    }
    result = msgspec.convert(data, GHContentItem)
    assert result.type == "file"
    assert result.name == "proposal.pdf"
    assert result.download_url is not None


def test_convert_roster_entry():
    data = {
        "assignment_name": "wk01-lab",
        "assignment_url": "https://classroom.github.com/classrooms/123/assignments/wk01-lab",
        "starter_code_url": "https://api.github.com/repos/org/starter",
        "github_username": "alice-gh",
        "roster_identifier": "Alice Smith",
        "student_repository_name": "wk01-lab-alice-gh",
        "student_repository_url": "https://github.com/org/wk01-lab-alice-gh",
        "submission_timestamp": "2025-01-07 23:12:11 UTC",
        "points_awarded": "100",
        "points_available": "100",
    }
    result = msgspec.convert(data, GHRosterEntry)
    assert result.github_username == "alice-gh"
    assert result.roster_identifier == "Alice Smith"
    assert result.student_repository_name == "wk01-lab-alice-gh"
    assert result.points_awarded == "100"


def test_convert_roster_entry_minimal():
    data = {"github_username": "bob-gh"}
    result = msgspec.convert(data, GHRosterEntry)
    assert result.github_username == "bob-gh"
    assert result.roster_identifier == ""


def test_convert_ignores_extra_fields():
    data = {
        "id": 123,
        "slug": "hw-01",
        "title": "Homework 01",
        "extra_field": "should be ignored",
        "another_unknown": 999,
    }
    result = msgspec.convert(data, GHAssignment)
    assert result.id == 123
    assert result.slug == "hw-01"


def test_convert_gh_assignment_with_starter_code():
    data = {
        "id": 123,
        "slug": "hw-01",
        "title": "Homework 01",
        "starter_code_repository": {
            "id": 456,
            "full_name": "psyc-201/hw-01-starter",
        },
    }
    result = msgspec.convert(data, GHAssignment)
    assert result.starter_code_repository is not None
    assert result.starter_code_repository.full_name == "psyc-201/hw-01-starter"


def test_convert_gh_assignment_no_starter_code():
    data = {"id": 123, "slug": "hw-01", "title": "Homework 01"}
    result = msgspec.convert(data, GHAssignment)
    assert result.starter_code_repository is None


# --- sanitize_student_dir ---


@pytest.mark.parametrize(
    "sortable,gh,expected",
    [
        ("Smith, Alice", "asmith", "smith-alice"),
        ("De La Cruz, Maria", "mcruz", "de-la-cruz-maria"),
        ("", "asmith", "asmith"),
        ("  Doe ,  Jane  ", "jdoe", "doe-jane"),
        ("O'Brien, Sean", "sobrien", "obrien-sean"),
        ("Madonna", "madonna", "madonna"),
    ],
)
def test_sanitize_student_dir(sortable: str, gh: str, expected: str):
    assert sanitize_student_dir(sortable, gh) == expected
