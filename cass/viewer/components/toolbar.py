"""Toolbar component for the viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from nicegui import ui

from ..grid import apply_search, export_csv, export_markdown

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..page import ViewerPage


class Toolbar:
    """Toolbar — table title, metadata, export buttons, search."""

    def __init__(
        self,
        page: ViewerPage,
        *,
        toggle_sidebar: Callable[[], None],
    ) -> None:
        self.page = page
        self._build(toggle_sidebar)

    def _build(self, toggle_sidebar: Callable[[], None]) -> None:
        p = self.page

        # Row 1: title, metadata, export
        with ui.row().classes("v-toolbar-row"):
            ui.button(icon="menu", on_click=toggle_sidebar).props(
                "flat dense round color=grey-6"
            )

            p.table_label = ui.label("").classes("v-table-label")
            p.meta_label = ui.label("").classes("v-meta-label")

            ui.button(
                "Export CSV",
                on_click=lambda: export_csv({"ref": p.grid_container}),
            ).props("outline dense no-caps size=sm color=grey-5").classes(
                "v-export-btn"
            )
            ui.button(
                "Export Markdown",
                on_click=lambda: export_markdown(
                    {"ref": p.grid_container},
                    {"name": p.current_table},
                ),
            ).props("outline dense no-caps size=sm color=grey-5").classes(
                "v-export-btn"
            )

        # Row 2: search
        with ui.row().classes("v-search-row"):
            p.search_input = (
                ui.input(placeholder="Search rows...")
                .props("dense outlined rounded")
                .classes("v-search-input")
            )
            p.search_input.on(
                "update:model-value",
                lambda e: apply_search(
                    {"ref": p.grid_container},
                    e.args,  # pyright: ignore[reportUnknownMemberType]
                ),
            )
