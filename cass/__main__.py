"""Native NiceGUI entry point for cass.

Run with ``python -m cass`` or via the ``cass`` console script.
Uses pywebview for a native desktop window.
"""

from __future__ import annotations

__docformat__ = "google"

from multiprocessing import freeze_support

from nicegui import app, ui

# Native window config — MUST be outside the main guard so it applies
# before freeze_support() intercepts the subprocess.
app.native.window_args["resizable"] = True  # pyright: ignore[reportUnknownMemberType]


def main() -> None:
    """Configure routes and launch the NiceGUI native app."""
    from nicegui import native

    from cass.app import configure_routes

    configure_routes()
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass",
        dark=True,
        native=True,
        reload=False,
        port=native.find_open_port(),
        favicon="\U0001f4ca",
    )


if __name__ == "__main__":
    freeze_support()
    main()
