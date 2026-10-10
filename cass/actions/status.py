"""Project status: config, auth, and local database overview."""

from __future__ import annotations

__docformat__ = "google"

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StatusCounts:
    """Row counts for the main Canvas tables."""

    students: int
    assignments: int
    submissions: int


@dataclass
class ProjectStatus:
    """Snapshot of a project's configuration and local database."""

    config_path: str
    course_url: str | None
    course_id: int | None
    auth_source: str | None
    db_path: str | None
    course_name: str | None
    counts: StatusCounts | None
    pending_changes: int | None


def count_pending(
    pending: dict[str, dict[str, dict[str, dict[str, object]]]],
) -> int:
    """Count pending column changes across all tables and rows."""
    return sum(len(cols) for rows in pending.values() for cols in rows.values())


def project_status(config_path: Path) -> ProjectStatus:
    """Collect the status of the project whose config is at *config_path*."""
    from .. import db
    from ..apis.canvas.auth import find_auth
    from .config import load_config

    cfg = load_config(config_path)
    course_url = None
    course_id = None
    auth_source = None
    if cfg.has_canvas:
        course_url = f"{cfg.canvas_base_url}/courses/{cfg.canvas_course_id}"
        course_id = cfg.canvas_course_id
        auth = find_auth(cfg.root)
        auth_source = auth.source if auth else None

    status = ProjectStatus(
        config_path=str(config_path),
        course_url=course_url,
        course_id=course_id,
        auth_source=auth_source,
        db_path=None,
        course_name=None,
        counts=None,
        pending_changes=None,
    )

    db_file = Path(db.db_path(cfg.root))
    if not db_file.exists():
        return status

    conn = db.connect_db(cfg.root)
    try:
        tables = {table.name for table in conn.tables}

        def count(table: str) -> int:
            return conn[table].count if table in tables else 0

        status.db_path = str(db_file)
        status.course_name = db.get_meta("course_name", conn)
        status.counts = StatusCounts(
            students=count("canvas_students"),
            assignments=count("canvas_assignments"),
            submissions=count("canvas_submissions"),
        )
        status.pending_changes = count_pending(db.get_pending_changes(conn))
    finally:
        conn.close()
    return status
