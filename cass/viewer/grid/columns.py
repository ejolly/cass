"""AG Grid column definitions, gradebook pivot views, and JS render constants."""

from __future__ import annotations

__docformat__ = "google"

import math
from datetime import date, datetime, time
from typing import Any, cast

import sqlite_utils

from ...db import (
    ENRICHED_QUERIES,
    get_assignment_groups,
    get_primary_keys,
    get_table_capability,
    is_editable,
    load_canvas_gradebook_data,
)
from ..config import (
    COLUMN_DISPLAY_NAMES,
    COLUMN_ORDERING,
    HIDDEN_COLUMNS,
)

# ---------------------------------------------------------------------------
# Sanitization (JSON-safe values for AG Grid)
# ---------------------------------------------------------------------------


def sanitize(obj: object) -> object:  # pyright: ignore[reportUnknownParameterType]
    """Replace float NaN/Inf with None and convert datetimes for JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%dT%H:%M")
    if isinstance(obj, (date, time)):
        return obj.isoformat()
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return obj


# ---------------------------------------------------------------------------
# Table rows (enriched query + sanitize)
# ---------------------------------------------------------------------------


def get_table_rows(conn: sqlite_utils.Database, table: str) -> list[dict[str, Any]]:
    """Return all rows from a table as sanitized list of dicts."""
    from ...db import get_enriched_rows

    rows = get_enriched_rows(conn, table)
    return cast(list[dict[str, Any]], [sanitize(row) for row in rows])


# ---------------------------------------------------------------------------
# JS render constants
# ---------------------------------------------------------------------------

_LINK_JS = """
(params) => {
    if (!params.value) return '';
    const url = params.value;
    const short = url.replace('https://github.com/', '');
    const parts = short.split('/commit/');
    const label = parts.length > 1 ? parts[1].substring(0, 7) : parts[0];
    return '<a href="' + url + '" target="_blank" '
        + 'style="color:#60a5fa;text-decoration:underline">'
        + label + '</a>';
}
""".strip()

_DATE_LINK_JS = """
(params) => {
    if (!params.value) return '';
    const url = params.data && params.data.commit_url;
    if (url) {
        return '<a href="' + url + '" target="_blank" '
            + 'style="color:#60a5fa;text-decoration:underline">'
            + params.value + '</a>';
    }
    return params.value;
}
""".strip()

# URL columns that should render as clickable links
_LINK_COLUMNS = {"repo_url"}

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

_LATE_HIGHLIGHT_JS = """
(params) => {
    if (!params.value) return '';
    if (params.data && params.data.late)
        return '<span style="color:#f87171">' + params.value + '</span>';
    return params.value;
}
""".strip()

PENDING_CELL_RULE = (
    "window._pendingCells && window._pendingCells.has("
    "String(node.id) + '::' + colDef.field)"
)


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------


# Column names that hold datetime values (SQLite stores them as TEXT)
_DATETIME_COLUMNS = {"due_at", "submitted_at", "deadline", "updated_at"}


def _is_datetime_col(dtype: str, name: str = "") -> bool:
    """Check if a column is a datetime/timestamp."""
    return "TIMESTAMP" in dtype or "DATE" in dtype or name in _DATETIME_COLUMNS


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


def _get_col_types(conn: sqlite_utils.Database, table: str) -> dict[str, str]:
    """Get column type map for a table from PRAGMA table_info.

    For enriched queries that JOIN multiple tables, we merge type info
    from all tables referenced in the query.
    """
    types: dict[str, str] = {}
    if table in ENRICHED_QUERIES:
        # Gather types from all tables in the database
        for t in conn.table_names():
            for col in conn[t].columns:
                if col.name not in types:
                    types[col.name] = (col.type or "TEXT").upper()
    else:
        if table in conn.table_names():
            for col in conn[table].columns:
                types[col.name] = (col.type or "TEXT").upper()
    return types


def build_column_defs(conn: sqlite_utils.Database, table: str) -> list[dict[str, Any]]:
    """Build AG Grid column definitions for a table."""
    query = ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)
    col_names = [desc[0] for desc in result.description]
    col_types = _get_col_types(conn, table)

    display_cols = get_display_columns(table, col_names)
    hidden_cols = HIDDEN_COLUMNS.get(table, [])
    col_display_names = COLUMN_DISPLAY_NAMES.get(table, {})

    editable = is_editable(conn, table)
    pk_cols = get_primary_keys(conn, table) if editable else []
    capability = get_table_capability(table)
    editable_cols = capability.editable_columns

    # Pre-fetch select editor values for canvas_assignments
    group_values: list[str] = []
    if table == "canvas_assignments":
        group_values = get_assignment_groups(conn)

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

        # Link columns
        if name in _LINK_COLUMNS:
            col_def[":cellRenderer"] = _LINK_JS

        # Last commit date as link to commit
        if name == "last_commit_at" and table == "gh_submissions":
            col_def[":cellRenderer"] = _DATE_LINK_JS

        # Datetime formatting
        elif _is_datetime_col(dtype, name):
            if table == "canvas_submissions" and name == "submitted_at":
                col_def[":cellRenderer"] = _LATE_HIGHLIGHT_JS
            else:
                col_def[":valueFormatter"] = _DATETIME_JS

        # Column-level editability (respects editable_columns restriction)
        col_is_editable = (
            editable
            and name not in pk_cols
            and (editable_cols is None or name in editable_cols)
        )

        # Type-specific editors and renderers for editable columns
        if col_is_editable:
            if _is_datetime_col(dtype, name):
                col_def["cellEditor"] = "agDateStringCellEditor"
                if "TIMESTAMP" in dtype:
                    col_def["cellEditorParams"] = {"includeTime": True}
            elif "BOOL" in dtype:
                col_def["cellEditor"] = "agCheckboxCellEditor"
                col_def["cellRenderer"] = "agCheckboxCellRenderer"
                col_def["singleClickEdit"] = True
            elif any(t in dtype for t in ("INT", "DOUBLE", "FLOAT", "REAL")):
                col_def["cellEditor"] = "agNumberCellEditor"
            # Select editor for assignment_group on canvas_assignments
            elif (
                table == "canvas_assignments"
                and name == "assignment_group"
                and group_values
            ):
                col_def["cellEditor"] = "agSelectCellEditor"
                col_def["cellEditorParams"] = {"values": group_values}

        # PK columns: bold, dimmed, not editable
        if name in pk_cols:
            col_def["headerName"] = f"{header} (PK)"
            col_def["cellStyle"] = {
                "fontWeight": "bold",
                "opacity": "0.6",
            }

        if col_is_editable:
            col_def["editable"] = True
            col_def[":cellClassRules"] = {
                "cell-pending": PENDING_CELL_RULE,
            }

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
    conn: sqlite_utils.Database,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build pivoted gradebook data: students as rows, assignments as columns.

    Returns:
        (row_data, col_defs) — ready for AG Grid.
    """
    data = load_canvas_gradebook_data(conn)

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
    for assignment in data.assignments:
        field = f"_a{assignment.canvas_id}"
        subtitle = (
            "Unpublished"
            if not assignment.published
            else f"Out of {assignment.points_possible:g}"
        )
        child: dict[str, Any] = {
            "headerName": assignment.name,
            "field": field,
            "minWidth": 90,
            "sortable": True,
            "filter": False,
            "resizable": True,
            "editable": True,
            "cellEditor": "agNumberCellEditor",
            "headerTooltip": f"{assignment.name} — {subtitle}",
            "wrapHeaderText": True,
            "autoHeaderHeight": True,
            ":cellClassRules": {"cell-pending": PENDING_CELL_RULE},
        }
        if not assignment.published:
            child["cellStyle"] = {"opacity": "0.45"}
        else:
            child["cellStyle"] = {"backgroundColor": "rgba(59, 130, 246, 0.08)"}
        groups.setdefault(assignment.assignment_group or "Ungrouped", []).append(child)

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
    for student in data.students:
        row: dict[str, Any] = {
            "_student_name": student.sortable_name,
            "_canvas_user_id": student.canvas_id,
        }
        for assignment in data.assignments:
            row[f"_a{assignment.canvas_id}"] = data.grades.get(
                (student.canvas_id, assignment.canvas_id),
                "",
            )
        row_data.append(row)

    return row_data, col_defs


# ---------------------------------------------------------------------------
# GH Gradebook pivot view
# ---------------------------------------------------------------------------


def build_gh_gradebook_view(
    conn: sqlite_utils.Database,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build pivoted GH gradebook: students as rows, assignments as columns.

    Cells show ``X/Y`` where X = commits before deadline, Y = commits after.
    Read-only — no edit handlers.

    Returns:
        (row_data, col_defs) — ready for AG Grid.
    """
    # Fetch GH assignments ordered by deadline
    assignments = conn.execute(
        "SELECT slug, title, deadline FROM gh_assignments ORDER BY deadline, title"
    ).fetchall()

    # Fetch GH submissions, excluding hidden students via SQL
    subs_raw = conn.execute(
        "SELECT gs.github_username, gs.assignment_slug, gs.submitted, "
        "gs.commit_count, gs.commits_after_deadline "
        "FROM gh_submissions gs "
        "LEFT JOIN gh_students gst "
        "  ON gs.github_username = gst.github_username "
        "WHERE COALESCE(gst.excluded, false) = false"
    ).fetchall()
    sub_map: dict[tuple[str, str], tuple[bool, int, int]] = {
        (r[0], r[1]): (r[2], r[3], r[4]) for r in subs_raw
    }

    # Build student list: Canvas sortable_name when matched, else
    # convert GH "First Last" → "Last, First" for consistent sorting.
    # Excludes students marked as hidden in the Roster.
    student_rows = conn.execute(
        "SELECT gs.github_username, "
        "COALESCE("
        "  cs.sortable_name, "
        "  CASE WHEN gs.name LIKE '% %' "
        "    THEN substr(gs.name, instr(gs.name, ' ') + 1) "
        "      || ', ' "
        "      || substr(gs.name, 1, instr(gs.name, ' ') - 1) "
        "    ELSE gs.name END"
        ") AS display_name "
        "FROM gh_students gs "
        "LEFT JOIN students s ON gs.github_username = s.github_username "
        "LEFT JOIN canvas_students cs ON s.canvas_id = cs.canvas_id "
        "WHERE gs.excluded = 0 "
        "ORDER BY display_name"
    ).fetchall()

    # Also include students who have submissions but aren't in gh_students
    known_handles = {r[0] for r in student_rows}
    extra_handles = {h for h, _ in sub_map if h not in known_handles}
    for handle in sorted(extra_handles):
        student_rows.append((handle, handle))

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

    for slug, title, _deadline in assignments:
        field = f"_a{slug}"
        col_defs.append(
            {
                "headerName": title,
                "field": field,
                "minWidth": 80,
                "sortable": True,
                "filter": False,
                "resizable": True,
                "editable": False,
                "headerTooltip": title,
                "wrapHeaderText": True,
                "autoHeaderHeight": True,
            }
        )

    # Hidden username column for identification
    col_defs.append({"field": "_github_username", "hide": True})

    # Build row data
    row_data: list[dict[str, Any]] = []
    for handle, name in student_rows:
        row: dict[str, Any] = {
            "_student_name": name,
            "_github_username": handle,
        }
        for slug, _title, _deadline in assignments:
            field = f"_a{slug}"
            sub = sub_map.get((handle, slug))
            if sub and sub[1]:  # has commits
                commit_count, after = sub[1], sub[2]
                before = commit_count - after
                row[field] = f"{before}/{after}"
            else:
                row[field] = ""
        row_data.append(row)

    return row_data, col_defs
