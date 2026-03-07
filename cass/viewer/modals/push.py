"""Push to Canvas modal dialog."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, cast

from nicegui import ui

from .. import canvas_apply, canvas_preview
from ..actions import build_preview_html
from ..grid import (
    clear_pending_cells,
    find_grid,
    notify,
    reload_current_grid,
)

if TYPE_CHECKING:
    from ..page import ViewerPage


class PushModal:
    """Push-to-Canvas modal with preview/confirm/results phases."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._preview: dict[str, object] | None = None
        self._phase: str = "loading"

        with ui.dialog() as self.dialog, ui.card().classes("v-modal-card-lg"):
            ui.label("Push to Canvas").classes("v-modal-title")
            self._content_area = ui.element("div")
            self._action_area = ui.row().classes("v-modal-actions")

    def open(self) -> None:
        self._preview = None
        self._phase = "loading"
        self._render_loading()
        self.dialog.open()
        ui.timer(0.1, self._fetch_preview, once=True)

    # ------------------------------------------------------------------
    # Phase renderers
    # ------------------------------------------------------------------

    def _render_loading(self) -> None:
        self._content_area.clear()
        with self._content_area:
            ui.label("Comparing with Canvas...").classes("v-modal-empty")
        self._action_area.clear()
        with self._action_area:
            ui.button("Cancel", on_click=self.dialog.close).props("flat")

    def _render_preview(self) -> None:
        preview = self._preview or {}
        changes = cast(
            list[dict[str, object]],
            preview.get("changes", []),
        )
        has_conflicts = cast(bool, preview.get("has_conflicts", False))

        self._content_area.clear()
        with self._content_area:
            if not changes:
                ui.label("No pending changes").classes("v-modal-empty")
                return
            a_ch = [c for c in changes if c.get("table") == "canvas_assignments"]
            g_ch = [c for c in changes if c.get("table") == "canvas_grades"]
            ui.html(build_preview_html(a_ch, g_ch, has_conflicts))

        pushable = [c for c in changes if "error" not in c]
        self._action_area.clear()
        with self._action_area:
            ui.button("Cancel", on_click=self.dialog.close).props("flat")
            if pushable:
                n = len(pushable)
                ui.button(
                    f"Push {n} change{'s' if n != 1 else ''}",
                    on_click=self._do_push,
                ).props("color=primary")

    def _render_pushing(self) -> None:
        self._content_area.clear()
        with self._content_area:
            ui.label("Pushing to Canvas...").classes("v-modal-empty")
        self._action_area.clear()
        with self._action_area:
            ui.button("Pushing...", on_click=lambda: None).props(
                "color=primary disabled"
            )

    def _render_results(self, results: list[dict[str, object]]) -> None:
        succeeded = [r for r in results if r.get("ok")]
        failed = [r for r in results if not r.get("ok")]
        self._content_area.clear()
        with self._content_area:
            ui.label(f"{len(succeeded)} pushed, {len(failed)} failed").classes(
                "v-modal-result-header"
            )
            for r in results:
                aid = r.get("canvas_id") or r.get("canvas_assignment_id") or "?"
                if r.get("ok"):
                    ui.label(f"\u2713 Assignment {aid}").classes("v-text-success")
                else:
                    err = r.get("error", "Unknown")
                    ui.label(f"\u2717 Assignment {aid}: {err}").classes("v-text-error")
        self._action_area.clear()
        with self._action_area:
            ui.button("Close", on_click=self.dialog.close).props("flat")

    def _render_error(self, message: str) -> None:
        self._content_area.clear()
        with self._content_area:
            ui.label(message).classes("v-text-error")
        self._action_area.clear()
        with self._action_area:
            ui.button("Close", on_click=self.dialog.close).props("flat")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _fetch_preview(self) -> None:
        p = self.page
        try:
            self._preview = canvas_preview(p.conn, p.pending)
            self._phase = "preview"
            self._render_preview()
        except Exception as exc:
            self._phase = "error"
            self._render_error(str(exc))

    def _do_push(self) -> None:
        self._phase = "pushing"
        self._render_pushing()
        ui.timer(0.1, self._execute_push, once=True)

    def _execute_push(self) -> None:
        p = self.page
        try:
            result = canvas_apply(p.conn, p.pending)
            if result["ok"]:
                self.dialog.close()
                clear_pending_cells()
                p.update_pending_display()
                notify("Pushed to Canvas")
                reload_current_grid(
                    p.conn,
                    {"ref": p.grid_container},
                    p.current_table,
                )
                grid = find_grid({"ref": p.grid_container})
                if grid is not None:
                    grid.run_grid_method("refreshCells", {"force": True})  # pyright: ignore[reportUnknownMemberType]
            else:
                self._phase = "results"
                self._render_results(
                    cast(
                        list[dict[str, object]],
                        result.get("results", []),
                    )
                )
                p.update_pending_display()
        except Exception as exc:
            self.dialog.close()
            notify(f"Push failed: {exc}", "negative")
