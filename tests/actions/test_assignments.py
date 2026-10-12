"""Tests for assignment and assignment group sync."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

import pytest

from cass.actions.assignments import (
    MissingAssignmentGroupsError,
    sync_assignment_groups,
    sync_assignments,
)
from cass.actions.config import CanvasAssignmentSpec
from cass.apis.canvas.schema import CanvasAssignmentGroup, CanvasAssignmentResponse

TZ = "America/Los_Angeles"


def client_with(*live: CanvasAssignmentResponse) -> MagicMock:
    client = MagicMock()
    client.list_assignments.return_value = list(live)
    client.create_assignment.return_value = CanvasAssignmentResponse(id=9, name="New")
    return client


def test_sync_assignments_creates_updates_and_skips_by_name():
    client = client_with(
        CanvasAssignmentResponse(id=1, name="HW1", points_possible=5, published=True),
        CanvasAssignmentResponse(id=2, name="HW2", points_possible=10, published=True),
    )
    specs = [
        CanvasAssignmentSpec(name="hw1", points=10, published=False),
        CanvasAssignmentSpec(name="HW2", points=10),
        CanvasAssignmentSpec(
            name="HW3",
            points=20,
            due_at="2026-10-01 23:59",
            group="Labs",
            submission_types=["online_upload"],
        ),
    ]
    created: list[CanvasAssignmentResponse] = []

    rows = sync_assignments(client, specs, {"labs": 11}, TZ, created=created)

    assert rows == [
        ("update", "assignment", "hw1 (points_possible: 10, published: False)"),
        ("skip", "assignment", "HW2"),
        ("create", "assignment", "HW3"),
    ]
    client.update_assignment.assert_called_once_with(
        1, points_possible=10, published=False
    )
    client.create_assignment.assert_called_once_with(
        "HW3",
        points_possible=20,
        due_at="2026-10-01T23:59:00-07:00",
        submission_types=["online_upload"],
        published=False,
        assignment_group_id=11,
    )
    assert created == [client.create_assignment.return_value]


def test_sync_assignments_leaves_published_alone_when_omitted():
    client = client_with(
        CanvasAssignmentResponse(id=1, name="HW1", published=True),
        CanvasAssignmentResponse(id=2, name="HW2", published=False),
    )
    specs = [CanvasAssignmentSpec(name="HW1"), CanvasAssignmentSpec(name="HW2")]

    rows = sync_assignments(client, specs, {}, TZ)

    assert rows == [("skip", "assignment", "HW1"), ("skip", "assignment", "HW2")]
    client.update_assignment.assert_not_called()


@pytest.mark.parametrize(
    "due_at", ["2026-10-01T23:59:00-07:00", "2026-10-01 23:59"], ids=["offset", "naive"]
)
def test_sync_assignments_due_at_matching_live_is_a_skip(due_at):
    client = client_with(
        CanvasAssignmentResponse(
            id=1, name="HW1", points_possible=10, due_at="2026-10-02T06:59:00Z"
        )
    )
    specs = [CanvasAssignmentSpec(name="HW1", points=10, due_at=due_at)]

    assert sync_assignments(client, specs, {}, TZ) == [("skip", "assignment", "HW1")]
    client.update_assignment.assert_not_called()


def test_sync_assignments_due_at_change_is_an_update():
    client = client_with(
        CanvasAssignmentResponse(id=1, name="HW1", due_at="2026-10-02T06:59:00Z")
    )
    specs = [CanvasAssignmentSpec(name="HW1", due_at="2026-10-08 23:59")]

    rows = sync_assignments(client, specs, {}, TZ)

    assert rows == [("update", "assignment", "HW1 (due_at: 2026-10-08T23:59:00-07:00)")]
    client.update_assignment.assert_called_once_with(
        1, due_at="2026-10-08T23:59:00-07:00"
    )


def test_sync_assignment_groups_creates_missing_when_asked():
    client = MagicMock()
    client.list_assignment_groups.return_value = [
        CanvasAssignmentGroup(id=3, name="Homework")
    ]
    client.create_assignment_group.return_value = CanvasAssignmentGroup(
        id=11, name="Labs"
    )

    rows, group_ids = sync_assignment_groups(
        client, ["homework", "Labs", "LABS"], create=True
    )

    assert rows == [("create", "group", "Labs")]
    assert group_ids == {"homework": 3, "labs": 11}
    client.create_assignment_group.assert_called_once_with("Labs")


def test_sync_assignment_groups_raises_on_missing_without_create():
    client = MagicMock()
    client.list_assignment_groups.return_value = []

    with pytest.raises(MissingAssignmentGroupsError) as excinfo:
        sync_assignment_groups(client, ["Labs", "Quizzes"], create=False)

    assert excinfo.value.missing == ["Labs", "Quizzes"]
    client.create_assignment_group.assert_not_called()


def test_sync_assignment_groups_without_wanted_reads_nothing():
    client = MagicMock()

    assert sync_assignment_groups(client, [], create=False) == ([], {})
    client.list_assignment_groups.assert_not_called()
