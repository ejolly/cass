"""Delete Assignment modal dialog."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from nicegui import ui

from ..actions import (
    delete_assignment_from_canvas,
    list_assignments_for_select,
    purge_pending_for_assignment,
)
from ..grid import clear_pending_cells, notify

if TYPE_CHECKING:
    from ..page import ViewerPage


class DeleteAssignmentModal:
    """Modal to delete an assignment from Canvas and the local DB."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._options: dict[int, str] = {}
        self._build()

    def _build(self) -> None:
        with (
            ui.dialog() as self.dialog,
            ui.card().classes("v-modal-card"),
        ):
            ui.label("Delete Assignment").classes("v-modal-title")
            ui.label(
                "Remove an assignment from Canvas and the local database. "
                "This also deletes associated grades and submissions."
            ).classes("v-modal-subtitle")

            self._assignment_select = (
                ui.select(
                    options={},
                    label="Assignment",
                    with_input=True,
                )
                .props("dense outlined")
                .classes("w-full")
            )

            self._error_label = ui.label("").classes("v-modal-error")
            self._error_label.set_visibility(False)

            self._status_label = ui.label("").classes("v-modal-status")
            self._status_label.set_visibility(False)

            with ui.row().classes("v-modal-actions"):
                ui.button("Cancel", on_click=self.dialog.close).props(
                    "flat dense no-caps size=sm"
                )
                self._delete_btn = ui.button(
                    "Delete", on_click=self._on_delete, icon="delete"
                ).props("color=negative dense no-caps size=sm")

    def open(self) -> None:
        self._options = list_assignments_for_select(self.page.conn)
        self._assignment_select.options = self._options  # pyright: ignore[reportAttributeAccessIssue]
        self._assignment_select.value = None
        self._error_label.set_visibility(False)
        self._status_label.set_visibility(False)
        self._delete_btn.props(remove="disabled")
        self.dialog.open()

    async def _on_delete(self) -> None:
        p = self.page
        selected_id = self._assignment_select.value
        if selected_id is None:
            self._error_label.text = "Select an assignment."
            self._error_label.set_visibility(True)
            return

        canvas_id = int(selected_id)
        name = self._options.get(canvas_id, "Unknown")

        self._error_label.set_visibility(False)
        self._status_label.text = "Deleting..."
        self._status_label.set_visibility(True)
        self._delete_btn.props("disabled")

        import asyncio

        from ...canvas.client import CanvasClient

        def _do_delete() -> dict[str, object]:
            with CanvasClient() as client:
                return delete_assignment_from_canvas(p.conn, canvas_id, client)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_delete)

        purge_pending_for_assignment(p.pending, canvas_id)
        clear_pending_cells()
        p.update_pending_display()

        if result["ok"]:
            self.dialog.close()
            notify(f"Deleted assignment: {name}")
        else:
            self.dialog.close()
            notify(
                f"Deleted locally but Canvas error: {result['error']}",
                "warning",
            )

        if p.current_table in ("canvas_assignments", "canvas_grades"):
            p.load_table(p.current_table)
