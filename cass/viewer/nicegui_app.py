"""NiceGUI-based database viewer — pure Python, AG Grid, no build step."""

from __future__ import annotations

__docformat__ = "google"

from nicegui import ui

from ..config import config_file_path
from ..db import DB_FILENAME
from ..db import reset as db_reset
from .grid import (
    get_tables,
    is_editable,
    pending_count,
    track_change,
)

# Re-export for tests and external consumers
__all__ = [
    "get_tables",
    "is_editable",
    "pending_count",
    "start_nicegui_server",
    "track_change",
]


# ---------------------------------------------------------------------------
# NiceGUI app
# ---------------------------------------------------------------------------


def _detect_state() -> str:
    """Return 'setup', 'pull', or 'ready' based on config/db presence."""
    from ..db import is_remote

    cfg_path = config_file_path()
    if cfg_path is None:
        return "setup"

    # Config exists — check database
    if is_remote():
        return "ready"

    from ..config import get_config

    cfg = get_config()
    db_file = cfg.root / DB_FILENAME
    if not db_file.exists():
        return "pull"

    return "ready"


def start_nicegui_server(port: int = 0) -> None:
    """Start the NiceGUI viewer, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.

    Routes based on project state:
    - No cass.toml → setup wizard
    - cass.toml but no database → auto-pull with progress
    - Both exist → normal table viewer
    """
    from .setup import pull_progress_page, setup_wizard_page

    @ui.page("/")
    def root_page() -> None:  # pyright: ignore[reportUnusedFunction]
        state = _detect_state()
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

    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass viewer",
        port=port if port > 0 else None,
        dark=True,
        reload=False,
        show=True,
        favicon="\U0001f4ca",
    )


def _render_viewer() -> None:
    """Render the main table viewer using the class-based ViewerPage."""
    import duckdb

    from ..db import db_path
    from .page import ViewerPage

    db_reset()
    conn = duckdb.connect(db_path())
    ViewerPage(conn)
