"""AG Grid column defs and edit handler for the generic DB viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

from ibis import BaseBackend
from nicegui import ui


def build_generic_column_defs(
    schema: list[tuple[str, str]],
    pk_cols: list[str],
    *,
    editable: bool = True,
    use_rowid: bool = False,
    categoricals: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Build AG Grid column definitions from an ibis schema.

    Args:
        schema: List of (column_name, type_string) tuples.
        pk_cols: Primary key column names.
        editable: Whether non-PK columns should be editable.
        use_rowid: If True, add a hidden rowid column for editing.
        categoricals: Mapping of column name to list of distinct values
            for columns that should use a dropdown selector.
    """
    categoricals = categoricals or {}
    defs: list[dict[str, Any]] = []
    for name, dtype in schema:
        dtype_lower = dtype.lower()
        col_def: dict[str, Any] = {
            "headerName": name,
            "field": name,
            "sortable": True,
            "filter": False,
            "resizable": True,
        }

        is_pk = name in pk_cols
        col_is_editable = editable and not is_pk

        if is_pk:
            col_def["headerName"] = f"{name} (PK)"
            col_def["cellStyle"] = {
                "fontWeight": "bold",
                "opacity": "0.6",
            }

        if col_is_editable:
            col_def["editable"] = True

            if name in categoricals:
                col_def["cellEditor"] = "agSelectCellEditor"
                col_def["cellEditorParams"] = {"values": categoricals[name]}
            elif any(
                t in dtype_lower for t in ("int", "float", "double", "real", "decimal")
            ):
                col_def["cellEditor"] = "agNumberCellEditor"
                params: dict[str, Any] = {"showStepperButtons": True}
                if "int" in dtype_lower:
                    params["precision"] = 0
                    params["step"] = 1
                col_def["cellEditorParams"] = params
            elif "bool" in dtype_lower:
                col_def["cellRenderer"] = "agCheckboxCellRenderer"
            elif "timestamp" in dtype_lower:
                col_def["cellEditor"] = "agDateStringCellEditor"
                col_def["cellEditorParams"] = {"includeTime": True}
            elif "date" in dtype_lower:
                col_def["cellEditor"] = "agDateStringCellEditor"

        defs.append(col_def)

    if use_rowid:
        defs.append({"field": "rowid", "hide": True})

    return defs


def attach_generic_edit_handler(
    grid: ui.aggrid,
    con: BaseBackend,
    table: str,
    pk_cols: list[str],
    *,
    use_rowid: bool = False,
) -> None:
    """Attach cell-change handler to an AG Grid for generic editing."""
    from ..db.ibis_adapter import update_cell

    async def _on_cell_changed(e: Any) -> None:
        args = e.args
        col = args["colId"]
        new_val = args["value"]
        data = args["data"]

        pk_col = pk_cols[0] if pk_cols else "rowid"
        pk_val = data.get(pk_col)

        result = update_cell(con, table, pk_col, pk_val, col, new_val)
        if result.get("ok"):
            ui.notify(f"Updated {col}", type="positive", position="bottom")
        else:
            ui.notify(
                f"Error: {result.get('error', 'unknown')}",
                type="negative",
                position="bottom",
            )

    grid.on("cellValueChanged", _on_cell_changed)
