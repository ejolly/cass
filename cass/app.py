"""NiceGUI app configuration — route definitions and app setup.

This module defines all NiceGUI routes and is imported by both the native
entry point (``__main__``) and the CLI ``cass-cli view`` command.  It does
**not** call ``ui.run()`` — callers decide how to start the server.
"""

from __future__ import annotations

__docformat__ = "google"

from nicegui import ui

from .config import config_file_path
from .db import DB_FILENAME
from .db import get_tables as get_tables
from .db import is_editable as is_editable
from .db import reset as db_reset
from .viewer.actions import pending_count as pending_count
from .viewer.actions import track_change as track_change

# Re-export for tests and external consumers
__all__ = [
    "configure_routes",
    "get_tables",
    "is_editable",
    "pending_count",
    "track_change",
]


# ---------------------------------------------------------------------------
# State detection
# ---------------------------------------------------------------------------


def detect_state() -> str:
    """Return 'setup', 'pull', or 'ready' based on config/db presence."""
    from .db import is_remote

    cfg_path = config_file_path()
    if cfg_path is None:
        return "setup"

    if is_remote():
        return "ready"

    from .config import get_config

    cfg = get_config()
    db_file = cfg.root / DB_FILENAME
    if not db_file.exists():
        return "pull"

    return "ready"


# ---------------------------------------------------------------------------
# Route configuration
# ---------------------------------------------------------------------------


def configure_routes() -> None:
    """Register all NiceGUI page routes.

    Call this once before ``ui.run()``.  Safe to call multiple times
    (NiceGUI deduplicates page registrations).
    """

    from .viewer.setup import pull_progress_page, setup_wizard_page

    @ui.page("/")
    def root_page() -> None:  # pyright: ignore[reportUnusedFunction]
        state = detect_state()
        if state == "setup":
            setup_wizard_page(on_complete=lambda: ui.navigate.to("/pull"))
        elif state == "pull":
            pull_progress_page(on_complete=lambda: ui.navigate.to("/view"))
        else:
            ui.navigate.to("/view")

    @ui.page("/pull")
    def pull_page() -> None:  # pyright: ignore[reportUnusedFunction]
        pull_progress_page(on_complete=lambda: ui.navigate.to("/view"))

    @ui.page("/view")
    def view_page() -> None:  # pyright: ignore[reportUnusedFunction]
        _render_viewer()


def _render_viewer() -> None:
    """Render the main table viewer using the class-based ViewerPage."""
    import duckdb

    from .db import db_path
    from .viewer.page import ViewerPage

    db_reset()
    conn = duckdb.connect(db_path())
    ViewerPage(conn)
