"""Push to Canvas modal dialog."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any, cast

import duckdb
from nicegui import ui

from . import canvas_apply, canvas_preview
from .config import PendingChanges
from .grid import (
    clear_pending_cells,
    notify,
    reload_current_grid,
)


def build_preview_html(
    assignment_changes: list[dict[str, object]],
    grade_changes: list[dict[str, object]],
    has_conflicts: bool,
) -> str:
    """Build HTML for the push preview tables."""
    from html import escape

    parts: list[str] = []

    if assignment_changes:
        parts.append("<h4 class='text-sm font-semibold mb-1'>Assignment changes</h4>")
        parts.append('<table class="push-table"><thead><tr>')
        for h in ("Assignment", "Field", "On Canvas", "New value"):
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for ch in assignment_changes:
            cls = (
                "error-row"
                if "error" in ch
                else "conflict-row"
                if ch.get("conflict")
                else ""
            )
            parts.append(f'<tr class="{cls}">')
            if "error" in ch:
                name = escape(str(ch.get("name", "")))
                err = escape(str(ch.get("error", "")))
                parts.append(f'<td colspan="4" class="text-red-400">{name}: {err}</td>')
            else:
                name = escape(str(ch.get("name", "")))
                col = escape(str(ch.get("column", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}</td>")
                parts.append(f"<td>{col}{warn}</td>")
                parts.append(f'<td class="opacity-50">{live}</td>')
                parts.append(f'<td class="font-semibold">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if grade_changes:
        parts.append("<h4 class='text-sm font-semibold mt-4 mb-1'>Grade changes</h4>")
        parts.append('<table class="push-table"><thead><tr>')
        for h in ("Student \u2014 Assignment", "On Canvas", "New grade"):
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for ch in grade_changes:
            cls = (
                "error-row"
                if "error" in ch
                else "conflict-row"
                if ch.get("conflict")
                else ""
            )
            parts.append(f'<tr class="{cls}">')
            if "error" in ch:
                name = escape(str(ch.get("name", "")))
                err = escape(str(ch.get("error", "")))
                parts.append(f'<td colspan="3" class="text-red-400">{name}: {err}</td>')
            else:
                name = escape(str(ch.get("name", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}{warn}</td>")
                parts.append(f'<td class="opacity-50">{live}</td>')
                parts.append(f'<td class="font-semibold">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if has_conflicts:
        parts.append(
            '<div class="text-yellow-500 text-xs mt-3 p-2'
            " bg-yellow-500/10 rounded"
            '">'
            "\u26a0 Some Canvas values differ from when you "
            "last pulled. Pushing will overwrite.</div>"
        )

    return "".join(parts)


def open_push_modal(
    conn: duckdb.DuckDBPyConnection,
    pending: PendingChanges,
    update_pending_display: Any,
    grid_container: dict[str, Any],
    current_table: dict[str, str],
) -> None:
    """Open the Push to Canvas modal with preview/push workflow."""
    with ui.dialog() as dialog, ui.card().classes("min-w-[32rem] max-w-[40rem]"):
        dialog.open()

        ui.label("Push to Canvas").classes("text-lg font-bold mb-2")
        content_area = ui.element("div")
        action_area = ui.row().classes("w-full justify-end gap-2 mt-4")

        state: dict[str, Any] = {"phase": "loading", "preview": None}

        def render_loading() -> None:
            content_area.clear()
            with content_area:
                ui.label("Comparing with Canvas...").classes(
                    "opacity-50 text-center py-4"
                )
            action_area.clear()
            with action_area:
                ui.button("Cancel", on_click=dialog.close).props("flat")

        def render_preview(preview: dict[str, object]) -> None:
            changes = cast(
                list[dict[str, object]],
                preview.get("changes", []),
            )
            has_conflicts = cast(bool, preview.get("has_conflicts", False))
            content_area.clear()
            with content_area:
                if not changes:
                    ui.label("No pending changes").classes(
                        "opacity-50 text-center py-4"
                    )
                    return

                a_ch = [c for c in changes if c.get("table") == "canvas_assignments"]
                g_ch = [c for c in changes if c.get("table") == "canvas_grades"]
                ui.html(build_preview_html(a_ch, g_ch, has_conflicts))

            pushable = [c for c in changes if "error" not in c]
            action_area.clear()
            with action_area:
                ui.button("Cancel", on_click=dialog.close).props("flat")
                if pushable:
                    n = len(pushable)
                    ui.button(
                        f"Push {n} change{'s' if n != 1 else ''}",
                        on_click=lambda: do_push(),
                    ).props("color=primary")

        def render_pushing() -> None:
            content_area.clear()
            with content_area:
                ui.label("Pushing to Canvas...").classes("opacity-50 text-center py-4")
            action_area.clear()
            with action_area:
                ui.button(
                    "Pushing...",
                    on_click=lambda: None,
                ).props("color=primary disabled")

        def render_results(results: list[dict[str, object]]) -> None:
            succeeded = [r for r in results if r.get("ok")]
            failed = [r for r in results if not r.get("ok")]
            content_area.clear()
            with content_area:
                ui.label(f"{len(succeeded)} pushed, {len(failed)} failed").classes(
                    "font-semibold mb-2"
                )
                for r in results:
                    aid = r.get("canvas_id") or r.get("canvas_assignment_id") or "?"
                    if r.get("ok"):
                        ui.label(f"\u2713 Assignment {aid}").classes("text-green-400")
                    else:
                        err = r.get("error", "Unknown")
                        ui.label(f"\u2717 Assignment {aid}: {err}").classes(
                            "text-red-400"
                        )
            action_area.clear()
            with action_area:
                ui.button("Close", on_click=dialog.close).props("flat")

        def render_error(message: str) -> None:
            content_area.clear()
            with content_area:
                ui.label(message).classes("text-red-400")
            action_area.clear()
            with action_area:
                ui.button("Close", on_click=dialog.close).props("flat")

        def fetch_preview() -> None:
            try:
                preview = canvas_preview(conn, pending)
                state["phase"] = "preview"
                state["preview"] = preview
                render_preview(preview)
            except Exception as exc:
                state["phase"] = "error"
                render_error(str(exc))

        def do_push() -> None:
            state["phase"] = "pushing"
            render_pushing()
            ui.timer(0.1, execute_push, once=True)

        def execute_push() -> None:
            try:
                result = canvas_apply(conn, pending)
                if result["ok"]:
                    dialog.close()
                    clear_pending_cells()
                    update_pending_display()
                    notify("Pushed to Canvas")
                    reload_current_grid(
                        conn,
                        grid_container,
                        current_table["name"],
                    )
                else:
                    state["phase"] = "results"
                    render_results(
                        cast(
                            list[dict[str, object]],
                            result.get("results", []),
                        )
                    )
                    update_pending_display()
            except Exception as exc:
                dialog.close()
                notify(f"Push failed: {exc}", "negative")

        render_loading()
        ui.timer(0.1, fetch_preview, once=True)
