"""Generic database viewer page — renders any SQLite/DuckDB file."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path
from typing import Any

from ibis import BaseBackend
from nicegui import ui

from ..db.ibis_adapter import (
    get_categorical_columns,
    get_primary_keys,
    get_row_count,
    get_rows,
    get_schema,
    list_tables,
    run_sql,
)
from .generic_grid import attach_generic_edit_handler, build_generic_column_defs
from .styles import NAV_ITEM, NAV_ITEM_ACTIVE, load_styles

_SIDEBAR_PCT = 25


class GenericViewerPage:
    """Self-contained viewer page for arbitrary SQLite/DuckDB files."""

    def __init__(self, con: BaseBackend, filepath: Path) -> None:
        self.con = con
        self.filepath = filepath
        self.tables = list_tables(con)
        self.current_table = ""
        self.grid: ui.aggrid | None = None
        self.grid_container: ui.element | None = None
        self.table_label: ui.label | None = None
        self.meta_label: ui.label | None = None
        self.search_input: ui.input | None = None
        self.sidebar_items: dict[str, ui.element] = {}
        self._build()

    def _build(self) -> None:
        """Emit the full page layout."""
        load_styles()

        splitter = ui.splitter(value=_SIDEBAR_PCT, limits=(0, 50)).classes(
            "w-full h-screen"
        )

        def _toggle_sidebar() -> None:
            splitter.value = (  # pyright: ignore[reportAttributeAccessIssue]
                0 if splitter.value > 0 else _SIDEBAR_PCT
            )

        with splitter.before:
            self._build_sidebar()

        with splitter.after, ui.column().classes("v-main-col"):
            self._build_toolbar(toggle_sidebar=_toggle_sidebar)
            self.grid_container = ui.element("div").classes("v-grid-container")

        if self.tables:
            self.load_table(self.tables[0]["name"])

    def _build_sidebar(self) -> None:
        """Render sidebar with file header and table list."""
        with ui.column().classes("v-sidebar"):
            with ui.column().classes("v-sidebar-header"):
                ui.label(self.filepath.name).classes(
                    "text-sm font-semibold text-white/80"
                )
                backend = self.con.name
                ui.label(f"{backend} \u00b7 {len(self.tables)} tables").classes(
                    "text-xs text-white/40"
                )

            with ui.column().classes("w-full flex-1 overflow-y-auto p-0 gap-0"):
                for table in self.tables:
                    name = table["name"]
                    count = get_row_count(self.con, name)
                    item = ui.element("div").classes(NAV_ITEM)
                    with (
                        item,
                        ui.row().classes(
                            "w-full items-center justify-between px-3 py-1"
                        ),
                    ):
                        ui.label(name).classes("text-sm truncate")
                        ui.badge(str(count)).props("color=grey-8 text-color=grey-4")
                    item.on(
                        "click",
                        lambda _, n=name: self.load_table(n),
                    )
                    self.sidebar_items[name] = item

    def _build_toolbar(self, *, toggle_sidebar: Any) -> None:
        """Render toolbar with table name, metadata, search, export."""
        with ui.row().classes("v-toolbar-row"):
            ui.button(icon="menu", on_click=toggle_sidebar).props(
                "flat dense round size=sm"
            )
            self.table_label = ui.label("").classes("text-base font-semibold")
            self.meta_label = ui.label("").classes("text-xs text-white/50")
            ui.element("div").classes("flex-1")
            self.search_input = (
                ui.input(placeholder="Search...")
                .props("dense outlined clearable")
                .classes("w-48")
            )
            self.search_input.on(
                "update:model-value",
                lambda e: self._on_search(e.args),
            )
            ui.button(
                "Export CSV",
                icon="download",
                on_click=self._export_csv,
            ).props("flat dense size=sm")

    def load_table(self, table_name: str) -> None:
        """Load a table into the grid area."""
        old = self.current_table
        self.current_table = table_name

        # Update sidebar active state
        if old in self.sidebar_items:
            self.sidebar_items[old].classes(remove=NAV_ITEM_ACTIVE)
        if table_name in self.sidebar_items:
            self.sidebar_items[table_name].classes(add=NAV_ITEM_ACTIVE)

        # Update toolbar
        if self.table_label is not None:
            self.table_label.text = table_name

        # Fetch data
        schema = get_schema(self.con, table_name)
        pk_cols = get_primary_keys(self.con, table_name)
        use_rowid = len(pk_cols) == 0
        rows = get_rows(self.con, table_name)
        categoricals = get_categorical_columns(self.con, table_name)
        col_defs = build_generic_column_defs(
            schema, pk_cols, use_rowid=use_rowid, categoricals=categoricals
        )

        # Row ID expression for AG Grid
        if pk_cols:
            if len(pk_cols) == 1:
                row_id_js = f"String(params.data['{pk_cols[0]}'])"
            else:
                row_id_js = " + '::' + ".join(
                    f"String(params.data['{c}'])" for c in pk_cols
                )
        else:
            row_id_js = "String(params.data.rowid || Math.random())"

        # Clear and rebuild grid
        if self.grid_container is not None:
            self.grid_container.clear()
            with self.grid_container:
                self.grid = (
                    ui.aggrid(
                        {
                            "columnDefs": col_defs,
                            "rowData": rows,
                            "defaultColDef": {
                                "sortable": True,
                                "resizable": True,
                                "minWidth": 80,
                                "flex": 1,
                            },
                            "animateRows": True,
                            "enableCellTextSelection": True,
                            ":getRowId": f"(params) => {row_id_js}",
                        },
                        html_columns=[],
                        theme="quartz",
                    )
                    .classes("v-grid")
                    .style("height: calc(100vh - 6rem)")
                )

                attach_generic_edit_handler(
                    self.grid,
                    self.con,
                    table_name,
                    pk_cols,
                    use_rowid=use_rowid,
                )

            # AG Grid adds ag-delay-render to hide rows until initial
            # render completes, but inside a splitter the grid never
            # receives the resize event that clears it.  Force-remove
            # the class after a short delay so rows become visible.
            ui.timer(
                0.1,
                lambda: ui.run_javascript(
                    "document.querySelectorAll('.ag-delay-render')"
                    ".forEach(el => el.classList.remove('ag-delay-render'))"
                ),
                once=True,
            )

        # Update metadata
        if self.meta_label is not None:
            n_cols = sum(1 for c in col_defs if not c.get("hide"))
            self.meta_label.text = f"{len(rows)} rows \u00b7 {n_cols} columns"

        # Clear search
        if self.search_input is not None:
            self.search_input.value = ""

    def _on_search(self, value: Any) -> None:
        """Apply quick filter to the grid."""
        if self.grid is not None:
            text = value if isinstance(value, str) else ""
            self.grid.run_grid_method("setGridOption", "quickFilterText", text)

    def _export_csv(self) -> None:
        """Export current grid data as CSV."""
        if self.grid is not None:
            self.grid.run_grid_method("exportDataAsCsv")

    def run_sql_query(self, sql: str) -> None:
        """Execute SQL and replace grid with results."""
        try:
            columns, rows = run_sql(self.con, sql)
        except Exception as exc:
            ui.notify(str(exc), type="negative", position="bottom")
            return

        col_defs = [
            {
                "headerName": c,
                "field": c,
                "sortable": True,
                "filter": False,
                "resizable": True,
            }
            for c in columns
        ]

        if self.grid_container is not None:
            self.grid_container.clear()
            with self.grid_container:
                self.grid = (
                    ui.aggrid(
                        {
                            "columnDefs": col_defs,
                            "rowData": rows,
                            "defaultColDef": {
                                "flex": 1,
                                "minWidth": 80,
                            },
                        },
                        theme="quartz",
                    )
                    .classes("v-grid")
                    .style("height: calc(100vh - 6rem)")
                )

        if self.meta_label is not None:
            self.meta_label.text = f"{len(rows)} rows \u00b7 {len(columns)} columns"
        if self.table_label is not None:
            self.table_label.text = "SQL Result"
