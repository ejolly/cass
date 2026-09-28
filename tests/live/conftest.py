"""Fixtures for live tests against real Canvas courses.

Live tests are marked ``live`` and run only through ``uv run poe live``;
``uv run poe test`` and CI deselect them. They skip when the repository root
has no Canvas credentials.
"""

from __future__ import annotations

__docformat__ = "google"

import os
from collections.abc import Iterator

import pytest
from live_course import live_auth, practice_client

from cass.actions.config import get_config, set_config_path
from cass.apis.canvas.client import CanvasClient

REAL_COURSE_ENV = "CASS_LIVE_REAL_COURSE"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(pytest.mark.live)


@pytest.fixture(scope="session")
def practice() -> Iterator[CanvasClient]:
    """Client for the seeded practice course; tests may change its content."""
    if live_auth() is None:
        pytest.skip("No Canvas credentials in the repository root")
    with practice_client() as client:
        yield client
    set_config_path(None)


@pytest.fixture(scope="session")
def real_course(practice: CanvasClient) -> Iterator[CanvasClient]:
    """Client for a real course, set by ``$CASS_LIVE_REAL_COURSE``.

    Tests must not change course content or grades. Generating quiz reports
    is allowed. Assert on structure (counts, columns), never on student data.
    """
    course_id = os.environ.get(REAL_COURSE_ENV, "")
    if not course_id:
        pytest.skip(f"Set {REAL_COURSE_ENV} to a course ID to run real-course tests")
    base_url = get_config().canvas_base_url
    with CanvasClient(base_url, course_id=int(course_id), auth=practice.auth) as client:
        yield client
