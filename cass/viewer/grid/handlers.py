"""AG Grid edit handlers — attach cellValueChanged callbacks."""

from __future__ import annotations

__docformat__ = "google"

import json
from typing import Any

import sqlite_utils
from nicegui import ui

from ...db import update_cell, upsert_canvas_grade
from ..actions import track_change
from ..config import PendingChanges
from .pending import mark_pending_cell
from .utils import notify

# ---------------------------------------------------------------------------
# Date autocommit
# ---------------------------------------------------------------------------

_DATE_AUTOCOMMIT_JS = """
(e) => {
    const input = e.api.getCellEditorInstances()[0]?.getGui()
        ?.querySelector('input[type="date"], input[type="datetime-local"]');
    if (input) {
        input.addEventListener('change', () => e.api.stopEditing(), {once: true});
    }
}
""".strip()


def attach_date_autocommit(grid: ui.aggrid) -> None:
    """Auto-commit date/datetime editors on value selection."""
    grid.options[":onCellEditingStarted"] = _DATE_AUTOCOMMIT_JS  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Boolean checkbox toggle (bypasses edit mode for reliable single-click)
# ---------------------------------------------------------------------------

_CHECKBOX_TOGGLE_JS = """
(params) => {
    if (params.colDef.cellRenderer === 'agCheckboxCellRenderer') {
        params.node.setDataValue(params.colDef.field, params.value ? 0 : 1);
    }
}
""".strip()


def attach_checkbox_toggle(grid: ui.aggrid) -> None:
    """Toggle boolean cells on single click via JS, bypassing edit mode."""
    grid.options[":onCellClicked"] = _CHECKBOX_TOGGLE_JS  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Regular table edit handler
# ---------------------------------------------------------------------------


def attach_edit_handler(
    grid: ui.aggrid,
    conn: sqlite_utils.Database,
    table_name: str,
    pk_cols: list[str],
    pending: PendingChanges,
    update_pending_display: Any,
) -> None:
    """Attach cellValueChanged handler to an AG Grid."""

    def on_cell_changed(e: Any) -> None:
        data = e.args
        col_field = data.get("colId")
        if not col_field:
            col_def = data.get("colDef")
            col_field = col_def["field"] if col_def else None
        if col_field is None or "value" not in data:
            return
        new_value = data["value"]
        row = data["data"]

        pk = {col: row[col] for col in pk_cols}
        result = update_cell(conn, table_name, pk, col_field, new_value)

        if result["ok"]:
            track_change(
                pending,
                table_name,
                pk,
                col_field,
                result["old_value"],
                new_value,
            )
            update_pending_display()
            notify(f"Saved {col_field}")

            # Determine AG Grid row ID (mirrors row_id_js)
            if len(pk_cols) == 1:
                row_id = str(row[pk_cols[0]])
            else:
                row_id = "::".join(str(row[c]) for c in pk_cols)
            # Check if change is still pending after track_change
            pk_key = (
                str(next(iter(pk.values())))
                if len(pk) == 1
                else json.dumps(pk, sort_keys=True)
            )
            still_pending = (
                table_name in pending
                and pk_key in pending[table_name]
                and col_field in pending[table_name][pk_key]
            )
            mark_pending_cell(grid, row_id, col_field, still_pending)
        else:
            notify(
                f"Error: {result.get('error', 'unknown')}",
                "negative",
            )

    grid.on("cellValueChanged", on_cell_changed)


# ---------------------------------------------------------------------------
# Gradebook edit handler
# ---------------------------------------------------------------------------


def attach_gradebook_edit_handler(
    grid: ui.aggrid,
    conn: sqlite_utils.Database,
    pending: PendingChanges,
    update_pending_display: Any,
) -> None:
    """Attach edit handler for the pivoted gradebook grid."""

    def on_cell_changed(e: Any) -> None:
        data = e.args
        col_field = data.get("colId")
        if not col_field:
            col_def = data.get("colDef")
            col_field = col_def["field"] if col_def else None
        if not col_field or not col_field.startswith("_a") or "value" not in data:
            return

        canvas_assignment_id = int(col_field[2:])  # strip "_a" prefix
        canvas_user_id = data["data"]["_canvas_user_id"]
        new_grade = data["value"] or ""

        old_value = upsert_canvas_grade(
            conn, canvas_user_id, canvas_assignment_id, new_grade
        )

        pk: dict[str, object] = {
            "canvas_user_id": canvas_user_id,
            "canvas_assignment_id": canvas_assignment_id,
        }
        track_change(
            pending,
            "canvas_grades",
            pk,
            "posted_grade",
            old_value,
            new_grade,
        )
        update_pending_display()
        notify("Saved grade")

        # Row ID is _canvas_user_id; check if change is still pending
        row_id = str(canvas_user_id)
        pk_key = json.dumps(dict(sorted(pk.items())), sort_keys=True)
        still_pending = (
            "canvas_grades" in pending
            and pk_key in pending["canvas_grades"]
            and "posted_grade" in pending["canvas_grades"][pk_key]
        )
        mark_pending_cell(grid, row_id, col_field, still_pending)

    grid.on("cellValueChanged", on_cell_changed)
