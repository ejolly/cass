"""NiceGUI-based database viewer — pure Python, AG Grid, no build step."""

from __future__ import annotations

__docformat__ = "google"

import json
import math
from datetime import date, datetime, time
from typing import Any, cast

import duckdb
from nicegui import ui

from ..db import db_path
from ..db import reset as db_reset
from . import _canvas_apply, _canvas_preview  # pyright: ignore[reportPrivateUsage]

# ---------------------------------------------------------------------------
# Constants
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
        LEFT JOIN canvas_assignments ca
            ON cs.canvas_assignment_id = ca.canvas_id
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
        LEFT JOIN canvas_assignments ca
            ON cg.canvas_assignment_id = ca.canvas_id
    """,
}

# Column display config: hide internal IDs, reorder for readability
_HIDDEN_COLUMNS: dict[str, list[str]] = {
    "canvas_assignments": ["canvas_id"],
    "canvas_students": ["canvas_id"],
    "canvas_submissions": ["canvas_user_id", "canvas_assignment_id"],
    "canvas_grades": ["canvas_user_id", "canvas_assignment_id"],
}

_COLUMN_ORDERING: dict[str, list[str]] = {
    "canvas_assignments": [
        "assignment_group",
        "name",
        "points_possible",
        "due_at",
        "published",
    ],
    "canvas_submissions": [
        "student_name",
        "assignment_name",
        "assignment_group",
        "submitted",
        "submitted_at",
        "late",
        "score",
        "workflow_state",
    ],
    "canvas_grades": [
        "student_name",
        "assignment_name",
        "assignment_group",
        "score",
        "posted_grade",
        "updated_at",
    ],
}

# Type aliases for pending changes
_ChangeFields = dict[str, object]
_RowChanges = dict[str, _ChangeFields]
_TableChanges = dict[str, _RowChanges]
_PendingChanges = dict[str, _TableChanges]


# ---------------------------------------------------------------------------
# Sanitization
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
# DB introspection
# ---------------------------------------------------------------------------


def _get_tables(
    conn: duckdb.DuckDBPyConnection,
) -> list[dict[str, str]]:
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
    return cast(
        list[dict[str, Any]],
        [_sanitize(dict(zip(col_names, row, strict=True))) for row in rows],
    )


def _classify_table(name: str) -> str:
    """Classify a table into a sidebar group."""
    if name.startswith("canvas_"):
        return "canvas"
    if name.startswith("gh_"):
        return "github"
    return "combined"


def _group_tables(
    tables: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Group tables into sidebar sections."""
    combined = [t for t in tables if _classify_table(t["name"]) == "combined"]
    canvas = [t for t in tables if _classify_table(t["name"]) == "canvas"]
    github = [t for t in tables if _classify_table(t["name"]) == "github"]
    groups: list[dict[str, Any]] = []
    if combined:
        groups.append({"label": "Combined Data", "items": combined})
    if canvas:
        groups.append({"label": "Canvas LMS", "items": canvas})
    if github:
        groups.append({"label": "GitHub Classroom", "items": github})
    return groups


# ---------------------------------------------------------------------------
# Cell update + pending change tracking
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
        row_changes[column] = {
            "baseline": old_value,
            "current": new_value,
        }


def _pending_count(pending: _PendingChanges) -> int:
    """Total number of pending field changes."""
    return sum(len(cols) for rows in pending.values() for cols in rows.values())


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------


def _get_display_columns(table: str, all_cols: list[str]) -> list[str]:
    """Get visible columns in display order for a table."""
    hidden = _HIDDEN_COLUMNS.get(table, [])
    visible = [c for c in all_cols if c not in hidden]

    ordering = _COLUMN_ORDERING.get(table)
    if not ordering:
        return visible

    ordered = [c for c in ordering if c in visible]
    remaining = [c for c in visible if c not in ordering]
    return [*ordered, *remaining]


def _build_column_defs(
    conn: duckdb.DuckDBPyConnection, table: str
) -> list[dict[str, Any]]:
    """Build AG Grid column definitions for a table."""
    query = _ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)
    col_names = [desc[0] for desc in result.description]
    col_types = {str(desc[0]): str(desc[1]) for desc in result.description}

    display_cols = _get_display_columns(table, col_names)
    hidden_cols = _HIDDEN_COLUMNS.get(table, [])

    editable = _is_editable(conn, table)
    pk_cols = _get_primary_keys(conn, table) if editable else []
    pushable_cols = _CANVAS_PUSHABLE.get(table, set())

    defs: list[dict[str, Any]] = []
    for name in display_cols:
        dtype = col_types.get(name, "VARCHAR")
        col_def: dict[str, Any] = {
            "headerName": name,
            "field": name,
            "sortable": True,
            "filter": True,
            "resizable": True,
            "floatingFilter": True,
        }

        # Type-specific filters and editors
        if "INT" in dtype or "DOUBLE" in dtype or "FLOAT" in dtype:
            col_def["filter"] = "agNumberColumnFilter"
        elif "BOOL" in dtype:
            col_def["filter"] = "agTextColumnFilter"
            if editable and name not in pk_cols:
                col_def["cellEditor"] = "agCheckboxCellEditor"
        elif "TIMESTAMP" in dtype or "DATE" in dtype:
            col_def["filter"] = "agDateColumnFilter"
        else:
            col_def["filter"] = "agTextColumnFilter"

        # PK columns: bold, dimmed, not editable
        if name in pk_cols:
            col_def["headerName"] = f"{name} (PK)"
            col_def["cellStyle"] = {
                "fontWeight": "bold",
                "opacity": "0.6",
            }

        # Editability: only non-PK columns on editable tables
        if editable and name not in pk_cols:
            col_def["editable"] = True

        # Highlight pushable columns with subtle blue tint
        if name in pushable_cols:
            col_def["cellStyle"] = {"backgroundColor": "rgba(59, 130, 246, 0.08)"}

        defs.append(col_def)

    # Add hidden columns at the end (for data integrity)
    for name in hidden_cols:
        if name in col_names:
            defs.append({"field": name, "hide": True})

    return defs


def _row_id_js(pk_cols: list[str]) -> str:
    """Generate a JS expression for AG Grid getRowId."""
    if not pk_cols:
        return "String(params.data.__rowIndex || Math.random())"
    if len(pk_cols) == 1:
        return f"String(params.data['{pk_cols[0]}'])"
    parts = " + '::' + ".join(f"String(params.data['{col}'])" for col in pk_cols)
    return parts


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CUSTOM_CSS = """
/* Sidebar styling */
.sidebar {
    width: 14rem;
    min-width: 14rem;
    background: var(--q-dark-page, #1d1d1d);
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
}
.sidebar-header {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.sidebar-title {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    opacity: 0.6;
    text-transform: uppercase;
}
.sidebar-nav {
    flex: 1;
    overflow-y: auto;
    padding: 0.5rem 0;
}
.sidebar-group-label {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    opacity: 0.5;
    text-transform: uppercase;
    padding: 0.75rem 1rem 0.25rem 1rem;
}
.sidebar-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.35rem 1rem;
    font-size: 0.75rem;
    font-family: 'SF Mono', 'Fira Code', 'Consolas',
        ui-monospace, monospace;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    border: none;
    background: transparent;
    border-radius: 0;
    transition: background 0.15s;
}
.sidebar-item:hover {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.95);
}
.sidebar-item.active {
    background: rgba(59, 130, 246, 0.2);
    color: white;
    font-weight: 600;
}
/* Toolbar */
.toolbar {
    padding: 0.5rem 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    align-items: center;
    gap: 0.625rem;
    min-height: 2.75rem;
    background: var(--q-dark-page, #1d1d1d);
}
.toolbar-label {
    font-size: 0.875rem;
    font-weight: 600;
}
.toolbar-badge {
    font-size: 0.65rem;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-weight: 600;
}
.badge-editable {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
}
.badge-readonly {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.5);
}
.toolbar-meta {
    font-size: 0.75rem;
    opacity: 0.5;
}
.toolbar-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.search-input {
    font-size: 0.75rem;
    padding: 0.25rem 0.5rem;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 0.25rem;
    background: transparent;
    color: inherit;
    width: 12rem;
    outline: none;
}
.search-input:focus {
    border-color: rgba(59, 130, 246, 0.5);
}
.search-input::placeholder {
    opacity: 0.4;
}
/* Status message */
.status-msg {
    font-size: 0.75rem;
    font-weight: 600;
    transition: opacity 0.3s;
}
.status-success { color: #4ade80; }
.status-error { color: #f87171; }
/* Toolbar buttons */
.toolbar-btn {
    font-size: 0.7rem;
    padding: 0.2rem 0.55rem;
    border-radius: 0.25rem;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: transparent;
    color: rgba(255, 255, 255, 0.8);
    cursor: pointer;
    white-space: nowrap;
}
.toolbar-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: white;
}
.toolbar-btn-primary {
    background: rgba(59, 130, 246, 0.2);
    border-color: rgba(59, 130, 246, 0.4);
    color: #93c5fd;
}
.toolbar-btn-primary:hover {
    background: rgba(59, 130, 246, 0.35);
}
/* Sidebar collapse */
.sidebar-collapsed {
    display: none !important;
}
.expand-btn {
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 100;
    background: var(--q-dark-page, #1d1d1d);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-left: none;
    border-radius: 0 0.25rem 0.25rem 0;
    color: rgba(255, 255, 255, 0.6);
    cursor: pointer;
    padding: 0.5rem 0.25rem;
    font-size: 0.75rem;
}
.expand-btn:hover {
    color: white;
    background: rgba(255, 255, 255, 0.08);
}
.collapse-btn {
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    font-size: 0.85rem;
    padding: 0 0.25rem;
}
.collapse-btn:hover {
    color: rgba(255, 255, 255, 0.8);
}
/* Push modal tables */
.push-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
    margin: 0.5rem 0;
}
.push-table th {
    text-align: left;
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
    opacity: 0.6;
    font-weight: 600;
}
.push-table td {
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.push-table .conflict-row {
    background: rgba(234, 179, 8, 0.1);
}
.push-table .error-row {
    background: rgba(239, 68, 68, 0.1);
}
/* Main layout */
.app-layout {
    display: flex;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
}
.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.grid-container {
    flex: 1;
    overflow: hidden;
    padding: 0;
}
"""


# ---------------------------------------------------------------------------
# NiceGUI app
# ---------------------------------------------------------------------------


def start_nicegui_server(port: int = 0) -> None:
    """Start the NiceGUI viewer, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
    """
    db_reset()
    conn = duckdb.connect(db_path())
    tables = _get_tables(conn)
    groups = _group_tables(tables)
    pending: _PendingChanges = {}

    @ui.page("/")
    def index() -> None:  # pyright: ignore[reportUnusedFunction]
        ui.add_head_html(f"<style>{_CUSTOM_CSS}</style>")

        # State containers for this page — typed as Any to allow
        # NiceGUI element refs alongside None initial values.
        grid_container: dict[str, Any] = {"ref": None}
        current_table: dict[str, str] = {
            "name": tables[0]["name"] if tables else "",
        }
        sidebar_buttons: dict[str, ui.element] = {}
        pending_label: dict[str, Any] = {"ref": None}
        table_label: dict[str, Any] = {"ref": None}
        badge_el: dict[str, Any] = {"ref": None}
        meta_label: dict[str, Any] = {"ref": None}
        search_ref: dict[str, Any] = {"ref": None}
        status_ref: dict[str, Any] = {"ref": None}
        clear_btn_ref: dict[str, Any] = {"ref": None}
        push_btn_ref: dict[str, Any] = {"ref": None}
        export_btn_ref: dict[str, Any] = {"ref": None}
        sidebar_ref: dict[str, Any] = {"ref": None}
        expand_btn_ref: dict[str, Any] = {"ref": None}
        sidebar_state: dict[str, bool] = {"collapsed": False}

        def update_pending_display() -> None:
            """Update pending count label and toggle clear/push button visibility."""
            count = _pending_count(pending)
            el = pending_label["ref"]
            if el is not None:
                el.text = f"{count} pending" if count > 0 else ""
            cb = clear_btn_ref["ref"]
            if cb is not None:
                cb.set_visibility(count > 0)
            pb = push_btn_ref["ref"]
            if pb is not None:
                pb.set_visibility(count > 0)

        def load_table(table_name: str) -> None:
            """Load a table into the grid area."""
            old = current_table["name"]
            current_table["name"] = table_name

            # Update sidebar active states
            if old in sidebar_buttons:
                sidebar_buttons[old].classes(remove="active", add="")
            if table_name in sidebar_buttons:
                sidebar_buttons[table_name].classes(add="active")

            # Update toolbar
            editable = _is_editable(conn, table_name)
            tl = table_label["ref"]
            if tl is not None:
                tl.text = table_name

            be = badge_el["ref"]
            if be is not None:
                if editable:
                    be.text = "EDITABLE"
                    be.classes(
                        remove="badge-readonly",
                        add="badge-editable",
                    )
                else:
                    be.text = "READ-ONLY"
                    be.classes(
                        remove="badge-editable",
                        add="badge-readonly",
                    )

            # Build grid
            row_data = _get_table_rows(conn, table_name)
            col_defs = _build_column_defs(conn, table_name)
            pk_cols = _get_primary_keys(conn, table_name) if editable else []

            ml = meta_label["ref"]
            if ml is not None:
                n_visible = sum(1 for c in col_defs if not c.get("hide"))
                ml.text = f"{len(row_data)} rows \u00b7 {n_visible} columns"

            # Clear and rebuild grid container
            container = grid_container["ref"]
            if container is not None:
                container.clear()
                with container:
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
                        ":getRowId": (f"(params) => {_row_id_js(pk_cols)}"),
                    }
                    # Dim unpublished rows in canvas_assignments
                    if table_name == "canvas_assignments":
                        grid_options[":getRowStyle"] = (
                            "(params) => {"
                            "  if (params.data && params.data.published === false)"
                            "    return { opacity: '0.45' };"
                            "}"
                        )

                    grid = (
                        ui.aggrid(grid_options, theme="quartz")
                        .classes("w-full")
                        .style("height: calc(100vh - 3rem)")
                    )

                    if editable:
                        _attach_edit_handler(
                            grid,
                            conn,
                            table_name,
                            pk_cols,
                            pending,
                            update_pending_display,
                            status_ref,
                        )

            # Clear search
            sr = search_ref["ref"]
            if sr is not None:
                sr.value = ""

        def toggle_sidebar() -> None:
            """Toggle sidebar collapsed/expanded state."""
            collapsed = not sidebar_state["collapsed"]
            sidebar_state["collapsed"] = collapsed
            sb = sidebar_ref["ref"]
            eb = expand_btn_ref["ref"]
            if sb is not None:
                if collapsed:
                    sb.classes(add="sidebar-collapsed")
                else:
                    sb.classes(remove="sidebar-collapsed")
            if eb is not None:
                eb.set_visibility(collapsed)

        # --- Layout ---
        with ui.element("div").classes("app-layout"):
            # Expand button (visible only when sidebar is collapsed)
            expand_btn = (
                ui.element("button")
                .classes("expand-btn")
                .props('innerHTML="\u203a"')
                .on("click", lambda _: toggle_sidebar())
            )
            expand_btn.set_visibility(False)
            expand_btn_ref["ref"] = expand_btn

            # --- Sidebar ---
            sidebar_el = ui.element("div").classes("sidebar")
            sidebar_ref["ref"] = sidebar_el
            with sidebar_el:
                with ui.element("div").classes("sidebar-header"):
                    ui.element("span").classes("sidebar-title").props(
                        'innerHTML="CASS"'
                    )
                    ui.element("button").classes("collapse-btn").props(
                        'innerHTML="\u2039"'
                    ).on("click", lambda _: toggle_sidebar())

                with ui.element("div").classes("sidebar-nav"):
                    for group in groups:
                        ui.element("div").classes("sidebar-group-label").props(
                            f'innerHTML="{group["label"]}"'
                        )
                        for t in group["items"]:
                            tn = t["name"]
                            btn = (
                                ui.element("button")
                                .classes("sidebar-item")
                                .props(f'innerHTML="{tn}"')
                                .on(
                                    "click",
                                    lambda _e, n=tn: load_table(n),
                                )
                            )
                            sidebar_buttons[tn] = btn
                            if tn == current_table["name"]:
                                btn.classes(add="active")

            # --- Main content ---
            with ui.element("div").classes("main-content"):
                # Toolbar
                with ui.element("div").classes("toolbar"):
                    tl = ui.label("").classes("toolbar-label")
                    table_label["ref"] = tl
                    be = ui.label("").classes("toolbar-badge badge-readonly")
                    badge_el["ref"] = be
                    ml = ui.label("").classes("toolbar-meta")
                    meta_label["ref"] = ml

                    with ui.element("div").classes("toolbar-right"):
                        si = (
                            ui.input(
                                placeholder="Search rows...",
                            )
                            .classes("search-input")
                            .props("dense outlined")
                        )
                        search_ref["ref"] = si
                        si.on(
                            "update:model-value",
                            lambda e: _apply_search(
                                grid_container,
                                e.args,  # pyright: ignore[reportUnknownMemberType]
                            ),
                        )

                        # Export CSV button
                        eb = (
                            ui.element("button")
                            .classes("toolbar-btn")
                            .props('innerHTML="Export CSV"')
                            .on("click", lambda _: _export_csv(grid_container))
                        )
                        export_btn_ref["ref"] = eb

                        # Status message label
                        sl = ui.label("").classes("status-msg")
                        status_ref["ref"] = sl

                        pl = ui.label("").classes("toolbar-meta")
                        pending_label["ref"] = pl

                        # Clear pending button (hidden initially)
                        cb = (
                            ui.element("button")
                            .classes("toolbar-btn")
                            .props('innerHTML="Clear"')
                            .on(
                                "click",
                                lambda _: _clear_pending(
                                    pending,
                                    update_pending_display,
                                    status_ref,
                                ),
                            )
                        )
                        cb.set_visibility(False)
                        clear_btn_ref["ref"] = cb

                        # Push to Canvas button (hidden initially)
                        pb = (
                            ui.element("button")
                            .classes("toolbar-btn toolbar-btn-primary")
                            .props('innerHTML="Push to Canvas"')
                            .on(
                                "click",
                                lambda _: _open_push_modal(
                                    conn,
                                    pending,
                                    update_pending_display,
                                    status_ref,
                                    grid_container,
                                    current_table,
                                ),
                            )
                        )
                        pb.set_visibility(False)
                        push_btn_ref["ref"] = pb

                # Grid area
                gc = ui.element("div").classes("grid-container")
                grid_container["ref"] = gc

        # Keyboard shortcuts: Ctrl/Cmd+K → focus search
        ui.add_body_html("""
        <script>
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const input = document.querySelector('.search-input input');
                if (input) input.focus();
            }
        });
        </script>
        """)

        # Load initial table
        if tables:
            load_table(tables[0]["name"])

    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass viewer",
        port=port if port > 0 else None,
        dark=True,
        reload=False,
        show=True,
        favicon="📊",
    )


def _find_grid(grid_container: dict[str, Any]) -> ui.aggrid | None:
    """Find the AG Grid element inside a container."""
    container = grid_container.get("ref")
    if container is None:
        return None
    for child in container:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(child, ui.aggrid):
            return child
    return None


def _apply_search(grid_container: dict[str, Any], search_text: object) -> None:
    """Apply quick filter to the AG Grid in the container."""
    grid = _find_grid(grid_container)
    if grid is None:
        return
    text = str(search_text) if search_text else ""
    escaped = json.dumps(text)
    grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
        "setGridOption", "quickFilterText", text
    )
    grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
        "setQuickFilter", escaped
    )


def _set_status(
    status_ref: dict[str, Any],
    text: str,
    level: str = "success",
    delay_ms: int = 3000,
) -> None:
    """Set a status message that auto-clears after a delay.

    Args:
        status_ref: Dict with "ref" pointing to the status label element.
        text: Message text to display.
        level: Either "success" or "error".
        delay_ms: Milliseconds before the message auto-clears.
    """
    el = status_ref.get("ref")
    if el is None:
        return
    el.text = text
    el.classes(remove="status-success status-error", add=f"status-{level}")

    def _clear() -> None:
        if el.text == text:
            el.text = ""

    ui.timer(delay_ms / 1000, _clear, once=True)


def _build_preview_html(
    assignment_changes: list[dict[str, object]],
    grade_changes: list[dict[str, object]],
    has_conflicts: bool,
) -> str:
    """Build HTML for the push preview tables.

    Args:
        assignment_changes: Preview rows for canvas_assignments.
        grade_changes: Preview rows for canvas_grades.
        has_conflicts: Whether any row has a conflict with live Canvas.

    Returns:
        HTML string for the preview content.
    """
    from html import escape

    parts: list[str] = []

    if assignment_changes:
        parts.append(
            '<h4 style="font-weight:600;margin-bottom:0.25rem">Assignment changes</h4>'
        )
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
                parts.append(
                    f'<td colspan="4" style="color:#f87171">{name}: {err}</td>'
                )
            else:
                name = escape(str(ch.get("name", "")))
                col = escape(str(ch.get("column", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}</td>")
                parts.append(f"<td>{col}{warn}</td>")
                parts.append(f'<td style="opacity:0.5">{live}</td>')
                parts.append(f'<td style="font-weight:600">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if grade_changes:
        parts.append(
            '<h4 style="font-weight:600;margin-top:1rem;'
            'margin-bottom:0.25rem">Grade changes</h4>'
        )
        parts.append('<table class="push-table"><thead><tr>')
        for h in (
            "Student \u2014 Assignment",
            "On Canvas",
            "New grade",
        ):
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
                parts.append(
                    f'<td colspan="3" style="color:#f87171">{name}: {err}</td>'
                )
            else:
                name = escape(str(ch.get("name", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}{warn}</td>")
                parts.append(f'<td style="opacity:0.5">{live}</td>')
                parts.append(f'<td style="font-weight:600">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if has_conflicts:
        parts.append(
            '<div style="color:#eab308;font-size:0.8rem;'
            "margin-top:0.75rem;padding:0.5rem;"
            "background:rgba(234,179,8,0.1);"
            'border-radius:0.25rem">'
            "\u26a0 Some Canvas values differ from when you "
            "last pulled. Pushing will overwrite.</div>"
        )

    return "".join(parts)


def _export_csv(grid_container: dict[str, Any]) -> None:
    """Export current grid data as CSV via AG Grid's built-in export."""
    grid = _find_grid(grid_container)
    if grid is not None:
        grid.run_grid_method("exportDataAsCsv")  # pyright: ignore[reportUnknownMemberType]


def _clear_pending(
    pending: _PendingChanges,
    update_pending_display: Any,
    status_ref: dict[str, Any],
) -> None:
    """Clear all pending changes."""
    pending.clear()
    update_pending_display()
    _set_status(status_ref, "Cleared", "success", 3000)


def _open_push_modal(
    conn: duckdb.DuckDBPyConnection,
    pending: _PendingChanges,
    update_pending_display: Any,
    status_ref: dict[str, Any],
    grid_container: dict[str, Any],
    current_table: dict[str, str],
) -> None:
    """Open the Push to Canvas modal with preview/push workflow.

    Args:
        conn: DuckDB connection.
        pending: Pending changes dict.
        update_pending_display: Callback to refresh pending count display.
        status_ref: Status label ref for post-push messages.
        grid_container: Grid container ref for reloading data after push.
        current_table: Current table name ref.
    """
    with ui.dialog() as dialog, ui.card().style("min-width: 32rem; max-width: 40rem"):
        dialog.open()

        ui.label("Push to Canvas").style(
            "font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem"
        )
        content_area = ui.element("div")
        action_area = ui.element("div").style(
            "display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem"
        )

        state: dict[str, Any] = {"phase": "loading", "preview": None}

        def _render_loading() -> None:
            content_area.clear()
            with content_area:
                ui.label("Comparing with Canvas...").style(
                    "opacity: 0.5; text-align: center; padding: 1rem 0"
                )
            action_area.clear()
            with action_area:
                ui.button("Cancel", on_click=dialog.close).props("flat")

        def _render_preview(preview: dict[str, object]) -> None:
            changes = cast(
                list[dict[str, object]],
                preview.get("changes", []),
            )
            has_conflicts = cast(bool, preview.get("has_conflicts", False))
            content_area.clear()
            with content_area:
                if not changes:
                    ui.label("No pending changes").style(
                        "opacity: 0.5; text-align: center; padding: 1rem 0"
                    )
                    return

                a_ch = [c for c in changes if c.get("table") == "canvas_assignments"]
                g_ch = [c for c in changes if c.get("table") == "canvas_grades"]
                ui.html(_build_preview_html(a_ch, g_ch, has_conflicts))

            pushable = [c for c in changes if "error" not in c]
            action_area.clear()
            with action_area:
                ui.button("Cancel", on_click=dialog.close).props("flat")
                if pushable:
                    n = len(pushable)
                    ui.button(
                        f"Push {n} change{'s' if n != 1 else ''}",
                        on_click=lambda: _do_push(),
                    ).props("color=primary")

        def _render_pushing() -> None:
            content_area.clear()
            with content_area:
                ui.label("Pushing to Canvas...").style(
                    "opacity: 0.5; text-align: center; padding: 1rem 0"
                )
            action_area.clear()
            with action_area:
                ui.button("Pushing...", on_click=lambda: None).props(
                    "color=primary disabled"
                )

        def _render_results(results: list[dict[str, object]]) -> None:
            succeeded = [r for r in results if r.get("ok")]
            failed = [r for r in results if not r.get("ok")]
            content_area.clear()
            with content_area:
                ui.label(f"{len(succeeded)} pushed, {len(failed)} failed").style(
                    "font-weight: 600; margin-bottom: 0.5rem"
                )
                for r in results:
                    aid = r.get("canvas_id") or r.get("canvas_assignment_id") or "?"
                    if r.get("ok"):
                        ui.label(f"\u2713 Assignment {aid}").style("color: #4ade80")
                    else:
                        err = r.get("error", "Unknown")
                        ui.label(f"\u2717 Assignment {aid}: {err}").style(
                            "color: #f87171"
                        )
            action_area.clear()
            with action_area:
                ui.button("Close", on_click=dialog.close).props("flat")

        def _render_error(message: str) -> None:
            content_area.clear()
            with content_area:
                ui.label(message).style("color: #f87171")
            action_area.clear()
            with action_area:
                ui.button("Close", on_click=dialog.close).props("flat")

        def _fetch_preview() -> None:
            try:
                preview = _canvas_preview(conn, pending)
                state["phase"] = "preview"
                state["preview"] = preview
                _render_preview(preview)
            except Exception as exc:
                state["phase"] = "error"
                _render_error(str(exc))

        def _do_push() -> None:
            state["phase"] = "pushing"
            _render_pushing()
            ui.timer(0.1, _execute_push, once=True)

        def _execute_push() -> None:
            try:
                result = _canvas_apply(conn, pending)
                if result["ok"]:
                    dialog.close()
                    update_pending_display()
                    _set_status(status_ref, "Pushed to Canvas", "success", 6000)
                    # Reload current table to reflect changes
                    grid = _find_grid(grid_container)
                    if grid is not None:
                        new_rows = _get_table_rows(conn, current_table["name"])
                        grid.options["rowData"] = new_rows  # pyright: ignore[reportUnknownMemberType]
                        grid.update()
                else:
                    state["phase"] = "results"
                    _render_results(
                        cast(
                            list[dict[str, object]],
                            result.get("results", []),
                        )
                    )
                    update_pending_display()
            except Exception as exc:
                dialog.close()
                _set_status(status_ref, f"Push failed: {exc}", "error", 6000)

        # Start with loading, then defer the blocking preview call
        _render_loading()
        ui.timer(0.1, _fetch_preview, once=True)


def _attach_edit_handler(
    grid: ui.aggrid,
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    pk_cols: list[str],
    pending: _PendingChanges,
    update_pending_display: Any,
    status_ref: dict[str, Any],
) -> None:
    """Attach cellValueChanged handler to an AG Grid."""

    def on_cell_changed(e: Any) -> None:
        data = e.args
        col_field = data["colDef"]["field"]
        new_value = data["value"]
        row = data["data"]

        pk = {col: row[col] for col in pk_cols}
        result = _update_cell(conn, table_name, pk, col_field, new_value)

        if result["ok"]:
            _track_change(
                pending,
                table_name,
                pk,
                col_field,
                result["old_value"],
                new_value,
            )
            update_pending_display()
            _set_status(status_ref, f"Saved {col_field}", "success", 3000)
            # Flash the edited column
            grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
                "flashCells",
                {
                    "columns": [col_field],
                    "flashDuration": 300,
                    "fadeDuration": 200,
                },
            )
        else:
            _set_status(
                status_ref,
                f"Error: {result.get('error', 'unknown')}",
                "error",
                5000,
            )

    grid.on("cellValueChanged", on_cell_changed)
