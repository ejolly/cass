"""Delete Assignment modal dialog for the viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, Any

import duckdb
from nicegui import ui

from .config import PendingChanges
from .grid import clear_pending_cells, notify

if TYPE_CHECKING:
    from ..canvas.client import CanvasClient


def list_assignments_for_select(
    conn: duckdb.DuckDBPyConnection,
) -> dict[int, str]:
    """Return {canvas_id: name} for all assignments, sorted by name."""
    rows = conn.execute(
        "SELECT canvas_id, name FROM canvas_assignments ORDER BY name"
    ).fetchall()
    return {int(r[0]): r[1] for r in rows}


def delete_local_assignment(
    conn: duckdb.DuckDBPyConnection,
    canvas_id: int,
) -> None:
    """Delete an assignment and all related rows from the local DB."""
    conn.execute(
        "DELETE FROM canvas_grades WHERE canvas_assignment_id = ?", [canvas_id]
    )
    conn.execute(
        "DELETE FROM canvas_submissions WHERE canvas_assignment_id = ?", [canvas_id]
    )
    conn.execute(
        "DELETE FROM _canvas_grades_synced WHERE canvas_assignment_id = ?", [canvas_id]
    )
    conn.execute(
        "DELETE FROM _canvas_assignments_synced WHERE canvas_id = ?", [canvas_id]
    )
    conn.execute("DELETE FROM canvas_assignments WHERE canvas_id = ?", [canvas_id])


def delete_assignment_from_canvas(
    conn: duckdb.DuckDBPyConnection,
    canvas_id: int,
    client: CanvasClient,
) -> dict[str, object]:
    """Delete an assignment from Canvas (if remote) and locally.

    Local-only assignments (negative IDs) skip the Canvas API call.
    On Canvas API error, the local deletion still proceeds.

    Returns:
        Result dict with ``ok`` and optionally ``error``.
    """
    canvas_error: str | None = None
    if canvas_id > 0:
        try:
            client.delete_assignment(canvas_id)
        except Exception as e:
            canvas_error = str(e)

    delete_local_assignment(conn, canvas_id)

    if canvas_error:
        return {"ok": False, "error": canvas_error}
    return {"ok": True}


def purge_pending_for_assignment(
    pending: PendingChanges,
    canvas_id: int,
) -> None:
    """Remove any pending changes referencing a deleted assignment."""
    import json

    # canvas_assignments: pk_key is str(canvas_id)
    assign_pending = pending.get("canvas_assignments", {})
    assign_pending.pop(str(canvas_id), None)
    if not assign_pending:
        pending.pop("canvas_assignments", None)

    # canvas_grades: pk_key is JSON with canvas_assignment_id
    grade_pending = pending.get("canvas_grades", {})
    to_remove = [
        pk_key
        for pk_key in grade_pending
        if json.loads(pk_key).get("canvas_assignment_id") == canvas_id
    ]
    for pk_key in to_remove:
        grade_pending.pop(pk_key, None)
    if not grade_pending:
        pending.pop("canvas_grades", None)


def open_delete_assignment_modal(
    conn: duckdb.DuckDBPyConnection,
    pending: PendingChanges,
    update_pending_display: Any,
    grid_container: dict[str, Any],
    current_table: dict[str, str],
    load_table: Any,
) -> None:
    """Open a modal to delete an assignment."""
    options = list_assignments_for_select(conn)

    with (
        ui.dialog() as dialog,
        ui.card().classes("min-w-[28rem] max-w-[36rem]"),
    ):
        dialog.open()

        ui.label("Delete Assignment").classes("text-lg font-bold mb-2")
        ui.label(
            "Remove an assignment from Canvas and the local database. "
            "This also deletes associated grades and submissions."
        ).classes("text-xs opacity-60 mb-3")

        assignment_select = (
            ui.select(
                options=options,
                label="Assignment",
                with_input=True,
            )
            .props("dense outlined")
            .classes("w-full")
        )

        error_label = ui.label("").classes("text-red-400 text-xs mt-1")
        error_label.set_visibility(False)

        status_label = ui.label("").classes("text-xs opacity-70 mt-1")
        status_label.set_visibility(False)

        async def _on_delete() -> None:
            selected_id = assignment_select.value
            if selected_id is None:
                error_label.text = "Select an assignment."
                error_label.set_visibility(True)
                return

            canvas_id = int(selected_id)
            name = options.get(canvas_id, "Unknown")

            error_label.set_visibility(False)
            status_label.text = "Deleting..."
            status_label.set_visibility(True)
            delete_btn.props("disabled")

            import asyncio

            from ..canvas.client import CanvasClient

            def _do_delete() -> dict[str, object]:
                with CanvasClient() as client:
                    return delete_assignment_from_canvas(conn, canvas_id, client)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _do_delete)

            # Purge orphaned pending entries for the deleted assignment
            purge_pending_for_assignment(pending, canvas_id)
            clear_pending_cells()
            update_pending_display()

            if result["ok"]:
                dialog.close()
                notify(f"Deleted assignment: {name}")
            else:
                dialog.close()
                notify(
                    f"Deleted locally but Canvas error: {result['error']}",
                    "warning",
                )

            # Refresh grid (load_table rebuilds grid + restores remaining pending)
            tbl = current_table["name"]
            if tbl in ("canvas_assignments", "canvas_grades"):
                load_table(tbl)

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dialog.close).props(
                "flat dense no-caps size=sm"
            )
            delete_btn = ui.button("Delete", on_click=_on_delete, icon="delete").props(
                "color=negative dense no-caps size=sm"
            )
