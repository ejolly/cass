"""Config discovery, loading, and writing for cass.

Searches for ``cass.toml`` starting from the current directory and walking
upward, unless ``set_config_path`` points at an explicit file (``--config``).
Config is loaded lazily on first access via ``get_config()``.
"""

from __future__ import annotations

__docformat__ = "google"

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "cass.toml"
_CANVAS_COURSE_URL_RE = re.compile(r"^(https?://[^/]+)/courses/(\d+)(?:[/?#].*)?$")


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
class CanvasQuizRef:
    """A quiz file declared in cass.toml, resolved relative to the config file."""

    file: Path


@dataclass
class Config:
    root: Path
    canvas_base_url: str = ""
    canvas_course_id: int = 0
    canvas_time_zone: str = ""
    canvas_modules: list[CanvasModuleSpec] = field(default_factory=list)
    canvas_assignments: list[CanvasAssignmentSpec] = field(default_factory=list)
    canvas_quizzes: list[CanvasQuizRef] = field(default_factory=list)
    motherduck_db: str = ""

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


_config_path_override: Path | None = None


def set_config_path(path: Path | None) -> None:
    """Point config discovery at an explicit ``cass.toml`` (``--config``).

    Pass ``None`` to return to walking up from the working directory.

    Raises:
        SystemExit: If *path* does not exist.
    """
    global _config_path_override
    if path is not None:
        path = _existing_config(path)
    _config_path_override = path
    reset_config()


def _existing_config(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"Config file not found: {resolved}")
    return resolved


def find_project_root(
    start: Path | None = None, config_path: Path | None = None
) -> Path:
    """Find the project root.

    With *config_path* (or a path set via ``set_config_path``) the root is that
    file's directory. Otherwise walk up from *start* (default: cwd) looking
    for ``cass.toml``.
    """
    explicit = config_path or _config_path_override
    if explicit is not None:
        return _existing_config(explicit).parent
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


def config_file() -> Path:
    """Return the config file in use (explicit path or ``<root>/cass.toml``)."""
    if _config_path_override is not None:
        return _config_path_override
    return find_project_root() / CONFIG_FILENAME


def config_file_path() -> Path | None:
    """Return the path to the config file, or None if it doesn't exist."""
    try:
        path = config_file()
    except SystemExit:
        return None
    return path if path.exists() else None


def load_config() -> Config:
    path = config_file()
    root = path.parent
    raw = read_config_data(path)

    canvas = raw.get("canvas", {})

    has_cv = "base_url" in canvas and "course_id" in canvas

    if not has_cv:
        raise SystemExit(f"Invalid config: {path} must have a [canvas] section.")

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

    quiz_refs = [
        CanvasQuizRef(file=(root / q["file"]).resolve())
        for q in canvas.get("quizzes", [])
        if "file" in q
    ]

    # Parse [database] section
    database = raw.get("database", {})
    motherduck_db = database.get("motherduck", "")

    return Config(
        root=root,
        canvas_base_url=canvas.get("base_url", ""),
        canvas_course_id=canvas.get("course_id", 0),
        canvas_time_zone=canvas.get("time_zone", ""),
        canvas_modules=module_specs,
        canvas_assignments=assignment_specs,
        canvas_quizzes=quiz_refs,
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
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def format_toml_value(value: object) -> str:
    """Render a scalar or flat list as a TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _format_toml_string(value)
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_toml_value(item) for item in value) + "]"
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
        lines.append(f"{key} = {format_toml_value(value)}")

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
                lines.append(f"{item_key} = {format_toml_value(item_value)}")


def _dump_config_data(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {format_toml_value(value)}")
            continue
        if lines:
            lines.append("")
        _write_table(lines, (key,), value)
    return "\n".join(lines).rstrip() + "\n"


def update_config(
    path: Path,
    *,
    canvas_base_url: str | None = None,
    canvas_course_id: int | None = None,
    canvas_time_zone: str | None = None,
) -> None:
    """Update Canvas settings in ``cass.toml`` while preserving other data.

    A leftover ``[classroom]`` table from older versions is removed on every
    rewrite.
    """
    raw = read_config_data(path)
    raw.pop("classroom", None)

    if any(
        v is not None for v in (canvas_base_url, canvas_course_id, canvas_time_zone)
    ):
        canvas = raw.setdefault("canvas", {})
        if not isinstance(canvas, dict):
            msg = "Invalid config: [canvas] must be a table."
            raise SystemExit(msg)
        if canvas_base_url is not None:
            canvas["base_url"] = canvas_base_url
        if canvas_course_id is not None:
            canvas["course_id"] = canvas_course_id
        if canvas_time_zone is not None:
            canvas["time_zone"] = canvas_time_zone

    path.write_text(_dump_config_data(raw))
    reset_config()


def write_config(
    path: Path,
    canvas_base_url: str = "",
    canvas_course_id: int = 0,
) -> None:
    """Write a cass.toml file."""
    both = bool(canvas_base_url and canvas_course_id)
    update_config(
        path,
        canvas_base_url=canvas_base_url if both else None,
        canvas_course_id=canvas_course_id if both else None,
    )
