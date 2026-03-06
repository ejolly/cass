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

import duckdb
from rich.console import Console

from ..db import db_path, reset as db_reset

console = Console()

_EXCLUDED_TABLES = {"meta"}


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
        return [_sanitize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    return obj


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj, cls=_ViewerEncoder).encode()


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
    """Return column defs, primary keys, and editability for a table."""
    cols_raw = conn.execute(f"DESCRIBE {table}").fetchall()  # noqa: S608
    columns: list[dict[str, object]] = [
        {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
        for row in cols_raw
    ]

    pk_cols = _get_primary_keys(conn, table)

    tables = _get_tables(conn)
    table_type = next((t["type"] for t in tables if t["name"] == table), None)
    editable = table_type == "table" and len(pk_cols) > 0

    return {
        "table": table,
        "columns": columns,
        "primary_keys": pk_cols,
        "editable": editable,
    }


def _get_table_data(conn: duckdb.DuckDBPyConnection, table: str) -> dict[str, object]:
    """Return all rows from a table/view as JSON-friendly structure."""
    result = conn.execute(f"SELECT * FROM {table}")  # noqa: S608
    col_names = [desc[0] for desc in result.description]
    col_types = [str(desc[1]) for desc in result.description]
    rows = result.fetchall()
    return {
        "table": table,
        "columns": col_names,
        "types": col_types,
        "rows": [list(row) for row in rows],
    }


def _update_cell(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    pk: dict[str, object],
    column: str,
    value: object,
) -> dict[str, object]:
    """Update a single cell in a table."""
    # Check editability
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

    sql = f"UPDATE {table} SET {column} = ? WHERE {where_clause}"  # noqa: S608
    conn.execute(sql, [value, *pk_values])

    # Verify the update took effect
    verify = conn.execute(
        f"SELECT {column} FROM {table} WHERE {where_clause}",  # noqa: S608
        pk_values,
    ).fetchone()

    if verify is None:
        return {"ok": False, "error": "No matching row found"}

    return {"ok": True}


_PATH_RE = re.compile(r"^/api/(tables|schema|table|update)/?([\w]*)$")


class ViewerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the database viewer."""

    conn: duckdb.DuckDBPyConnection
    valid_tables: set[str]

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

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests."""
        if self.path == "/":
            html = files("cass.viewer").joinpath("index.html").read_bytes()
            self._send_html(html)
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

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
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
        status = 200 if result["ok"] else 400
        self._send_json(result, status)


def start_server(port: int = 0) -> None:
    """Start the viewer server, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
    """
    db_file = db_path()

    # Release any existing singleton connection
    db_reset()

    conn = duckdb.connect(db_file)
    valid_tables = _get_table_names(conn)

    ViewerHandler.conn = conn
    ViewerHandler.valid_tables = valid_tables

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
