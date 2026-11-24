"""Push to Canvas modal dialog."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, cast

from nicegui import ui

from ...db import (
    can_be_approved,
    count_pending,
    count_postable,
    count_unreleased,
    hold_back_unapproved,
    refresh_pending,
)
from .. import canvas_apply, canvas_preview
from ..actions import build_preview_html
from ..grid import (
    clear_pending_cells,
    find_grid,
    notify,
    reload_current_grid,
)

if TYPE_CHECKING:
    from ...db import PendingChanges
    from ..page import ViewerPage


class PushModal:
    """Push-to-Canvas modal with preview/confirm/results phases."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._preview: dict[str, object] | None = None
        self._phase: str = "loading"
        self._overwrite_conflicts = False
        self._allow_over_points = False
        self._allow_clears = False
        self._release_grades = False
        self._n_postable = 0

        with ui.dialog() as self.dialog, ui.card().classes("v-modal-card-lg"):
            ui.label("Push to Canvas").classes("v-modal-title")
            self._content_area = ui.element("div")
            self._action_area = ui.row().classes("v-modal-actions")

    def open(self) -> None:
        self._preview = None
        self._overwrite_conflicts = False
        self._allow_over_points = False
        self._allow_clears = False
        self._release_grades = False
        self._n_postable = 0
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
            n_conflicts = sum(
                1 for c in changes if c.get("conflict") and can_be_approved(c)
            )
            n_over = sum(
                1 for c in changes if c.get("over_points") and can_be_approved(c)
            )
            if n_conflicts:
                ui.checkbox(
                    f"Overwrite {n_conflicts} value(s) changed on Canvas "
                    "since your last pull",
                    on_change=lambda e: self._approve("conflicts", bool(e.value)),
                )
            if n_over:
                ui.checkbox(
                    f"Push {n_over} grade(s) above points possible",
                    on_change=lambda e: self._approve("over_points", bool(e.value)),
                )
            n_clears = sum(1 for c in changes if c.get("clears") and can_be_approved(c))
            if n_clears:
                ui.checkbox(
                    f"Remove {n_clears} cleared grade(s) from Canvas",
                    on_change=lambda e: self._approve("clears", bool(e.value)),
                )
            self._release_area = ui.element("div")
        self._render_preview_actions()

    def _approve(self, kind: str, value: bool) -> None:
        if kind == "conflicts":
            self._overwrite_conflicts = value
        elif kind == "clears":
            self._allow_clears = value
        else:
            self._allow_over_points = value
        self._render_preview_actions()

    def _render_release_checkbox(self, to_push: PendingChanges) -> None:
        """Offer to release the pushed grades, unticked whenever N changes."""
        n_postable = count_postable(to_push, self._preview or {})
        if n_postable == self._n_postable:
            return
        self._n_postable = n_postable
        self._release_grades = False
        self._release_area.clear()
        if n_postable:
            with self._release_area:
                ui.checkbox(
                    f"Release {n_postable} pushed grade(s) to students",
                    on_change=lambda e: self._approve_release(bool(e.value)),
                )

    def _approve_release(self, value: bool) -> None:
        self._release_grades = value

    def _split_pending(self) -> tuple[PendingChanges, list[dict[str, object]]]:
        return hold_back_unapproved(
            self.page.pending,
            self._preview or {},
            overwrite_conflicts=self._overwrite_conflicts,
            allow_over_points=self._allow_over_points,
            allow_clears=self._allow_clears,
        )

    def _render_preview_actions(self) -> None:
        to_push, held = self._split_pending()
        n = count_pending(to_push)
        self._render_release_checkbox(to_push)
        self._action_area.clear()
        with self._action_area:
            if held:
                ui.label(f"{len(held)} held back; they stay pending").classes(
                    "opacity-70"
                )
            ui.button("Cancel", on_click=self.dialog.close).props("flat")
            if n:
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

    def _render_results(
        self,
        results: list[dict[str, object]],
        held: list[dict[str, object]] | None = None,
    ) -> None:
        succeeded = [r for r in results if r.get("ok") and "action" not in r]
        failed = [r for r in results if not r.get("ok")]
        held = held or []
        self._content_area.clear()
        with self._content_area:
            ui.label(
                f"{len(succeeded)} pushed, {len(failed)} failed, {len(held)} held back"
            ).classes("v-modal-result-header")
            for h in held:
                ui.label(f"\u23f8 {h.get('name', '?')}: {h.get('held')}").classes(
                    "opacity-70"
                )
            for r in results:
                aid = r.get("canvas_id") or r.get("canvas_assignment_id") or "?"
                if r.get("ok"):
                    note = ": released to students" if "action" in r else ""
                    if r.get("unreleased"):
                        note = ": " + self._unreleased_note(cast(int, r["unreleased"]))
                    ui.label(f"\u2713 Assignment {aid}{note}").classes("v-text-success")
                else:
                    err = r.get("error", "Unknown")
                    ui.label(f"\u2717 Assignment {aid}: {err}").classes("v-text-error")
        self._action_area.clear()
        with self._action_area:
            ui.button("Close", on_click=self.dialog.close).props("flat")

    @staticmethod
    def _unreleased_note(count: int) -> str:
        return (
            f"{count} grade(s) pushed but not released to students; post them in Canvas"
        )

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

    async def _fetch_preview(self) -> None:
        import asyncio

        from ...db import connect_db

        p = self.page
        pending_snapshot = p.pending

        def _blocking() -> dict[str, object]:
            thread_conn = connect_db(p._project_root)
            return canvas_preview(thread_conn, pending_snapshot)

        try:
            self._preview = await asyncio.get_event_loop().run_in_executor(
                None, _blocking
            )
            self._phase = "preview"
            self._render_preview()
        except Exception as exc:
            self._phase = "error"
            self._render_error(str(exc))

    def _do_push(self) -> None:
        self._phase = "pushing"
        self._render_pushing()
        ui.timer(0.1, self._execute_push, once=True)

    async def _execute_push(self) -> None:
        import asyncio

        from ...db import connect_db

        p = self.page
        to_push, held = self._split_pending()
        preview = self._preview
        post_grades = self._release_grades

        def _blocking() -> dict[str, object]:
            thread_conn = connect_db(p._project_root)
            return canvas_apply(
                thread_conn, to_push, post_grades=post_grades, preview=preview
            )

        try:
            result = await asyncio.get_event_loop().run_in_executor(None, _blocking)
            # Pending changes now live in the DB diff; reload them so pushed
            # changes drop out and held-back ones stay highlighted.
            refresh_pending(p.pending, p.conn)
            clear_pending_cells()
            p.update_pending_display()
            reload_current_grid(
                p.conn,
                {"ref": p.grid_container},
                p.current_table,
            )
            grid = find_grid({"ref": p.grid_container})
            if grid is not None:
                grid.run_grid_method("refreshCells", {"force": True})  # pyright: ignore[reportUnknownMemberType]
            if result["ok"] and not held:
                self.dialog.close()
                n_unreleased = count_unreleased(result)
                if n_unreleased:
                    notify(self._unreleased_note(n_unreleased), "warning")
                else:
                    notify("Pushed to Canvas")
            else:
                self._phase = "results"
                self._render_results(
                    cast(list[dict[str, object]], result.get("results", [])),
                    held,
                )
        except Exception as exc:
            self.dialog.close()
            notify(f"Push failed: {exc}", "negative")
