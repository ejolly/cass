"""Viewer CSS loader — injects styles.css into the current NiceGUI page."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

from nicegui import ui

_CSS_PATH = Path(__file__).parent / "styles.css"
_css_cache: str | None = None

# Class constants used for dynamic toggling in Python code.
# Keep these in sync with the corresponding @layer rules in styles.css.
NAV_ITEM = "v-nav-item"
NAV_ITEM_ACTIVE = "v-nav-item-active"


def load_styles() -> None:
    """Inject the consolidated CSS into the current page.

    Uses ``<style type="text/tailwindcss">`` so that ``@apply``
    directives are processed by NiceGUI's Tailwind engine.
    """
    global _css_cache  # pyright: ignore[reportGlobalUsage]
    if _css_cache is None:
        _css_cache = _CSS_PATH.read_text()
    ui.add_head_html(f'<style type="text/tailwindcss">{_css_cache}</style>')
