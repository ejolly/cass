"""Grid helpers — DB introspection, column defs, gradebook pivot, edit handlers."""

from __future__ import annotations

__docformat__ = "google"

import json
import math
from datetime import date, datetime, time
from typing import Any, Literal, cast

import duckdb
from nicegui import ui

from . import values_equal
from .config import (
    CANVAS_PUSHABLE,
    COLUMN_DISPLAY_NAMES,
    COLUMN_ORDERING,
    ENRICHED_QUERIES,
    EXCLUDED_TABLES,
    HIDDEN_COLUMNS,
    READ_ONLY_TABLES,
    PendingChanges,
    display_name,
)

# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def sanitize(obj: object) -> object:  # pyright: ignore[reportUnknownParameterType]
    """Replace float NaN/Inf with None and convert datetimes for JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return obj


# ---------------------------------------------------------------------------
# Datetime formatting
# ---------------------------------------------------------------------------

_DATETIME_JS = """
(params) => {
    if (!params.value) return '';
    const d = new Date(params.value);
    if (isNaN(d)) return params.value;
    return d.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit'
    });
}
""".strip()

_DATE_JS = """
(params) => {
    if (!params.value) return '';
    const d = new Date(params.value);
    if (isNaN(d)) return params.value;
    return d.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
    });
}
""".strip()

_SUBMISSION_DATE_JS = """
(params) => {
    if (!params.value) return '';
    const d = new Date(params.value);
    if (isNaN(d)) return params.value;
    const due = params.data && params.data.due_at ? new Date(params.data.due_at) : null;
    const text = d.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit'
    });
    if (due && d > due) return '<span style="color:#f87171">' + text + '</span>';
    return text;
}
""".strip()


# ---------------------------------------------------------------------------
# DB introspection
# ---------------------------------------------------------------------------


def get_tables(
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
        if name not in EXCLUDED_TABLES
    ]


def get_primary_keys(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
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


def get_column_names(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return column names for a table."""
    cols_raw = conn.execute(f"DESCRIBE {table}").fetchall()
    return [row[0] for row in cols_raw]


def is_editable(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    """Check if a table is editable."""
    tables = get_tables(conn)
    table_type = next((t["type"] for t in tables if t["name"] == table), None)
    pk_cols = get_primary_keys(conn, table)
    return table_type == "table" and len(pk_cols) > 0 and table not in READ_ONLY_TABLES


def get_table_rows(conn: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, Any]]:
    """Return all rows from a table as list of dicts."""
    query = ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)
    col_names = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return cast(
        list[dict[str, Any]],
        [sanitize(dict(zip(col_names, row, strict=True))) for row in rows],
    )


# ---------------------------------------------------------------------------
# Cell update + pending change tracking
# ---------------------------------------------------------------------------


def update_cell(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    pk: dict[str, object],
    column: str,
    value: object,
) -> dict[str, object]:
    """Update a single cell in a table."""
    pk_cols = get_primary_keys(conn, table)
    if not pk_cols:
        return {"ok": False, "error": "Table is not editable"}

    valid_cols = get_column_names(conn, table)
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


def track_change(
    pending: PendingChanges,
    table: str,
    pk: dict[str, object],
    column: str,
    old_value: object,
    new_value: object,
) -> None:
    """Record a cell edit as a pending Canvas change."""
    pushable = CANVAS_PUSHABLE.get(table)
    if not pushable or column not in pushable:
        return

    pk_key = (
        str(next(iter(pk.values()))) if len(pk) == 1 else json.dumps(pk, sort_keys=True)
    )

    table_changes = pending.setdefault(table, {})
    row_changes = table_changes.setdefault(pk_key, {})

    if column in row_changes:
        row_changes[column]["current"] = new_value
        if values_equal(row_changes[column]["baseline"], new_value):
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


def pending_count(pending: PendingChanges) -> int:
    """Total number of pending field changes."""
    return sum(len(cols) for rows in pending.values() for cols in rows.values())


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------


def _is_datetime_col(dtype: str) -> bool:
    """Check if a column type is a datetime/timestamp."""
    return "TIMESTAMP" in dtype or "DATE" in dtype


def get_display_columns(table: str, all_cols: list[str]) -> list[str]:
    """Get visible columns in display order for a table."""
    hidden = HIDDEN_COLUMNS.get(table, [])
    visible = [c for c in all_cols if c not in hidden]

    ordering = COLUMN_ORDERING.get(table)
    if not ordering:
        return visible

    ordered = [c for c in ordering if c in visible]
    remaining = [c for c in visible if c not in ordering]
    return [*ordered, *remaining]


def build_column_defs(
    conn: duckdb.DuckDBPyConnection, table: str
) -> list[dict[str, Any]]:
    """Build AG Grid column definitions for a table."""
    query = ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)
    col_names = [desc[0] for desc in result.description]
    col_types = {str(desc[0]): str(desc[1]) for desc in result.description}

    display_cols = get_display_columns(table, col_names)
    hidden_cols = HIDDEN_COLUMNS.get(table, [])
    col_display_names = COLUMN_DISPLAY_NAMES.get(table, {})

    editable = is_editable(conn, table)
    pk_cols = get_primary_keys(conn, table) if editable else []
    pushable_cols = CANVAS_PUSHABLE.get(table, set())

    defs: list[dict[str, Any]] = []
    for name in display_cols:
        dtype = col_types.get(name, "VARCHAR")
        header = col_display_names.get(name, name)
        col_def: dict[str, Any] = {
            "headerName": header,
            "field": name,
            "sortable": True,
            "filter": False,
            "resizable": True,
        }

        # Datetime formatting
        if _is_datetime_col(dtype):
            if table == "canvas_submissions" and name == "submitted_at":
                col_def[":cellRenderer"] = _SUBMISSION_DATE_JS
            else:
                col_def[":valueFormatter"] = _DATETIME_JS
            # Date string editor for editable datetime columns
            if editable and name not in pk_cols:
                col_def["cellEditor"] = "agDateStringCellEditor"

        # Type-specific editors for editable columns
        if editable and name not in pk_cols:
            if "BOOL" in dtype:
                col_def["cellEditor"] = "agCheckboxCellEditor"
            elif "INT" in dtype or "DOUBLE" in dtype or "FLOAT" in dtype:
                col_def["cellEditor"] = "agNumberCellEditor"

        # PK columns: bold, dimmed, not editable
        if name in pk_cols:
            col_def["headerName"] = f"{header} (PK)"
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


def row_id_js(pk_cols: list[str]) -> str:
    """Generate a JS expression for AG Grid getRowId."""
    if not pk_cols:
        return "String(params.data.__rowIndex || Math.random())"
    if len(pk_cols) == 1:
        return f"String(params.data['{pk_cols[0]}'])"
    parts = " + '::' + ".join(f"String(params.data['{col}'])" for col in pk_cols)
    return parts


# ---------------------------------------------------------------------------
# Gradebook pivot view
# ---------------------------------------------------------------------------


def build_gradebook_view(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build pivoted gradebook data: students as rows, assignments as columns.

    Returns:
        (row_data, col_defs) — ready for AG Grid.
    """
    # Fetch assignments ordered by assignment_group then name
    assignments = conn.execute(
        "SELECT canvas_id, name, points_possible, published, assignment_group "
        "FROM canvas_assignments ORDER BY assignment_group, name"
    ).fetchall()

    # Fetch students ordered by sortable_name
    students = conn.execute(
        "SELECT canvas_id, name, sortable_name FROM canvas_students "
        "ORDER BY sortable_name"
    ).fetchall()

    # Fetch all grades into a lookup: (user_id, assignment_id) -> posted_grade
    grades_raw = conn.execute(
        "SELECT canvas_user_id, canvas_assignment_id, posted_grade FROM canvas_grades"
    ).fetchall()
    grade_map: dict[tuple[int, int], str] = {
        (int(r[0]), int(r[1])): r[2] for r in grades_raw
    }

    # Build column defs
    col_defs: list[dict[str, Any]] = [
        {
            "headerName": "Student",
            "field": "_student_name",
            "pinned": "left",
            "minWidth": 160,
            "sortable": True,
            "filter": False,
            "resizable": True,
            "editable": False,
            "cellStyle": {"fontWeight": "600"},
        },
    ]

    # Group assignments by assignment_group for column groups
    groups: dict[str, list[dict[str, Any]]] = {}
    for a_id, a_name, pts, published, group in assignments:
        field = f"_a{a_id}"
        subtitle = "Unpublished" if not published else f"Out of {pts:g}"
        child: dict[str, Any] = {
            "headerName": a_name,
            "field": field,
            "minWidth": 90,
            "sortable": True,
            "filter": False,
            "resizable": True,
            "editable": True,
            "headerTooltip": f"{a_name} — {subtitle}",
            "wrapHeaderText": True,
            "autoHeaderHeight": True,
        }
        if not published:
            child["cellStyle"] = {"opacity": "0.45"}
        else:
            child["cellStyle"] = {"backgroundColor": "rgba(59, 130, 246, 0.08)"}
        groups.setdefault(group or "Ungrouped", []).append(child)

    for group_name, children in groups.items():
        if len(groups) > 1:
            col_defs.append(
                {
                    "headerName": group_name,
                    "children": children,
                }
            )
        else:
            col_defs.extend(children)

    # Hidden ID column for row identification
    col_defs.append({"field": "_canvas_user_id", "hide": True})

    # Build row data: one row per student
    row_data: list[dict[str, Any]] = []
    for s_id, s_name, _sortable in students:
        row: dict[str, Any] = {
            "_student_name": s_name,
            "_canvas_user_id": int(s_id),
        }
        for a_id, *_rest in assignments:
            row[f"_a{a_id}"] = grade_map.get((int(s_id), int(a_id)), "")
        row_data.append(row)

    return row_data, col_defs


# ---------------------------------------------------------------------------
# Edit handlers
# ---------------------------------------------------------------------------


def attach_edit_handler(
    grid: ui.aggrid,
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    pk_cols: list[str],
    pending: PendingChanges,
    update_pending_display: Any,
) -> None:
    """Attach cellValueChanged handler to an AG Grid."""

    def on_cell_changed(e: Any) -> None:
        data = e.args
        col_def = data.get("colDef")
        if col_def:
            col_field = col_def["field"]
        else:
            col_field = data.get("colId", data.get("column"))
        if col_field is None:
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
            grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
                "flashCells",
                {
                    "columns": [col_field],
                    "flashDuration": 300,
                    "fadeDuration": 200,
                },
            )
        else:
            notify(
                f"Error: {result.get('error', 'unknown')}",
                "negative",
            )

    grid.on("cellValueChanged", on_cell_changed)


def attach_gradebook_edit_handler(
    grid: ui.aggrid,
    conn: duckdb.DuckDBPyConnection,
    pending: PendingChanges,
    update_pending_display: Any,
) -> None:
    """Attach edit handler for the pivoted gradebook grid."""

    def on_cell_changed(e: Any) -> None:
        data = e.args
        col_def = data.get("colDef")
        if col_def:
            col_field = col_def["field"]
        else:
            col_field = data.get("colId", data.get("column"))
        if not col_field or not col_field.startswith("_a"):
            return

        canvas_assignment_id = int(col_field[2:])  # strip "_a" prefix
        canvas_user_id = data["data"]["_canvas_user_id"]
        new_grade = data["value"] or ""

        old_row = conn.execute(
            "SELECT posted_grade FROM canvas_grades "
            "WHERE canvas_user_id = ? AND canvas_assignment_id = ?",
            [canvas_user_id, canvas_assignment_id],
        ).fetchone()

        if old_row is None:
            conn.execute(
                "INSERT INTO canvas_grades "
                "(canvas_user_id, canvas_assignment_id, posted_grade, updated_at) "
                "VALUES (?, ?, ?, 0)",
                [canvas_user_id, canvas_assignment_id, new_grade],
            )
            old_value = ""
        else:
            old_value = old_row[0]
            conn.execute(
                "UPDATE canvas_grades SET posted_grade = ? "
                "WHERE canvas_user_id = ? AND canvas_assignment_id = ?",
                [new_grade, canvas_user_id, canvas_assignment_id],
            )

        pk: dict[str, object] = {
            "canvas_user_id": canvas_user_id,
            "canvas_assignment_id": canvas_assignment_id,
        }
        track_change(pending, "canvas_grades", pk, "posted_grade", old_value, new_grade)
        update_pending_display()
        notify("Saved grade")
        grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
            "flashCells",
            {"columns": [col_field], "flashDuration": 300, "fadeDuration": 200},
        )

    grid.on("cellValueChanged", on_cell_changed)


# ---------------------------------------------------------------------------
# Grid utilities
# ---------------------------------------------------------------------------


_NotifyLevel = Literal["positive", "negative", "warning", "info"]


def notify(text: str, level: _NotifyLevel = "positive") -> None:
    """Show a toast notification in the bottom-left corner."""
    ui.notify(
        text,
        type=level,
        position="bottom-left",
        close_button=True,
    )


def find_grid(grid_container: dict[str, Any]) -> ui.aggrid | None:
    """Find the AG Grid element inside a container."""
    container = grid_container.get("ref")
    if container is None:
        return None
    for child in container:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(child, ui.aggrid):
            return child
    return None


def apply_search(grid_container: dict[str, Any], search_text: object) -> None:
    """Apply quick filter to the AG Grid in the container."""
    grid = find_grid(grid_container)
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


def export_csv(grid_container: dict[str, Any]) -> None:
    """Export current grid data as CSV via AG Grid's built-in export."""
    grid = find_grid(grid_container)
    if grid is not None:
        grid.run_grid_method("exportDataAsCsv")  # pyright: ignore[reportUnknownMemberType]


def _grid_to_markdown(grid: ui.aggrid) -> str:
    """Convert AG Grid options to a markdown table string."""
    col_defs = cast(list[Any], grid.options.get("columnDefs", []))  # pyright: ignore[reportUnknownMemberType]
    row_data = cast(list[Any], grid.options.get("rowData", []))  # pyright: ignore[reportUnknownMemberType]

    headers: list[str] = []
    fields: list[str] = []
    for col in col_defs:
        children: list[Any] = col.get("children", [])  # pyright: ignore[reportUnknownMemberType]
        if children:
            for child in children:  # pyright: ignore[reportUnknownVariableType]
                if not child.get("hide"):  # pyright: ignore[reportUnknownMemberType]
                    headers.append(str(child.get("headerName", child["field"])))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
                    fields.append(str(child["field"]))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        elif not col.get("hide"):  # pyright: ignore[reportUnknownMemberType]
            headers.append(str(col.get("headerName", col["field"])))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            fields.append(str(col["field"]))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]

    widths = [len(h) for h in headers]
    rows_str: list[list[str]] = []
    for row in row_data:  # pyright: ignore[reportUnknownVariableType]
        cells = [str(row.get(f, "") or "") for f in fields]  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))
        rows_str.append(cells)

    def fmt(cells: list[str]) -> str:
        return (
            "| "
            + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True))
            + " |"
        )

    lines = [
        fmt(headers),
        "| " + " | ".join("-" * w for w in widths) + " |",
        *[fmt(r) for r in rows_str],
    ]
    return "\n".join(lines) + "\n"


def export_markdown(
    grid_container: dict[str, Any],
    current_table: dict[str, str],
) -> None:
    """Export current grid data as a markdown file download."""
    grid = find_grid(grid_container)
    if grid is None:
        return
    title = display_name(current_table["name"])
    md = f"# {title}\n\n{_grid_to_markdown(grid)}"
    filename = f"{current_table['name']}.md"
    ui.download(md.encode(), filename)


def reload_current_grid(
    conn: duckdb.DuckDBPyConnection,
    grid_container: dict[str, Any],
    table_name: str,
) -> None:
    """Reload the AG Grid with fresh data from the DB."""
    grid = find_grid(grid_container)
    if grid is not None:
        if table_name == "canvas_grades":
            new_rows, _col_defs = build_gradebook_view(conn)
        else:
            new_rows = get_table_rows(conn, table_name)
        grid.options["rowData"] = new_rows  # pyright: ignore[reportUnknownMemberType]
        grid.update()


def revert_pending(
    conn: duckdb.DuckDBPyConnection,
    pending: PendingChanges,
    update_pending_display: Any,
    grid_container: dict[str, Any],
    current_table: dict[str, str],
) -> None:
    """Revert all pending changes in the DB and reload the grid."""
    count = pending_count(pending)
    for table, rows in pending.items():
        pk_cols = get_primary_keys(conn, table)
        for pk_key, cols in rows.items():
            pk = {pk_cols[0]: pk_key} if len(pk_cols) == 1 else json.loads(pk_key)
            where_parts = [f"{col} = ?" for col in pk_cols]
            where_clause = " AND ".join(where_parts)
            pk_values = [pk[col] for col in pk_cols]
            for col_name, change in cols.items():
                sql = f"UPDATE {table} SET {col_name} = ? WHERE {where_clause}"
                conn.execute(sql, [change["baseline"], *pk_values])
    pending.clear()
    update_pending_display()
    reload_current_grid(conn, grid_container, current_table["name"])
    notify(f"Reverted {count} change{'s' if count != 1 else ''}")
