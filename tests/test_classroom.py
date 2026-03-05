"""Tests for cass.classroom — typed struct decoding via msgspec.convert."""

import msgspec

from cass.models import (
    GHAcceptedAssignment,
    GHAssignment,
    GHCommit,
    GHContentItem,
)


def test_convert_gh_assignment():
    data = {
        "id": 123,
        "slug": "hw-01",
        "title": "Homework 01",
        "deadline": "2025-01-15T23:59:00Z",
        "accepted": 25,
    }
    result = msgspec.convert(data, GHAssignment)
    assert result.id == 123
    assert result.slug == "hw-01"
    assert result.title == "Homework 01"
    assert result.deadline == "2025-01-15T23:59:00Z"
    assert result.accepted == 25


def test_convert_accepted_assignment():
    data = {
        "id": 456,
        "students": [{"id": 1, "login": "alice-gh"}, {"id": 2, "login": "bob-gh"}],
        "repository": {"id": 789, "full_name": "my-org/hw-01-alice-gh"},
    }
    result = msgspec.convert(data, GHAcceptedAssignment)
    assert result.id == 456
    assert len(result.students) == 2
    assert result.students[0].login == "alice-gh"
    assert result.repository is not None
    assert result.repository.full_name == "my-org/hw-01-alice-gh"


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
