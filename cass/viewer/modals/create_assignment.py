"""Create Assignment modal dialog."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from nicegui import ui

from ...db import get_assignment_groups
from ..actions import (
    create_local_assignment,
    push_new_assignment,
    validate_assignment_fields,
)
from ..grid import notify

if TYPE_CHECKING:
    from ..page import ViewerPage


class CreateAssignmentModal:
    """Modal to create a new local assignment and auto-push to Canvas."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._build()

    def _build(self) -> None:
        with (
            ui.dialog() as self.dialog,
            ui.card().classes("v-modal-card-scroll"),
        ):
            ui.label("Create Assignment").classes("v-modal-title")
            ui.label(
                "Add a local assignment to canvas_assignments. "
                "Use Push to Canvas to sync it upstream."
            ).classes("v-modal-subtitle")

            self._name_input = (
                ui.input(label="Name", placeholder="e.g. Homework 3")
                .props("dense outlined")
                .classes("w-full")
            )
            self._points_input = (
                ui.number(label="Points Possible", value=0, min=0, format="%.1f")
                .props("dense outlined")
                .classes("w-full mt-1")
            )

            with (
                ui.input("Due Date")
                .props("dense outlined")
                .classes("w-full mt-1") as self._due_input
            ):
                with (
                    ui.menu().props("no-parent-event") as menu,
                    ui.date().bind_value(self._due_input),
                    ui.row().classes("justify-end"),
                ):
                    ui.button("Close", on_click=menu.close).props("flat")
                with self._due_input.add_slot("append"):
                    ui.icon("edit_calendar").on("click", menu.open).classes(
                        "cursor-pointer"
                    )

            group_values = get_assignment_groups(self.page.conn)
            group_options = {g: g for g in group_values} if group_values else {}
            self._group_select = (
                ui.select(
                    options=group_options,
                    label="Assignment Group",
                    value=None,
                    with_input=True,
                    new_value_mode="add-unique",
                )
                .props("dense outlined")
                .classes("w-full mt-1")
            )

            self._published_toggle = ui.switch("Published", value=False).classes("mt-1")

            self._error_label = ui.label("").classes("v-modal-error")
            self._error_label.set_visibility(False)

            self._status_label = ui.label("").classes("v-modal-status")
            self._status_label.set_visibility(False)

            with ui.row().classes("v-modal-actions"):
                ui.button("Cancel", on_click=self.dialog.close).props(
                    "flat dense no-caps size=sm"
                )
                self._create_btn = ui.button("Create", on_click=self._on_create).props(
                    "color=primary dense no-caps size=sm"
                )

    def open(self) -> None:
        self._name_input.value = ""
        self._points_input.value = 0
        self._due_input.value = ""
        self._error_label.set_visibility(False)
        self._status_label.set_visibility(False)
        self._create_btn.props(remove="disabled")
        self.dialog.open()

    async def _on_create(self) -> None:
        p = self.page
        name_val = self._name_input.value or ""
        pts = self._points_input.value

        errors = validate_assignment_fields(name=name_val, points=pts)
        if errors:
            self._error_label.text = " · ".join(errors)
            self._error_label.set_visibility(True)
            return

        self._error_label.set_visibility(False)
        due_val = self._due_input.value or None
        group_val = self._group_select.value or ""

        local_id = create_local_assignment(
            p.conn,
            name=name_val.strip(),
            points_possible=pts or 0.0,
            due_at=due_val if due_val and due_val.strip() else None,
            published=self._published_toggle.value,
            assignment_group=group_val,
        )

        self._status_label.text = "Pushing to Canvas..."
        self._status_label.set_visibility(True)
        self._create_btn.props("disabled")

        import asyncio

        from ...apis.canvas.client import CanvasClient
        from ...db import connect_db

        def _do_push() -> dict[str, object]:
            thread_conn = connect_db(p._project_root)
            with CanvasClient() as client:
                return push_new_assignment(thread_conn, local_id, client)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_push)

        if result["ok"]:
            self.dialog.close()
            notify(
                f"Created assignment: {name_val.strip()} "
                f"(Canvas ID {result['canvas_id']})"
            )
        else:
            self._status_label.text = f"Canvas error: {result['error']}"
            self._status_label.classes("v-text-error", remove="v-modal-status")
            self._create_btn.props(remove="disabled")
            notify(
                f"Created locally but Canvas push failed: {result['error']}",
                "warning",
            )

        if p.current_table in ("canvas_assignments", "canvas_grades"):
            p.load_table(p.current_table)
