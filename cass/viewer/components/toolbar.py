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
        with ui.row().classes(
            "w-full items-center gap-2 px-4 py-2 border-b border-white/10 bg-[#1d1d1d]"
        ):
            ui.button(icon="menu", on_click=toggle_sidebar).props(
                "flat dense round color=grey-6"
            )

            p.table_label = ui.label("").classes("text-sm font-semibold")
            p.meta_label = ui.label("").classes("text-xs opacity-50")

            ui.button(
                "Export CSV",
                on_click=lambda: export_csv({"ref": p.grid_container}),
            ).props("outline dense no-caps size=sm color=grey-5").classes("text-xs")
            ui.button(
                "Export Markdown",
                on_click=lambda: export_markdown(
                    {"ref": p.grid_container},
                    {"name": p.current_table},
                ),
            ).props("outline dense no-caps size=sm color=grey-5").classes("text-xs")

        # Row 2: search
        with ui.row().classes("w-full px-4 py-1 border-b border-white/10 bg-[#1d1d1d]"):
            p.search_input = (
                ui.input(placeholder="Search rows...")
                .props("dense outlined rounded")
                .classes("w-1/3 min-w-[12rem] text-xs")
            )
            p.search_input.on(
                "update:model-value",
                lambda e: apply_search(
                    {"ref": p.grid_container},
                    e.args,  # pyright: ignore[reportUnknownMemberType]
                ),
            )
