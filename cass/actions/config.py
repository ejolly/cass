"""Config discovery, loading, and writing for cass.

Searches for ``cass.toml`` starting from the current directory and walking
upward.  Config is loaded lazily on first access via ``get_config()``.
"""

__docformat__ = "google"

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "cass.toml"
_CANVAS_COURSE_URL_RE = re.compile(r"^(https?://[^/]+)/courses/(\d+)(?:[/?#].*)?$")
_GH_CLASSROOM_URL_RE = re.compile(
    r"^https?://classroom\.github\.com/classrooms/(\d+)(?:-[^/?#]+)?(?:[/?#].*)?$"
)


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
    classroom_url: str = ""
    classroom_url_id: int = 0
    classroom_gh_id: int = 0
    classroom_slug: str = ""
    classroom_title: str = ""
    org: str = ""
    canvas_base_url: str = ""
    canvas_course_id: int = 0
    canvas_modules: list[CanvasModuleSpec] = field(default_factory=list)
    canvas_assignments: list[CanvasAssignmentSpec] = field(default_factory=list)
    motherduck_db: str = ""

    @property
    def has_classroom_url(self) -> bool:
        return bool(self.classroom_url and self.classroom_url_id)

    @property
    def has_classroom(self) -> bool:
        return bool(self.has_classroom_url and self.classroom_gh_id)

    @property
    def classroom_needs_resolution(self) -> bool:
        return self.has_classroom_url and not self.has_classroom

    @property
    def classroom_status(self) -> str:
        if self.has_classroom:
            return "configured"
        if self.classroom_needs_resolution:
            return "pending"
        return "missing"

    @property
    def classroom_needs_auth(self) -> bool:
        """Backward-compatible alias for pending Classroom resolution."""
        return self.classroom_needs_resolution

    @property
    def classroom_id(self) -> int:
        """Return the resolved gh-classroom runtime ID."""
        return self.classroom_gh_id

    @property
    def has_canvas(self) -> bool:
        return bool(self.canvas_base_url and self.canvas_course_id)

    @property
    def has_motherduck(self) -> bool:
        return bool(self.motherduck_db)


_config: Config | None = None


def parse_canvas_course_url(raw: str) -> tuple[str, int] | None:
    """Extract ``(base_url, course_id)`` from a Canvas course URL."""
    match = _CANVAS_COURSE_URL_RE.match(raw.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


def parse_classroom_url(raw: str) -> int | None:
    """Extract the GitHub Classroom numeric ID from a classroom URL."""
    match = _GH_CLASSROOM_URL_RE.match(raw.strip())
    if not match:
        return None
    return int(match.group(1))


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
    raw = read_config_data(root / CONFIG_FILENAME)

    cc = raw.get("classroom", {})
    canvas = raw.get("canvas", {})

    has_cv = "base_url" in canvas and "course_id" in canvas

    if not has_cv:
        raise SystemExit(
            f"Invalid config: {root / CONFIG_FILENAME} must have a [canvas] section."
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

    classroom_url = cc.get("url", "")
    classroom_url_id = cc.get("url_id", 0)
    classroom_gh_id = cc.get("gh_id", 0)
    classroom_slug = cc.get("slug", "")
    classroom_title = cc.get("title", "")
    org = cc.get("org", "")

    # Best-effort migration for older configs that only stored a single id.
    legacy_id = cc.get("id", 0)
    if not classroom_url and isinstance(legacy_id, int) and legacy_id > 0:
        classroom_url_id = classroom_url_id or legacy_id
        classroom_url = f"https://classroom.github.com/classrooms/{legacy_id}"

    return Config(
        root=root,
        classroom_url=classroom_url,
        classroom_url_id=classroom_url_id,
        classroom_gh_id=classroom_gh_id,
        classroom_slug=classroom_slug,
        classroom_title=classroom_title,
        org=org,
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


def read_config_data(path: Path) -> dict[str, Any]:
    """Load a TOML config file into a mutable dict."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return dict(raw)


def _format_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _format_toml_string(value)
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    msg = f"Unsupported TOML value: {value!r}"
    raise TypeError(msg)


def _write_table(
    lines: list[str], path: tuple[str, ...], table: dict[str, Any]
) -> None:
    scalar_items: list[tuple[str, object]] = []
    nested_tables: list[tuple[str, dict[str, Any]]] = []
    array_tables: list[tuple[str, list[dict[str, Any]]]] = []

    for key, value in table.items():
        if isinstance(value, dict):
            nested_tables.append((key, value))
        elif (
            isinstance(value, list)
            and value
            and all(isinstance(item, dict) for item in value)
        ):
            array_tables.append((key, value))
        else:
            scalar_items.append((key, value))

    if path:
        lines.append(f"[{'.'.join(path)}]")
    for key, value in scalar_items:
        lines.append(f"{key} = {_format_toml_value(value)}")

    for key, value in nested_tables:
        if lines and lines[-1] != "":
            lines.append("")
        _write_table(lines, (*path, key), value)

    for key, value in array_tables:
        for item in value:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{'.'.join((*path, key))}]]")
            for item_key, item_value in item.items():
                if isinstance(item_value, dict | list) and not (
                    isinstance(item_value, list)
                    and all(not isinstance(entry, dict) for entry in item_value)
                ):
                    msg = f"Unsupported nested TOML table value: {item_value!r}"
                    raise TypeError(msg)
                lines.append(f"{item_key} = {_format_toml_value(item_value)}")


def _dump_config_data(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_format_toml_value(value)}")
            continue
        if lines:
            lines.append("")
        _write_table(lines, (key,), value)
    return "\n".join(lines).rstrip() + "\n"


def update_config(
    path: Path,
    *,
    classroom_url: str | None = None,
    classroom_url_id: int | None = None,
    classroom_gh_id: int | None = None,
    classroom_slug: str | None = None,
    classroom_title: str | None = None,
    org: str | None = None,
    canvas_base_url: str | None = None,
    canvas_course_id: int | None = None,
) -> None:
    """Update setup-related fields in ``cass.toml`` while preserving other data."""
    raw = read_config_data(path)

    if canvas_base_url is not None or canvas_course_id is not None:
        canvas = raw.setdefault("canvas", {})
        if not isinstance(canvas, dict):
            msg = "Invalid config: [canvas] must be a table."
            raise SystemExit(msg)
        if canvas_base_url is not None:
            canvas["base_url"] = canvas_base_url
        if canvas_course_id is not None:
            canvas["course_id"] = canvas_course_id

    if (
        classroom_url is not None
        or classroom_url_id is not None
        or classroom_gh_id is not None
        or classroom_slug is not None
        or classroom_title is not None
        or org is not None
    ):
        next_url = classroom_url
        next_url_id = classroom_url_id
        if next_url is None or next_url_id is None:
            existing = raw.get("classroom", {})
            if isinstance(existing, dict):
                if next_url is None:
                    next_url = existing.get("url", "")
                if next_url_id is None:
                    next_url_id = existing.get("url_id", 0)

        if next_url and next_url_id:
            classroom = raw.setdefault("classroom", {})
            if not isinstance(classroom, dict):
                msg = "Invalid config: [classroom] must be a table."
                raise SystemExit(msg)
            classroom["url"] = next_url
            classroom["url_id"] = next_url_id
            if classroom_gh_id is not None:
                classroom["gh_id"] = classroom_gh_id
            elif "gh_id" not in classroom:
                classroom["gh_id"] = 0
            if classroom_slug is not None:
                classroom["slug"] = classroom_slug
            if classroom_title is not None:
                classroom["title"] = classroom_title
            if org is not None:
                classroom["org"] = org
            elif "org" not in classroom:
                classroom["org"] = ""
            classroom.pop("id", None)
        else:
            raw.pop("classroom", None)

    path.write_text(_dump_config_data(raw))
    reset_config()


def write_config(
    path: Path,
    classroom_url: str = "",
    classroom_url_id: int = 0,
    classroom_gh_id: int = 0,
    classroom_slug: str = "",
    classroom_title: str = "",
    org: str = "",
    canvas_base_url: str = "",
    canvas_course_id: int = 0,
) -> None:
    """Write a cass.toml file."""
    update_config(
        path,
        classroom_url=classroom_url or None,
        classroom_url_id=classroom_url_id or None,
        classroom_gh_id=classroom_gh_id if classroom_url else None,
        classroom_slug=classroom_slug if classroom_url else None,
        classroom_title=classroom_title if classroom_url else None,
        org=org if classroom_url else None,
        canvas_base_url=canvas_base_url
        if canvas_base_url and canvas_course_id
        else None,
        canvas_course_id=canvas_course_id
        if canvas_base_url and canvas_course_id
        else None,
    )
