"""NiceGUI-based database viewer — pure Python, AG Grid, no build step."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

from nicegui import ui

from ..actions.config import config_file_path
from ..db import DB_FILENAME
from ..db import get_tables as get_tables
from ..db import is_editable as is_editable
from .actions import pending_count as pending_count
from .actions import track_change as track_change

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
    cfg_path = config_file_path()
    if cfg_path is None:
        return "setup"

    from ..actions.config import get_config

    db_file = get_config().root / DB_FILENAME
    if not db_file.exists():
        return "pull"

    return "ready"


def start_nicegui_server(
    port: int = 0,
    *,
    project_root: Path | None = None,
    generic_file: Path | None = None,
) -> None:
    """Start the NiceGUI viewer, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
        project_root: Path to the cass project root (cass-specific viewer).
        generic_file: Path to a .duckdb or .db file (generic viewer).

    Routes based on project state (when generic_file is None):
    - No cass.toml → setup wizard
    - cass.toml but no database → auto-pull with progress
    - Both exist → normal table viewer
    """
    if generic_file is not None:

        @ui.page("/")
        def generic_root() -> None:  # pyright: ignore[reportUnusedFunction]
            _render_generic_viewer(generic_file)

        title = f"cass \u2014 {generic_file.name}"
    else:
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
            _render_viewer(project_root)

        title = "cass viewer"

    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title=title,
        port=port if port > 0 else None,
        dark=True,
        reload=False,
        show=True,
        favicon="\U0001f4ca",
    )


def _render_generic_viewer(filepath: Path) -> None:
    """Render the generic viewer for an arbitrary SQLite/DuckDB file."""
    from ..db.ibis_adapter import connect_file
    from .generic_page import GenericViewerPage

    con = connect_file(filepath)
    GenericViewerPage(con, filepath)


def _render_viewer(project_root: Path | None = None) -> None:
    """Render the main table viewer using the class-based ViewerPage."""
    from ..db import get_db
    from .page import ViewerPage

    conn = get_db(project_root)
    ViewerPage(conn, project_root=project_root)
