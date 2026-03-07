"""NiceGUI-based database viewer — browser mode entry point.

This module is a thin wrapper around :mod:`cass.app`.  It re-exports
symbols that tests and other consumers historically imported from here
and provides ``start_nicegui_server()`` for the ``cass-cli view`` command.
"""

from __future__ import annotations

__docformat__ = "google"

from ..app import detect_state as _detect_state
from ..app import get_tables as get_tables
from ..app import is_editable as is_editable
from ..app import pending_count as pending_count
from ..app import track_change as track_change

# Re-export for tests and external consumers
__all__ = [
    "_detect_state",
    "get_tables",
    "is_editable",
    "pending_count",
    "start_nicegui_server",
    "track_change",
]


def start_nicegui_server(port: int = 0) -> None:
    """Start the NiceGUI viewer in the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
    """
    from nicegui import ui

    from ..app import configure_routes

    configure_routes()
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass viewer",
        port=port if port > 0 else None,
        dark=True,
        reload=False,
        show=True,
        favicon="\U0001f4ca",
    )
