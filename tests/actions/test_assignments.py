"""Tests for assignment and assignment group sync."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any
from unittest.mock import MagicMock

import pytest

from cass.actions.assignments import (
    MissingAssignmentGroupsError,
    refuse_group_delete,
    sync_assignment_groups,
    sync_assignments,
)
from cass.actions.config import CanvasAssignmentSpec
from cass.apis.canvas.attempts import (
    QuizAttemptsUnknownError,
    QuizHasAttemptsError,
    refuse_if_assignment_attempted,
)
from cass.apis.canvas.schema import CanvasAssignmentGroup, CanvasAssignmentResponse

TZ = "America/Los_Angeles"


def client_with(*live: CanvasAssignmentResponse) -> MagicMock:
    client = MagicMock()
    client.list_assignments.return_value = list(live)
    client.create_assignment.return_value = CanvasAssignmentResponse(id=9, name="New")
    client.get_assignment.side_effect = {a.id: a for a in live}.__getitem__
    client.update_assignment.side_effect = lambda id, **fields: (
        CanvasAssignmentResponse(
            id=id, name="", points_possible=fields.get("points_possible")
        )
    )
    client.list_students.return_value = []
    client.list_quiz_submissions.return_value = []
    client.count_quiz_takers.return_value = 0
    return client


def quiz_assignment(**fields: Any) -> CanvasAssignmentResponse:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "Quiz 1",
        "points_possible": 5.0,
        "quiz_id": 20,
    }
    return CanvasAssignmentResponse(**{**defaults, **fields})


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


def test_sync_points_refused_with_attempts():
    client = client_with(quiz_assignment())
    client.count_quiz_takers.return_value = 2
    specs = [
        CanvasAssignmentSpec(name="Quiz 1", points=10, due_at="2026-10-08 23:59"),
        CanvasAssignmentSpec(name="Only points", points=10),
    ]
    client.list_assignments.return_value.append(
        quiz_assignment(id=2, name="Only points")
    )

    rows = sync_assignments(client, specs, {}, TZ)

    reason = "2 finished attempt(s); change it in the Canvas web app"
    assert rows == [
        ("refuse", "assignment", f"Quiz 1 (points_possible: {reason})"),
        ("update", "assignment", "Quiz 1 (due_at: 2026-10-08T23:59:00-07:00)"),
        ("refuse", "assignment", f"Only points (points_possible: {reason})"),
    ]
    client.update_assignment.assert_called_once_with(
        1, due_at="2026-10-08T23:59:00-07:00"
    )


def test_sync_points_refused_when_attempts_unknown():
    client = client_with(
        quiz_assignment(), CanvasAssignmentResponse(id=2, name="HW", points_possible=1)
    )
    client.count_quiz_takers.side_effect = QuizAttemptsUnknownError(20, "reason")
    specs = [
        CanvasAssignmentSpec(name="Quiz 1", points=10),
        CanvasAssignmentSpec(name="HW", points=10),
    ]

    rows = sync_assignments(client, specs, {}, TZ)

    assert [(action, name.split(" (")[0]) for action, _, name in rows] == [
        ("refuse", "Quiz 1"),
        ("update", "HW"),
    ]
    assert "attempts could not be checked" in rows[0][2]
    client.update_assignment.assert_called_once_with(2, points_possible=10)


def test_sync_points_sent_without_attempts():
    client = client_with(quiz_assignment())
    rows = sync_assignments(
        client, [CanvasAssignmentSpec(name="Quiz 1", points=10)], {}, TZ
    )
    assert rows == [("update", "assignment", "Quiz 1 (points_possible: 10)")]
    client.update_assignment.assert_called_once_with(1, points_possible=10)


def test_sync_rechecks_attempts_before_sending():
    client = client_with(quiz_assignment())
    client.count_quiz_takers.side_effect = [0, 1]
    rows = sync_assignments(
        client, [CanvasAssignmentSpec(name="Quiz 1", points=10)], {}, TZ
    )
    assert [action for action, _, _ in rows] == ["fail"]
    assert "1 finished student attempt(s)" in rows[0][2]
    client.update_assignment.assert_not_called()


def test_reverted_points_reported():
    client = client_with(quiz_assignment())
    client.update_assignment.side_effect = None
    client.update_assignment.return_value = quiz_assignment()
    rows = sync_assignments(
        client, [CanvasAssignmentSpec(name="Quiz 1", points=10)], {}, TZ
    )
    assert rows == [
        ("fail", "assignment", "Quiz 1 (Canvas kept points_possible at 5.0)")
    ]


def test_group_delete_checks_every_assignment():
    client = client_with(
        quiz_assignment(id=1, quiz_id=20, assignment_group_id=9),
        CanvasAssignmentResponse(id=2, name="HW", assignment_group_id=9),
        quiz_assignment(id=3, name="Quiz 3", quiz_id=30, assignment_group_id=9),
        quiz_assignment(id=4, name="Elsewhere", quiz_id=40, assignment_group_id=8),
    )
    takers = {20: 0, 30: 1, 40: 5}
    client.count_quiz_takers.side_effect = takers.__getitem__
    group = CanvasAssignmentGroup(id=9, name="Labs")

    with pytest.raises(QuizHasAttemptsError, match="'Quiz 3' has 1 finished"):
        refuse_group_delete(client, group)

    takers[30] = 0
    refuse_group_delete(client, group)
    checked = [call.args[0] for call in client.count_quiz_takers.call_args_list]
    assert checked == [20, 30, 20, 30]


def test_group_delete_refused_when_attempts_unknown():
    client = client_with(quiz_assignment(assignment_group_id=9))
    client.count_quiz_takers.side_effect = QuizAttemptsUnknownError(20, "reason")
    with pytest.raises(QuizAttemptsUnknownError, match="did not make this change"):
        refuse_group_delete(client, CanvasAssignmentGroup(id=9, name="Labs"))


def test_assignment_without_quiz_needs_no_requests():
    client = MagicMock()
    assignment = CanvasAssignmentResponse(id=1, name="HW")
    refuse_if_assignment_attempted(client, assignment, "delete it")
    assert client.mock_calls == []
