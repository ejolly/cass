"""Canvas LMS API client — typed CRUD for every Canvas resource.

Provides ``CanvasClient``, a typed httpx client with ``course_id`` baked in.
All methods return msgspec.Struct instances, never raw dicts. The client is
assembled from one mixin per resource; ``base`` holds the transport, auth
lookup, pagination, and the shared ``_resolve`` helper."""

from __future__ import annotations

__docformat__ = "google"

from .announcements import AnnouncementsMixin
from .assignments import AssignmentsMixin
from .base import (
    MAX_RETRIES,
    THROTTLE_DELAY,
    THROTTLE_THRESHOLD,
    BaseClient,
    RetryTransport,
    get_auth,
    get_token,
    resource_key,
    save_token,
)
from .calendar import CalendarMixin
from .course import CourseMixin
from .files import FilesMixin
from .grades import GradesMixin
from .modules import ModulesMixin
from .quizzes import QuizzesMixin
from .tabs import TabsMixin

__all__ = [
    "MAX_RETRIES",
    "THROTTLE_DELAY",
    "THROTTLE_THRESHOLD",
    "BaseClient",
    "CanvasClient",
    "RetryTransport",
    "get_auth",
    "get_token",
    "resource_key",
    "save_token",
]


class CanvasClient(
    CourseMixin,
    ModulesMixin,
    AssignmentsMixin,
    GradesMixin,
    QuizzesMixin,
    FilesMixin,
    AnnouncementsMixin,
    CalendarMixin,
    TabsMixin,
    BaseClient,
):
    """Typed Canvas LMS API client with course_id baked in.

    See ``BaseClient`` for constructor arguments.
    """
