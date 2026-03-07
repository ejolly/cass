"""Grid panel component for the viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, Any

from nicegui import ui

from ..grid import (
    attach_date_autocommit,
    attach_edit_handler,
    attach_gradebook_edit_handler,
    build_column_defs,
    build_gh_gradebook_view,
    build_gradebook_view,
    get_primary_keys,
    get_table_rows,
    is_editable,
    restore_pending_cells,
    row_id_js,
)

if TYPE_CHECKING:
    import duckdb

    from ..config import PendingChanges
    from ..page import ViewerPage


class GridPanel:
    """AG Grid container — builds and swaps grids on table load."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._build()

    def _build(self) -> None:
        self.page.grid_container = ui.element("div").classes("v-grid-container")

    @staticmethod
    def build_grid(
        container: ui.element,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        pending: PendingChanges,
        update_pending_display: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build an AG Grid inside *container* for the given table."""
        editable_flag = is_editable(conn, table_name)
        is_canvas_gb = table_name == "canvas_grades"
        is_gh_gb = table_name == "gh_gradebook"

        if is_canvas_gb:
            row_data, col_defs = build_gradebook_view(conn)
            pk_cols: list[str] = []
        elif is_gh_gb:
            row_data, col_defs = build_gh_gradebook_view(conn)
            pk_cols = []
        else:
            row_data = get_table_rows(conn, table_name)
            col_defs = build_column_defs(conn, table_name)
            pk_cols = get_primary_keys(conn, table_name) if editable_flag else []

        grid_options: dict[str, Any] = {
            "columnDefs": col_defs,
            "rowData": row_data,
            "defaultColDef": {
                "sortable": True,
                "resizable": True,
                "minWidth": 80,
            },
            "animateRows": True,
            "enableCellTextSelection": True,
            "stopEditingWhenCellsLoseFocus": True,
        }

        if is_canvas_gb:
            grid_options[":getRowId"] = (
                "(params) => String(params.data._canvas_user_id)"
            )
        elif is_gh_gb:
            grid_options[":getRowId"] = (
                "(params) => String(params.data._github_username)"
            )
        else:
            grid_options[":getRowId"] = f"(params) => {row_id_js(pk_cols)}"

        grid = (
            ui.aggrid(grid_options, theme="quartz")
            .classes("v-grid")
            .style("height: calc(100vh - 6rem)")
        )

        if is_canvas_gb:
            attach_gradebook_edit_handler(grid, conn, pending, update_pending_display)
        elif editable_flag:
            attach_edit_handler(
                grid,
                conn,
                table_name,
                pk_cols,
                pending,
                update_pending_display,
            )

        if is_canvas_gb or editable_flag:
            attach_date_autocommit(grid)

        if is_canvas_gb:
            restore_pending_cells(grid, pending, "canvas_grades", [], is_gradebook=True)
        elif editable_flag:
            restore_pending_cells(grid, pending, table_name, pk_cols)

        return row_data, col_defs
