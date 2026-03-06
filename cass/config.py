"""Config discovery, loading, and writing for cass.

Searches for ``cass.toml`` starting from the current directory and walking
upward.  Config is loaded lazily on first access via ``get_config()``.
"""

__docformat__ = "google"

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "cass.toml"


@dataclass
class CanvasModuleSpec:
    """Desired state for a Canvas module declared in cass.toml."""

    name: str
    published: bool = False


@dataclass
class CanvasAssignmentSpec:
    """Desired state for a Canvas assignment declared in cass.toml."""

    name: str
    points: float = 0.0
    submission_types: list[str] = field(default_factory=lambda: ["online_url"])
    due_at: str = ""
    published: bool = False
    group: str = ""


@dataclass
class Config:
    root: Path
    classroom_id: int = 0
    org: str = ""
    canvas_base_url: str = ""
    canvas_course_id: int = 0
    canvas_modules: list[CanvasModuleSpec] = field(default_factory=list)
    canvas_assignments: list[CanvasAssignmentSpec] = field(default_factory=list)
    motherduck_db: str = ""

    @property
    def has_classroom(self) -> bool:
        return bool(self.classroom_id and self.org)

    @property
    def has_canvas(self) -> bool:
        return bool(self.canvas_base_url and self.canvas_course_id)

    @property
    def has_motherduck(self) -> bool:
        return bool(self.motherduck_db)


_config: Config | None = None


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find cass.toml."""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / CONFIG_FILENAME).exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise SystemExit(
        "No cass.toml found in current or parent directories.\n"
        "Run 'cass init' to create one."
    )


def config_file_path() -> Path | None:
    """Return the path to the config file, or None if it doesn't exist."""
    try:
        root = find_project_root()
    except SystemExit:
        return None
    path = root / CONFIG_FILENAME
    return path if path.exists() else None


def load_config() -> Config:
    root = find_project_root()
    path = root / CONFIG_FILENAME
    if not path.exists():
        raise SystemExit("Config file not found.")
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    cc = raw.get("classroom", {})
    canvas = raw.get("canvas", {})

    has_cc = "id" in cc and "org" in cc
    has_cv = "base_url" in canvas and "course_id" in canvas

    if not has_cc and not has_cv:
        raise SystemExit(
            f"Invalid config: {path} must have at least a "
            "[classroom] or [canvas] section."
        )

    # Parse [[canvas.modules]] and [[canvas.assignments]] if present
    module_specs = [
        CanvasModuleSpec(
            name=m["name"],
            published=m.get("published", False),
        )
        for m in canvas.get("modules", [])
        if "name" in m
    ]
    assignment_specs = [
        CanvasAssignmentSpec(
            name=a["name"],
            points=a.get("points", 0.0),
            submission_types=a.get("submission_types", ["online_url"]),
            due_at=a.get("due_at", ""),
            published=a.get("published", False),
            group=a.get("group", ""),
        )
        for a in canvas.get("assignments", [])
        if "name" in a
    ]

    # Parse [database] section
    database = raw.get("database", {})
    motherduck_db = database.get("motherduck", "")

    return Config(
        root=root,
        classroom_id=cc.get("id", 0),
        org=cc.get("org", ""),
        canvas_base_url=canvas.get("base_url", ""),
        canvas_course_id=canvas.get("course_id", 0),
        canvas_modules=module_specs,
        canvas_assignments=assignment_specs,
        motherduck_db=motherduck_db,
    )


def get_config() -> Config:
    """Return the lazily-loaded project config."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Clear the cached config (for re-reading after writes)."""
    global _config
    _config = None


def write_config(
    path: Path,
    classroom_id: int = 0,
    org: str = "",
    canvas_base_url: str = "",
    canvas_course_id: int = 0,
) -> None:
    """Write a cass.toml file."""
    lines: list[str] = []
    if classroom_id and org:
        lines += [
            "[classroom]",
            f"id = {classroom_id}",
            f'org = "{org}"',
        ]
    if canvas_base_url and canvas_course_id:
        if lines:
            lines.append("")
        lines += [
            "[canvas]",
            f'base_url = "{canvas_base_url}"',
            f"course_id = {canvas_course_id}",
        ]
    path.write_text("\n".join(lines) + "\n")
    reset_config()


# --- Prerequisite checks ---


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    indent: int = 0


def check_prerequisites() -> list[Check]:
    """Run all setup checks and return results."""
    from .github.client import check_auth, check_available

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
        checks.append(
            Check(
                "config", False, "invalid — needs [classroom] and/or [canvas] section"
            )
        )
        return checks

    # GitHub Classroom checks (only if configured)
    if cfg.has_classroom:
        checks.append(Check("classroom", True, "configured"))
        is_default = cfg.classroom_id == 0 or cfg.org == "my-org"
        checks.append(
            Check(
                "classroom_id",
                not is_default and cfg.classroom_id > 0,
                str(cfg.classroom_id) if cfg.classroom_id > 0 else "not set",
                indent=1,
            )
        )
        checks.append(Check("org", cfg.org != "my-org", cfg.org, indent=1))

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
            authed, detail = check_auth()
            checks.append(Check("gh auth", authed, detail, indent=1))
    else:
        checks.append(Check("classroom", True, "not configured (optional)"))

    # Canvas checks (only if configured)
    if cfg.has_canvas:
        checks.append(Check("canvas", True, "configured"))
        checks.append(Check("base_url", True, cfg.canvas_base_url, indent=1))
        checks.append(Check("course_id", True, str(cfg.canvas_course_id), indent=1))
        token_path = cfg.root / "canvas-token.txt"
        has_token = (
            token_path.exists() and token_path.read_text().strip() != ""
        ) or bool(os.environ.get("CANVAS_TOKEN"))
        checks.append(
            Check(
                "token",
                has_token,
                "found"
                if has_token
                else "not found (canvas-token.txt or $CANVAS_TOKEN)",
                indent=1,
            )
        )
    else:
        checks.append(Check("canvas", True, "not configured (optional)"))

    # MotherDuck checks (only if configured)
    if cfg.has_motherduck:
        has_md_token = bool(os.environ.get("MOTHERDUCK_TOKEN"))
        checks.append(Check("motherduck", True, f"database = {cfg.motherduck_db}"))
        checks.append(
            Check(
                "token",
                has_md_token,
                "found" if has_md_token else "not found — set $MOTHERDUCK_TOKEN",
                indent=1,
            )
        )

    # Roster
    try:
        from . import db

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
