"""Access to the Canvas practice course that live tests run against."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

from cass.actions.config import get_config, set_config_path
from cass.apis.canvas.auth import CanvasAuth, find_auth
from cass.apis.canvas.client import CanvasClient

LIVE_DIR = Path(__file__).resolve().parent
REPO_ROOT = LIVE_DIR.parents[1]
CONFIG_PATH = LIVE_DIR / "cass.toml"

QUIZ_TITLE = "cass-live: quiz"
SURVEY_TITLE = "cass-live: survey"


def live_auth() -> CanvasAuth | None:
    """Canvas credentials saved in the repository root, if any."""
    return find_auth(REPO_ROOT)


def practice_client() -> CanvasClient:
    """A client for the practice course in ``tests/live/cass.toml``.

    Raises:
        SystemExit: If the repository root has no Canvas credentials.
    """
    auth = live_auth()
    if auth is None:
        raise SystemExit(
            f"No Canvas credentials in {REPO_ROOT}; save a token to .canvastoken."
        )
    set_config_path(CONFIG_PATH)
    cfg = get_config()
    return CanvasClient(
        cfg.canvas_base_url,
        course_id=cfg.canvas_course_id,
        auth=auth,
        time_zone=cfg.canvas_time_zone,
    )


def get_test_student_id(client: CanvasClient) -> int:
    """ID of the course's Test Student (Canvas creates one on first request)."""
    resp = client.request("GET", f"/courses/{client.course_id}/student_view_student")
    return int(resp.json()["id"])
