"""Tests for enrollment dates and late-enrollee selection."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

import pytest

from cass.actions.enrollments import (
    LateEnrollee,
    enrollment_dates,
    is_after,
    late_enrollees,
    person_record,
    roster,
    select_people,
)
from cass.apis.canvas.schema import (
    CanvasEnrollment,
    CanvasStudentResponse,
    CanvasUser,
)
from cass.apis.canvas.times import parse_when


def enrollment(
    id: int,
    user_id: int,
    created_at: str | None,
    *,
    type: str = "StudentEnrollment",
    state: str = "active",
    name: str = "",
) -> CanvasEnrollment:
    user = CanvasStudentResponse(id=user_id, name=name) if name else None
    return CanvasEnrollment(
        id=id,
        user_id=user_id,
        type=type,
        enrollment_state=state,
        created_at=created_at,
        user=user,
    )


def test_enrollment_dates_takes_earliest() -> None:
    enrollments = [
        enrollment(1, 5, "2026-10-02T17:00:00Z"),
        enrollment(2, 5, "2026-09-01T00:00:00Z"),
        enrollment(3, 6, None),
    ]
    assert enrollment_dates(enrollments) == {5: "2026-09-01T00:00:00Z"}


def test_earliest_enrollment_counts_deleted() -> None:
    enrollments = [
        enrollment(1, 5, "2026-09-01T00:00:00Z", state="deleted"),
        enrollment(2, 5, "2026-10-02T17:00:00Z"),
    ]
    assert late_enrollees(enrollments, "2026-10-01T00:00:00-07:00") == {}


def test_late_enrollees_students_only() -> None:
    late = "2026-10-03T00:00:00Z"
    enrollments = [
        enrollment(1, 5, "2026-10-02T17:00:00Z", name="Ann"),
        enrollment(2, 8, late, state="invited"),
        enrollment(3, 99, late, type="StudentViewEnrollment"),
        enrollment(4, 2, late, type="TeacherEnrollment"),
        enrollment(5, 9, late, state="inactive"),
    ]
    result = late_enrollees(enrollments, "2026-10-01T00:00:00-07:00")
    assert set(result) == {5, 8}
    assert result[5] == LateEnrollee(5, "Ann", "2026-10-02T17:00:00Z")
    assert result[8].name == "8"


def test_enrolled_after_uses_course_time_zone() -> None:
    cutoff = parse_when("2026-10-05", "America/Los_Angeles")
    assert is_after("2026-10-05T06:59:00Z", cutoff) is False
    assert is_after("2026-10-05T07:01:00Z", cutoff) is True
    assert is_after(None, cutoff) is False


def test_enrolled_after_follows_daylight_saving() -> None:
    # Nov 2 is after the switch to PST (-08:00), so midnight is 08:00Z.
    cutoff = parse_when("2026-11-02", "America/Los_Angeles")
    assert cutoff.endswith("-08:00")
    assert is_after("2026-11-02T07:59:00Z", cutoff) is False
    assert is_after("2026-11-02T08:01:00Z", cutoff) is True


def test_late_enrollees_keeps_a_name_across_sections() -> None:
    late = "2026-10-03T00:00:00Z"
    enrollments = [
        enrollment(1, 5, late, name="Ann"),
        enrollment(2, 5, late),  # a second section, returned without a user
    ]
    result = late_enrollees(enrollments, "2026-10-01T00:00:00-07:00")
    assert result[5].name == "Ann"


def test_roster_filters_any_role_and_sorts() -> None:
    client = MagicMock()
    client.time_zone = "America/Los_Angeles"
    client.list_users.return_value = [
        CanvasUser(id=7, name="Zoe", sortable_name="Zed, Zoe"),
        CanvasUser(id=6, name="Ann", sortable_name="Aye, Ann"),
        CanvasUser(id=5, name="Ann", sortable_name="Aye, Ann"),
        CanvasUser(id=1, name="Old", sortable_name="Old"),
    ]
    late = "2026-10-03T00:00:00Z"
    client.list_enrollments.return_value = [
        enrollment(1, 7, late, type="TeacherEnrollment"),
        enrollment(2, 6, late),
        enrollment(3, 5, late),
        enrollment(4, 1, "2026-09-01T00:00:00Z"),
    ]
    users, dates = roster(client, states=["active"], enrolled_after="2026-10-01")
    client.list_users.assert_called_once_with(states=["active"])
    assert [u.id for u in users] == [5, 6, 7]
    assert dates[1] == "2026-09-01T00:00:00Z"


def test_roster_rejects_bad_date_before_any_request() -> None:
    client = MagicMock()
    with pytest.raises(RuntimeError, match="Unrecognized time"):
        roster(client, enrolled_after="soon")
    assert client.method_calls == []


def test_select_people_filters_by_date() -> None:
    early = CanvasUser(id=1, name="Early")
    later = CanvasUser(id=2, name="Later")
    dates = {1: "2026-09-01T00:00:00Z", 2: "2026-10-02T17:00:00Z"}
    cutoff = "2026-10-01T00:00:00-07:00"
    assert select_people([early, later], dates, cutoff) == [later]
    assert select_people([early, later], dates) == [early, later]


def test_person_record_adds_enrolled_at() -> None:
    record = person_record(CanvasUser(id=5, name="Ann"), "2026-10-02T17:00:00Z")
    assert record["name"] == "Ann"
    assert "enrollments" in record
    assert record["enrolled_at"] == "2026-10-02T17:00:00Z"
