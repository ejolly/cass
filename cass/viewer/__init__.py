"""Browser-based database viewer — local HTTP server with AG Grid frontend."""

from __future__ import annotations

__docformat__ = "google"

import json
import math
import re
import webbrowser
from datetime import date, datetime, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from typing import TYPE_CHECKING

import duckdb
from rich.console import Console

from ..db import db_path, reset as db_reset

if TYPE_CHECKING:
    from ..canvas.client import CanvasClient

console = Console()

# Type aliases for the pending-changes structure:
#   table -> pk_key -> column -> {"baseline": ..., "current": ...}
_ChangeFields = dict[str, object]
_RowChanges = dict[str, _ChangeFields]
_TableChanges = dict[str, _RowChanges]
_PendingChanges = dict[str, _TableChanges]

_EXCLUDED_TABLES = {"meta"}

# Tables that are generated/pulled data and should not be editable in the viewer.
_READ_ONLY_TABLES = {
    "canvas_submissions",
    "gh_submissions",
    "gh_grades",
}

# Columns on canvas tables that can be pushed back to the Canvas API.
_CANVAS_PUSHABLE: dict[str, set[str]] = {
    "canvas_assignments": {"name", "points_possible", "due_at", "published"},
    "canvas_grades": {"posted_grade"},
}

# Enriched queries that JOIN in human-readable names for ID-heavy tables.
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


class _ViewerEncoder(json.JSONEncoder):
    """JSON encoder that handles DuckDB types."""

    def default(self, o: object) -> object:
        if isinstance(o, (datetime, date, time)):
            return o.isoformat()
        return super().default(o)

    def encode(self, o: object) -> str:  # noqa: D102
        return super().encode(_sanitize(o))


def _sanitize(obj: object) -> object:
    """Replace float NaN/Inf with None for JSON compatibility."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return obj


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj, cls=_ViewerEncoder).encode()


# ---------------------------------------------------------------------------
# DB introspection helpers
# ---------------------------------------------------------------------------


def _get_tables(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    """Return list of tables and views with their type."""
    rows = conn.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_type, table_name"
    ).fetchall()
    return [
        {"name": name, "type": "view" if "VIEW" in ttype else "table"}
        for name, ttype in rows
        if name not in _EXCLUDED_TABLES
    ]


def _get_table_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """Return set of valid table/view names."""
    return {t["name"] for t in _get_tables(conn)}


def _get_column_names(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return column names for a table."""
    cols_raw = conn.execute(f"DESCRIBE {table}").fetchall()  # noqa: S608
    return [row[0] for row in cols_raw]


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


def _get_schema(conn: duckdb.DuckDBPyConnection, table: str) -> dict[str, object]:
    """Return column defs, primary keys, editability, and pushable info."""
    cols_raw = conn.execute(f"DESCRIBE {table}").fetchall()  # noqa: S608
    columns: list[dict[str, object]] = [
        {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
        for row in cols_raw
    ]

    pk_cols = _get_primary_keys(conn, table)

    tables = _get_tables(conn)
    table_type = next((t["type"] for t in tables if t["name"] == table), None)
    editable = (
        table_type == "table" and len(pk_cols) > 0 and table not in _READ_ONLY_TABLES
    )

    return {
        "table": table,
        "columns": columns,
        "primary_keys": pk_cols,
        "editable": editable,
        "canvas_pushable": sorted(_CANVAS_PUSHABLE.get(table, set())),
    }


def _get_table_data(conn: duckdb.DuckDBPyConnection, table: str) -> dict[str, object]:
    """Return all rows from a table/view as JSON-friendly structure."""
    query = _ENRICHED_QUERIES.get(table, f"SELECT * FROM {table}")
    result = conn.execute(query)  # noqa: S608
    col_names = [desc[0] for desc in result.description]
    col_types = [str(desc[1]) for desc in result.description]
    rows = result.fetchall()
    return {
        "table": table,
        "columns": col_names,
        "types": col_types,
        "rows": [list(row) for row in rows],
    }


# ---------------------------------------------------------------------------
# Cell update
# ---------------------------------------------------------------------------


def _update_cell(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    pk: dict[str, object],
    column: str,
    value: object,
) -> dict[str, object]:
    """Update a single cell in a table.

    Returns:
        Dict with ``ok``, and ``old_value`` on success.
    """
    tables = _get_tables(conn)
    table_type = next((t["type"] for t in tables if t["name"] == table), None)
    pk_cols = _get_primary_keys(conn, table)
    if table_type != "table" or not pk_cols:
        return {"ok": False, "error": "Table is not editable"}

    valid_cols = _get_column_names(conn, table)
    if column not in valid_cols:
        return {"ok": False, "error": f"Unknown column: {column}"}

    if set(pk.keys()) != set(pk_cols):
        return {"ok": False, "error": f"Expected PK columns: {pk_cols}"}

    where_parts = [f"{col} = ?" for col in pk_cols]
    where_clause = " AND ".join(where_parts)
    pk_values = [pk[col] for col in pk_cols]

    # Capture old value before update
    old_row = conn.execute(
        f"SELECT {column} FROM {table} WHERE {where_clause}",  # noqa: S608
        pk_values,
    ).fetchone()
    old_value = old_row[0] if old_row else None

    sql = f"UPDATE {table} SET {column} = ? WHERE {where_clause}"  # noqa: S608
    conn.execute(sql, [value, *pk_values])

    verify = conn.execute(
        f"SELECT {column} FROM {table} WHERE {where_clause}",  # noqa: S608
        pk_values,
    ).fetchone()

    if verify is None:
        return {"ok": False, "error": "No matching row found"}

    return {"ok": True, "old_value": old_value}


# ---------------------------------------------------------------------------
# Pending change tracking (server-side, in-memory)
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


def _track_change(
    pending: _PendingChanges,
    table: str,
    pk: dict[str, object],
    column: str,
    old_value: object,
    new_value: object,
) -> None:
    """Record a cell edit as a pending Canvas change.

    Tracks baseline (original value before first edit) and current value.
    If the user edits back to baseline, the entry is removed.
    """
    pushable = _CANVAS_PUSHABLE.get(table)
    if not pushable or column not in pushable:
        return

    pk_key = (
        str(list(pk.values())[0]) if len(pk) == 1 else json.dumps(pk, sort_keys=True)
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


def _resolve_row_name(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    pk_key: str,
) -> str:
    """Resolve a pending-change pk_key to a human-readable row name."""
    if table == "canvas_assignments":
        row = conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [int(pk_key)],
        ).fetchone()
        return row[0] if row else pk_key
    if table == "canvas_grades":
        pk = json.loads(pk_key)
        uid, aid = pk["canvas_user_id"], pk["canvas_assignment_id"]
        row = conn.execute(
            "SELECT st.name, ca.name "
            "FROM canvas_students st, canvas_assignments ca "
            "WHERE st.canvas_id = ? AND ca.canvas_id = ?",
            [uid, aid],
        ).fetchone()
        if row:
            return f"{row[0]} — {row[1]}"
        return pk_key
    return pk_key


def _get_pending_summary(
    conn: duckdb.DuckDBPyConnection,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Return pending changes with human-readable names for display."""
    changes: list[dict[str, object]] = []
    for table, rows in pending.items():
        pk_col = _get_primary_keys(conn, table)
        pk_name = pk_col[0] if pk_col else "id"

        for pk_key, columns in rows.items():
            row_name = _resolve_row_name(conn, table, pk_key)
            for col, vals in columns.items():
                changes.append(
                    {
                        "table": table,
                        "pk_column": pk_name,
                        "pk_value": pk_key,
                        "row_name": row_name,
                        "column": col,
                        "baseline": vals["baseline"],
                        "current": vals["current"],
                    }
                )

    return {"ok": True, "count": len(changes), "changes": changes}


# ---------------------------------------------------------------------------
# Canvas sync: preview and apply
# ---------------------------------------------------------------------------


def _preview_assignments(
    conn: duckdb.DuckDBPyConnection,
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending assignment changes against live Canvas state."""
    results: list[dict[str, object]] = []
    for pk_key, columns in table_changes.items():
        canvas_id = int(pk_key)
        name_row = conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [canvas_id],
        ).fetchone()
        assignment_name = name_row[0] if name_row else f"ID {canvas_id}"

        try:
            live = client.get_assignment(canvas_id)
            for col, vals in columns.items():
                live_val = getattr(live, col, None)
                conflict = not _values_equal(live_val, vals["baseline"])
                results.append(
                    {
                        "table": "canvas_assignments",
                        "canvas_id": canvas_id,
                        "name": assignment_name,
                        "column": col,
                        "baseline": vals["baseline"],
                        "current": vals["current"],
                        "live": live_val,
                        "conflict": conflict,
                    }
                )
        except Exception as e:
            results.append(
                {
                    "table": "canvas_assignments",
                    "canvas_id": canvas_id,
                    "name": assignment_name,
                    "error": str(e),
                }
            )
    return results


def _preview_grades(
    conn: duckdb.DuckDBPyConnection,
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending grade changes against live Canvas submissions."""
    results: list[dict[str, object]] = []

    # Group changes by assignment_id for efficient fetching
    by_assignment: dict[int, list[tuple[int, _RowChanges]]] = {}
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        by_assignment.setdefault(aid, []).append((uid, columns))

    for aid, student_changes in by_assignment.items():
        assignment_name = _resolve_row_name(conn, "canvas_assignments", str(aid))

        try:
            live_subs = client.list_submissions(aid)
            live_by_user = {s.user_id: s for s in live_subs}

            for uid, columns in student_changes:
                student_row = conn.execute(
                    "SELECT name FROM canvas_students WHERE canvas_id = ?",
                    [uid],
                ).fetchone()
                student_name = student_row[0] if student_row else f"User {uid}"

                live_sub = live_by_user.get(uid)
                for col, vals in columns.items():
                    live_val = None
                    if live_sub:
                        if col == "posted_grade":
                            live_val = live_sub.grade
                        elif col == "score":
                            live_val = live_sub.score
                    conflict = not _values_equal(live_val, vals["baseline"])
                    results.append(
                        {
                            "table": "canvas_grades",
                            "canvas_assignment_id": aid,
                            "canvas_user_id": uid,
                            "name": f"{student_name} — {assignment_name}",
                            "column": col,
                            "baseline": vals["baseline"],
                            "current": vals["current"],
                            "live": live_val,
                            "conflict": conflict,
                        }
                    )
        except Exception as e:
            results.append(
                {
                    "table": "canvas_grades",
                    "canvas_assignment_id": aid,
                    "name": assignment_name,
                    "error": str(e),
                }
            )

    return results


def _canvas_preview(
    conn: duckdb.DuckDBPyConnection,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Compare pending changes against live Canvas state (dry-run)."""
    from ..canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "changes": []}

    results: list[dict[str, object]] = []
    with CanvasClient() as c:
        if assignment_changes:
            results.extend(_preview_assignments(conn, assignment_changes, c))
        if grade_changes:
            results.extend(_preview_grades(conn, grade_changes, c))

    return {
        "ok": True,
        "changes": results,
        "has_conflicts": any(r.get("conflict") for r in results),
        "has_errors": any("error" in r for r in results),
    }


def _apply_assignments(
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Push pending assignment changes to Canvas."""
    results: list[dict[str, object]] = []
    for pk_key, columns in list(table_changes.items()):
        canvas_id = int(pk_key)
        kwargs = {col: vals["current"] for col, vals in columns.items()}
        try:
            client.update_assignment(canvas_id, **kwargs)
            results.append({"canvas_id": canvas_id, "ok": True})
            del table_changes[pk_key]
        except Exception as e:
            results.append({"canvas_id": canvas_id, "ok": False, "error": str(e)})
    return results


def _apply_grades(
    table_changes: _TableChanges,
    client: CanvasClient,
    conn: duckdb.DuckDBPyConnection,
) -> list[dict[str, object]]:
    """Push pending grade changes to Canvas via bulk update_grades.

    For assignments with ``post_manually=True``, grades are also posted
    (made visible to students) via the Canvas GraphQL API.
    """
    results: list[dict[str, object]] = []

    # Group by assignment_id for bulk push
    by_assignment: dict[int, dict[int, str]] = {}
    pk_keys_by_assignment: dict[int, list[str]] = {}
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        # Use posted_grade for the push
        grade_val = columns.get("posted_grade", {}).get("current")
        if grade_val is not None:
            by_assignment.setdefault(aid, {})[uid] = str(grade_val)
            pk_keys_by_assignment.setdefault(aid, []).append(pk_key)

    # Look up post_manually status
    manual_rows = conn.execute(
        "SELECT canvas_id, post_manually FROM canvas_assignments"
    ).fetchall()
    post_manually_map = {r[0]: r[1] for r in manual_rows}

    pushed_aids: list[int] = []
    for aid, grade_data in by_assignment.items():
        try:
            progress = client.bulk_push_grades(aid, grade_data)
            client.wait_for_progress(progress.id)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": True,
                    "count": len(grade_data),
                }
            )
            pushed_aids.append(aid)
            # Clear successful changes
            for pk_key in pk_keys_by_assignment[aid]:
                table_changes.pop(pk_key, None)
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "error": str(e),
                    "count": len(grade_data),
                }
            )

    # Post grades for manual-post assignments (make visible to students)
    for aid in pushed_aids:
        if not post_manually_map.get(aid):
            continue
        try:
            p = client.post_assignment_grades(aid, graded_only=True)
            if p:
                client.wait_for_progress(p.id)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": True,
                    "action": "posted_to_students",
                }
            )
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "action": "posted_to_students",
                    "error": str(e),
                }
            )

    return results


def _canvas_apply(
    conn: duckdb.DuckDBPyConnection,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Push pending changes to Canvas and clear them on success."""
    from ..canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "results": []}

    results: list[dict[str, object]] = []
    with CanvasClient() as c:
        if assignment_changes:
            results.extend(_apply_assignments(assignment_changes, c))
        if grade_changes:
            results.extend(_apply_grades(grade_changes, c, conn))

    # Clean up empty table entries
    if not assignment_changes:
        pending.pop("canvas_assignments", None)
    if not grade_changes:
        pending.pop("canvas_grades", None)

    return {"ok": all(r.get("ok") for r in results), "results": results}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

_PATH_RE = re.compile(r"^/api/(tables|schema|table|update)/?([\w]*)$")


class ViewerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the database viewer."""

    conn: duckdb.DuckDBPyConnection
    valid_tables: set[str]
    pending_changes: _PendingChanges
    use_classic: bool

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default stderr logging."""

    def _send_json(self, data: object, status: int = 200) -> None:
        body = _json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status)

    def _send_html(self, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_body(self) -> bytes:
        """Read the request body."""
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def _send_js(self, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests."""
        if self.path == "/":
            if self.use_classic:
                html = files("cass.viewer").joinpath("index_classic.html").read_bytes()
            else:
                html = files("cass.viewer").joinpath("index.html").read_bytes()
            self._send_html(html)
            return

        if self.path == "/elm.js" and not self.use_classic:
            js = files("cass.viewer").joinpath("elm.js").read_bytes()
            self._send_js(js)
            return

        if self.path == "/api/pending":
            self._send_json(_get_pending_summary(self.conn, self.pending_changes))
            return

        match = _PATH_RE.match(self.path)
        if not match:
            self._send_error_json(404, "Not found")
            return

        action, name = match.group(1), match.group(2)

        if action == "tables":
            self._send_json({"tables": _get_tables(self.conn)})
            return

        if not name:
            self._send_error_json(400, "Missing table name")
            return

        if name not in self.valid_tables:
            self._send_error_json(404, f"Unknown table: {name}")
            return

        if action == "schema":
            self._send_json(_get_schema(self.conn, name))
        elif action == "table":
            self._send_json(_get_table_data(self.conn, name))
        else:
            self._send_error_json(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests."""
        if self.path == "/api/canvas/preview":
            try:
                result = _canvas_preview(self.conn, self.pending_changes)
                self._send_json(result)
            except Exception as e:
                self._send_error_json(500, str(e))
            return

        if self.path == "/api/canvas/apply":
            try:
                result = _canvas_apply(self.conn, self.pending_changes)
                status = 200 if result["ok"] else 207
                self._send_json(result, status)
            except Exception as e:
                self._send_error_json(500, str(e))
            return

        if self.path == "/api/pending/clear":
            self.pending_changes.clear()
            self._send_json({"ok": True})
            return

        # --- Cell update ---
        match = _PATH_RE.match(self.path)
        if not match or match.group(1) != "update":
            self._send_error_json(404, "Not found")
            return

        name = match.group(2)
        if not name:
            self._send_error_json(400, "Missing table name")
            return

        if name not in self.valid_tables:
            self._send_error_json(404, f"Unknown table: {name}")
            return

        try:
            data = json.loads(self._read_body())
        except json.JSONDecodeError:
            self._send_error_json(400, "Invalid JSON")
            return

        pk = data.get("pk")
        column = data.get("column")
        value = data.get("value")

        if pk is None or column is None:
            self._send_error_json(400, "Missing pk or column")
            return

        result = _update_cell(self.conn, name, pk, column, value)
        if result["ok"]:
            _track_change(
                self.pending_changes,
                name,
                pk,
                column,
                result["old_value"],
                value,
            )
            result["pending_count"] = _pending_count(self.pending_changes)

        status = 200 if result["ok"] else 400
        self._send_json(result, status)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def start_server(port: int = 0, *, classic: bool = False) -> None:
    """Start the viewer server, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
        classic: Use the classic AG Grid frontend instead of the default Elm frontend.
    """
    db_file = db_path()

    # Release any existing singleton connection
    db_reset()

    conn = duckdb.connect(db_file)
    valid_tables = _get_table_names(conn)

    ViewerHandler.conn = conn
    ViewerHandler.valid_tables = valid_tables
    ViewerHandler.pending_changes = {}
    ViewerHandler.use_classic = classic

    server = HTTPServer(("127.0.0.1", port), ViewerHandler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"

    console.print(f"Viewer running at [bold]{url}[/bold]")
    console.print("Press [bold]Ctrl+C[/bold] to stop.\n")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Viewer stopped.[/dim]")
    finally:
        server.shutdown()
        conn.close()
