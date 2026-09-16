"""Prerequisite checks for cass setup (``cass init`` doctor)."""

__docformat__ = "google"


import shutil
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
    from ..apis.github.client import check_auth, check_available
    from ..apis.github.service import check_classroom_extension

    checks: list[Check] = []

    # Config file
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

    # GitHub Classroom checks (only if configured)
    if cfg.has_classroom:
        checks.append(Check("classroom", True, "configured"))
        checks.append(
            Check(
                "classroom_url",
                cfg.has_classroom_url,
                cfg.classroom_url or "not set",
                indent=1,
            )
        )
        checks.append(
            Check(
                "url_id", cfg.classroom_url_id > 0, str(cfg.classroom_url_id), indent=1
            )
        )
        checks.append(
            Check("gh_id", cfg.classroom_gh_id > 0, str(cfg.classroom_gh_id), indent=1)
        )

        # git
        checks.append(
            Check(
                "git",
                bool(shutil.which("git")),
                "installed" if shutil.which("git") else "not found",
            )
        )

        # gh CLI
        gh_ok = check_available()
        checks.append(
            Check(
                "gh",
                gh_ok,
                "installed" if gh_ok else "not found — https://cli.github.com/",
            )
        )
        if gh_ok:
            ext_ok, ext_detail = check_classroom_extension()
            checks.append(Check("gh classroom", ext_ok, ext_detail, indent=1))
            authed, detail = check_auth()
            checks.append(Check("gh auth", authed, detail, indent=1))
    elif cfg.classroom_needs_resolution:
        checks.append(
            Check("classroom", False, "URL saved; gh-classroom ID unresolved")
        )
        checks.append(Check("classroom_url", True, cfg.classroom_url, indent=1))
        checks.append(Check("url_id", True, str(cfg.classroom_url_id), indent=1))
        checks.append(Check("gh_id", False, "unresolved", indent=1))
        gh_ok = check_available()
        checks.append(
            Check(
                "gh",
                gh_ok,
                "installed" if gh_ok else "Install GitHub CLI: https://cli.github.com/",
            )
        )
        if gh_ok:
            ext_ok, ext_detail = check_classroom_extension()
            checks.append(Check("gh classroom", ext_ok, ext_detail, indent=1))
            authed, detail = check_auth()
            checks.append(Check("gh auth", authed, detail, indent=1))
    else:
        checks.append(Check("classroom", True, "not configured (optional)"))

    # Canvas checks (only if configured)
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

        if db.students_exist():
            students = db.load_students()
            checks.append(
                Check("roster", True, f"{len(students)} students in database")
            )
        else:
            checks.append(Check("roster", False, "empty — run 'cass pull'"))
    except SystemExit:
        pass

    return checks
