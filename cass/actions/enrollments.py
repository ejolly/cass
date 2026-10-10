"""Enrollment dates and late-enrollee selection.

"Enrolled at" is the earliest ``created_at`` across all of a user's
enrollments (any type, any state, deleted included), so a student who
dropped and re-enrolled keeps their original date.
"""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import msgspec

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasEnrollment, CanvasUser


class EnrollmentState(StrEnum):
    """Values accepted by ``people list --state``."""

    ACTIVE = "active"
    INVITED = "invited"
    INACTIVE = "inactive"
    COMPLETED = "completed"


ALL_ENROLLMENT_STATES = (
    "active",
    "invited",
    "creation_pending",
    "inactive",
    "completed",
    "rejected",
    "deleted",
)
CURRENT_STUDENT_STATES = ("active", "invited")


@dataclass
class LateEnrollee:
    """A current student who first enrolled after a cutoff."""

    user_id: int
    name: str
    enrolled_at: str


def fetch_all_enrollments(client: CanvasClient) -> list[CanvasEnrollment]:
    """Fetch every enrollment of every type and state (no scores)."""
    return client.list_enrollments(
        enrollment_type=None, states=ALL_ENROLLMENT_STATES, include_scores=False
    )


def enrollment_dates(enrollments: Iterable[CanvasEnrollment]) -> dict[int, str]:
    """Map user id to the earliest enrollment ``created_at``.

    Enrollments without ``created_at`` are ignored.
    """
    earliest: dict[int, str] = {}
    for enrollment in enrollments:
        created = enrollment.created_at
        if not created:
            continue
        current = earliest.get(enrollment.user_id)
        if current is None or is_after(current, created):
            earliest[enrollment.user_id] = created
    return earliest


def is_after(iso: str | None, cutoff: str) -> bool:
    """Whether the instant *iso* is strictly later than *cutoff*.

    Compares moments, not spellings (``Z`` versus a local offset). A missing
    *iso* is never after anything.
    """
    if not iso:
        return False
    return datetime.fromisoformat(iso) > datetime.fromisoformat(cutoff)


def select_people(
    users: list[CanvasUser], dates: dict[int, str], cutoff: str = ""
) -> list[CanvasUser]:
    """Keep users first enrolled after *cutoff*; an empty cutoff keeps all."""
    if not cutoff:
        return users
    return [user for user in users if is_after(dates.get(user.id), cutoff)]


def person_record(user: CanvasUser, enrolled_at: str | None) -> dict[str, object]:
    """A user as a plain dict plus the cass ``enrolled_at`` key."""
    return msgspec.to_builtins(user) | {"enrolled_at": enrolled_at}


def late_enrollees(
    enrollments: list[CanvasEnrollment], cutoff: str
) -> dict[int, LateEnrollee]:
    """Current students (active or invited) first enrolled after *cutoff*."""
    dates = enrollment_dates(enrollments)
    late: dict[int, LateEnrollee] = {}
    for enrollment in enrollments:
        if enrollment.type != "StudentEnrollment":
            continue
        if enrollment.enrollment_state not in CURRENT_STUDENT_STATES:
            continue
        enrolled_at = dates.get(enrollment.user_id)
        if enrolled_at is None or not is_after(enrolled_at, cutoff):
            continue
        name = enrollment.user.name if enrollment.user else str(enrollment.user_id)
        late[enrollment.user_id] = LateEnrollee(enrollment.user_id, name, enrolled_at)
    return late
