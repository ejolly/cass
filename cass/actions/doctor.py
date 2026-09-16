"""Prerequisite checks for cass setup (``cass init`` doctor)."""

from __future__ import annotations

__docformat__ = "google"


from dataclasses import dataclass

from ..apis.canvas.auth import find_auth
from .config import config_file_path, get_config


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    indent: int = 0


def check_prerequisites() -> list[Check]:
    """Run all setup checks and return results."""
    checks: list[Check] = []

    cfg_path = config_file_path()
    if not cfg_path:
        checks.append(Check("cass.toml", False, "not found — run 'cass init'"))
        return checks

    checks.append(Check("cass.toml", True, f"found at {cfg_path}"))

    try:
        cfg = get_config()
    except SystemExit:
        checks.append(Check("config", False, "invalid — needs a [canvas] section"))
        return checks

    if cfg.has_canvas:
        checks.append(Check("canvas", True, "configured"))
        checks.append(Check("base_url", True, cfg.canvas_base_url, indent=1))
        checks.append(Check("course_id", True, str(cfg.canvas_course_id), indent=1))
        auth = find_auth(cfg.root)
        checks.append(
            Check(
                "auth",
                auth is not None,
                auth.description
                if auth
                else "not found (.canvascreds, .canvastoken or $CANVAS_TOKEN)",
                indent=1,
            )
        )
    else:
        checks.append(Check("canvas", False, "not configured"))

    # Roster
    try:
        from .. import db

        count = len(db.load_canvas_student_ids())
        if count:
            checks.append(Check("roster", True, f"{count} students in database"))
        else:
            checks.append(Check("roster", False, "empty — run 'cass pull'"))
    except SystemExit:
        pass

    return checks
