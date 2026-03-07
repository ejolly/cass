"""Pending cell highlight management — JS set operations for AG Grid."""

from __future__ import annotations

__docformat__ = "google"

import json

from nicegui import ui

from ..config import PendingChanges


def mark_pending_cell(
    grid: ui.aggrid,
    row_id: str,
    col_field: str,
    is_pending: bool,
) -> None:
    """Add or remove a cell from the JS pending set and refresh its style."""
    escaped_key = json.dumps(f"{row_id}::{col_field}")
    if is_pending:
        js = (
            f"window._pendingCells = window._pendingCells || new Set();"
            f"window._pendingCells.add({escaped_key})"
        )
    else:
        js = f"if (window._pendingCells) window._pendingCells.delete({escaped_key})"
    ui.run_javascript(js)
    grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
        "refreshCells",
        {"columns": [col_field], "force": True},
    )


def clear_pending_cells() -> None:
    """Clear all pending cell highlights."""
    ui.run_javascript("if (window._pendingCells) window._pendingCells.clear()")


def restore_pending_cells(
    grid: ui.aggrid,
    pending: PendingChanges,
    table_name: str,
    pk_cols: list[str],
    *,
    is_gradebook: bool = False,
) -> None:
    """Mark all existing pending cells in the JS set and refresh the grid.

    Called on table load so that persisted pending changes appear highlighted.
    """
    table_pending = pending.get(table_name, {})
    if not table_pending:
        return

    js_parts: list[str] = ["window._pendingCells = window._pendingCells || new Set();"]
    for pk_key, cols in table_pending.items():
        if is_gradebook:
            pk = json.loads(pk_key)
            row_id = str(pk["canvas_user_id"])
            for col in cols:
                if col == "posted_grade":
                    col_field = f"_a{pk['canvas_assignment_id']}"
                else:
                    col_field = col
                js_parts.append(
                    f"window._pendingCells.add({json.dumps(f'{row_id}::{col_field}')});"
                )
        else:
            if len(pk_cols) == 1:
                row_id = pk_key
            else:
                pk = json.loads(pk_key)
                row_id = "::".join(str(pk[c]) for c in pk_cols)
            for col in cols:
                js_parts.append(
                    f"window._pendingCells.add({json.dumps(f'{row_id}::{col}')});"
                )

    ui.run_javascript("".join(js_parts))
    grid.run_grid_method("refreshCells", {"force": True})  # pyright: ignore[reportUnknownMemberType]
