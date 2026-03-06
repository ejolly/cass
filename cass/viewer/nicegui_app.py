"""NiceGUI-based database viewer — pure Python, AG Grid, no build step."""

from __future__ import annotations

__docformat__ = "google"

import json
import math
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

import duckdb
from nicegui import ui

from ..db import db_path
from ..db import reset as db_reset

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Reuse existing viewer constants and helpers
# ---------------------------------------------------------------------------

_EXCLUDED_TABLES = {"meta"}

_READ_ONLY_TABLES = {
    "canvas_submissions",
    "gh_submissions",
    "gh_grades",
}

_CANVAS_PUSHABLE: dict[str, set[str]] = {
    "canvas_assignments": {"name", "points_possible", "due_at", "published"},
    "canvas_grades": {"posted_grade"},
}

_ENRICHED_QUERIES: dict[str, str] = {
    "canvas_submissions": """
        SELECT
            cs.canvas_user_id,
            cs.canvas_assignment_id,
            st.name AS student_name,
            ca.name AS assignment_name,
            ca.assignment_group,
            cs.submitted,
            cs.submitted_at,
            cs.late,
            cs.lateness_seconds,
            cs.score,
            cs.workflow_state,
            cs.fetched_at
        FROM canvas_submissions cs
        LEFT JOIN canvas_students st ON cs.canvas_user_id = st.canvas_id
        LEFT JOIN canvas_assignments ca ON cs.canvas_assignment_id = ca.canvas_id
    """,
    "canvas_grades": """
        SELECT
            cg.canvas_user_id,
            cg.canvas_assignment_id,
            st.name AS student_name,
            ca.name AS assignment_name,
            ca.assignment_group,
            cg.score,
            cg.posted_grade,
            cg.updated_at
        FROM canvas_grades cg
        LEFT JOIN canvas_students st ON cg.canvas_user_id = st.canvas_id
        LEFT JOIN canvas_assignments ca ON cg.canvas_assignment_id = ca.canvas_id
    """,
}

# Type aliases for pending changes
_ChangeFields = dict[str, object]
_RowChanges = dict[str, _ChangeFields]
_TableChanges = dict[str, _RowChanges]
_PendingChanges = dict[str, _TableChanges]


# ---------------------------------------------------------------------------
# Sanitization for AG Grid (NaN/Inf → None, datetime → isoformat)
# ---------------------------------------------------------------------------


def _sanitize(obj: object) -> object:  # pyright: ignore[reportUnknownParameterType]
    """Replace float NaN/Inf with None and convert datetimes for JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return obj


# ---------------------------------------------------------------------------
# DB introspection (same as viewer/__init__.py)
# ---------------------------------------------------------------------------


def _get_tables(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    """Return list of tables with their type."""
    rows = conn.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_type, table_name"
    ).fetchall()
    return [
        {"name": name, "type": "view" if "VIEW" in ttype else "table"}
        for name, ttype in rows
        if name not in _EXCLUDED_TABLES
    ]


def _get_primary_keys(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return primary key column names for a table."""
    try:
        pk_rows = conn.execute(
            "SELECT constraint_column_names FROM duckdb_constraints() "
            "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
            [table],
        ).fetchall()
        if pk_rows:
            return list(pk_rows[0][0])
    except duckdb.Error:
        pass
    return []


def _get_column_names(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return column names for a table."""
    cols_raw = conn.execute(f"DESCRIBE {table}").fetchall()
    return [row[0] for row in cols_raw]


def _is_editable(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    """Check if a table is editable."""
    tables = _get_tables(conn)
    table_type = next((t["type"] for t in tables if t["name"] == table), None)
    pk_cols = _get_primary_keys(conn, table)
    return table_type == "table" and len(pk_cols) > 0 and table not in _READ_ONLY_TABLES


def _get_table_rows(
    conn: duckdb.DuckDBPyConnection, table: str
) -> list[dict[str, Any]]:
    """Return all rows from a table as list of dicts."""
    query = _ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)
    col_names = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [
        _sanitize(dict(zip(col_names, row, strict=True)))  # pyright: ignore[reportReturnType]
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Cell update + pending change tracking (reused from viewer/__init__.py)
# ---------------------------------------------------------------------------


def _values_equal(a: object, b: object) -> bool:
    """Compare values loosely, handling datetime/string equivalence."""
    if a == b:
        return True
    if isinstance(a, (datetime, date)) and isinstance(b, str):
        return a.isoformat() == b or str(a) == b
    if isinstance(b, (datetime, date)) and isinstance(a, str):
        return b.isoformat() == a or str(b) == a
    return False


def _update_cell(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    pk: dict[str, object],
    column: str,
    value: object,
) -> dict[str, object]:
    """Update a single cell in a table."""
    pk_cols = _get_primary_keys(conn, table)
    if not pk_cols:
        return {"ok": False, "error": "Table is not editable"}

    valid_cols = _get_column_names(conn, table)
    if column not in valid_cols:
        return {"ok": False, "error": f"Unknown column: {column}"}

    if set(pk.keys()) != set(pk_cols):
        return {"ok": False, "error": f"Expected PK columns: {pk_cols}"}

    where_parts = [f"{col} = ?" for col in pk_cols]
    where_clause = " AND ".join(where_parts)
    pk_values = [pk[col] for col in pk_cols]

    old_row = conn.execute(
        f"SELECT {column} FROM {table} WHERE {where_clause}",
        pk_values,
    ).fetchone()
    old_value = old_row[0] if old_row else None

    sql = f"UPDATE {table} SET {column} = ? WHERE {where_clause}"
    conn.execute(sql, [value, *pk_values])

    return {"ok": True, "old_value": old_value}


def _track_change(
    pending: _PendingChanges,
    table: str,
    pk: dict[str, object],
    column: str,
    old_value: object,
    new_value: object,
) -> None:
    """Record a cell edit as a pending Canvas change."""
    pushable = _CANVAS_PUSHABLE.get(table)
    if not pushable or column not in pushable:
        return

    pk_key = (
        str(next(iter(pk.values()))) if len(pk) == 1 else json.dumps(pk, sort_keys=True)
    )

    table_changes = pending.setdefault(table, {})
    row_changes = table_changes.setdefault(pk_key, {})

    if column in row_changes:
        row_changes[column]["current"] = new_value
        if _values_equal(row_changes[column]["baseline"], new_value):
            del row_changes[column]
            if not row_changes:
                del table_changes[pk_key]
            if not table_changes:
                del pending[table]
    else:
        row_changes[column] = {"baseline": old_value, "current": new_value}


def _pending_count(pending: _PendingChanges) -> int:
    """Total number of pending field changes."""
    return sum(len(cols) for rows in pending.values() for cols in rows.values())


# ---------------------------------------------------------------------------
# NiceGUI app
# ---------------------------------------------------------------------------


def _build_column_defs(
    conn: duckdb.DuckDBPyConnection, table: str
) -> list[dict[str, Any]]:
    """Build AG Grid column definitions for a table."""
    query = _ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)
    col_names = [desc[0] for desc in result.description]
    col_types = [str(desc[1]) for desc in result.description]

    editable = _is_editable(conn, table)
    pk_cols = _get_primary_keys(conn, table) if editable else []
    pushable_cols = _CANVAS_PUSHABLE.get(table, set())

    defs: list[dict[str, Any]] = []
    for name, dtype in zip(col_names, col_types, strict=True):
        col_def: dict[str, Any] = {
            "headerName": name,
            "field": name,
            "sortable": True,
            "filter": True,
            "resizable": True,
            "floatingFilter": True,
        }

        # Type-specific filters
        if "INT" in dtype or "DOUBLE" in dtype or "FLOAT" in dtype:
            col_def["filter"] = "agNumberColumnFilter"
        elif "BOOL" in dtype:
            col_def["filter"] = "agTextColumnFilter"
        elif "TIMESTAMP" in dtype or "DATE" in dtype:
            col_def["filter"] = "agDateColumnFilter"
        else:
            col_def["filter"] = "agTextColumnFilter"

        # Editability: only non-PK columns on editable tables
        if editable and name not in pk_cols:
            col_def["editable"] = True

        # Highlight pushable columns
        if name in pushable_cols:
            col_def["cellStyle"] = {"backgroundColor": "rgba(59, 130, 246, 0.08)"}

        defs.append(col_def)

    return defs


def start_nicegui_server(port: int = 0) -> None:
    """Start the NiceGUI viewer, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
    """
    db_reset()
    conn = duckdb.connect(db_path())
    tables = _get_tables(conn)
    pending: _PendingChanges = {}

    # Store grids by table name for refreshing
    grids: dict[str, ui.aggrid] = {}

    @ui.page("/")
    def index() -> None:  # pyright: ignore[reportUnusedFunction]
        # --- Header ---
        with ui.header().classes("items-center justify-between bg-base-300"):
            ui.label("cass viewer").classes("text-xl font-bold")
            pending_badge = ui.badge("0 pending").props("outline")
            pending_badge.classes("text-sm")

        def update_badge() -> None:
            count = _pending_count(pending)
            pending_badge.text = f"{count} pending"
            if count > 0:
                pending_badge.props("color=warning")
            else:
                pending_badge.props(remove="color=warning").props("outline")

        # --- Table tabs ---
        with ui.tabs().classes("w-full") as tabs:
            for t in tables:
                label = t["name"]
                if t["name"] in _READ_ONLY_TABLES:
                    label += " (read-only)"
                ui.tab(t["name"], label=label)

        with ui.tab_panels(tabs, value=tables[0]["name"] if tables else None).classes(
            "w-full flex-grow"
        ):
            for t in tables:
                table_name = t["name"]
                with ui.tab_panel(table_name).classes("p-2"):
                    row_data = _get_table_rows(conn, table_name)
                    col_defs = _build_column_defs(conn, table_name)
                    editable = _is_editable(conn, table_name)
                    pk_cols = _get_primary_keys(conn, table_name) if editable else []

                    # Info bar
                    with ui.row().classes("items-center gap-4 mb-2"):
                        ui.label(f"{len(row_data)} rows").classes("text-sm opacity-70")
                        if editable:
                            pushable = _CANVAS_PUSHABLE.get(table_name, set())
                            if pushable:
                                ui.badge("Canvas-pushable", color="blue").props(
                                    "outline"
                                )
                            else:
                                ui.badge("editable", color="green").props("outline")
                        else:
                            ui.badge("read-only", color="grey").props("outline")

                    # AG Grid
                    grid = (
                        ui.aggrid(
                            {
                                "columnDefs": col_defs,
                                "rowData": row_data,
                                "defaultColDef": {
                                    "sortable": True,
                                    "resizable": True,
                                    "minWidth": 80,
                                },
                                "animateRows": True,
                                "rowSelection": {"mode": "multiRow"},
                                "enableCellTextSelection": True,
                                ":getRowId": f"(params) => {_row_id_js(pk_cols)}",
                            },
                            theme="quartz",
                        )
                        .classes("w-full")
                        .style("height: calc(100vh - 160px)")
                    )

                    grids[table_name] = grid

                    if editable:
                        # Capture table_name and pk_cols in closure
                        _tn = table_name
                        _pkc = pk_cols

                        def make_handler(tn: str, pkc: list[str]) -> Any:
                            def on_cell_changed(e: Any) -> None:
                                data = e.args
                                col_field = data["colDef"]["field"]
                                new_value = data["value"]
                                row = data["data"]

                                pk = {col: row[col] for col in pkc}
                                result = _update_cell(
                                    conn, tn, pk, col_field, new_value
                                )

                                if result["ok"]:
                                    _track_change(
                                        pending,
                                        tn,
                                        pk,
                                        col_field,
                                        result["old_value"],
                                        new_value,
                                    )
                                    update_badge()
                                    ui.notify(
                                        f"Updated {col_field}",
                                        type="positive",
                                        position="bottom-right",
                                        close_button=True,
                                    )
                                else:
                                    ui.notify(
                                        f"Error: {result.get('error', 'unknown')}",
                                        type="negative",
                                    )

                            return on_cell_changed

                        grid.on("cellValueChanged", make_handler(_tn, _pkc))

    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass viewer",
        port=port if port > 0 else None,
        dark=None,  # auto dark mode
        reload=False,
        show=True,
        favicon="📊",
    )


def _row_id_js(pk_cols: list[str]) -> str:
    """Generate a JS expression for AG Grid getRowId based on PK columns."""
    if not pk_cols:
        return "String(params.data.__rowIndex || Math.random())"
    if len(pk_cols) == 1:
        return f"String(params.data['{pk_cols[0]}'])"
    parts = " + '::' + ".join(f"String(params.data['{col}'])" for col in pk_cols)
    return parts
