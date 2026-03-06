"""Tests for cass.viewer — browser-based database viewer API endpoints."""

import json
import threading
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import duckdb
import pytest

from cass.viewer import ViewerHandler, _get_schema, _get_table_names, _get_tables


@pytest.fixture
def viewer_conn():
    """In-memory DuckDB with test tables (including one without a PK)."""
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE students ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  email TEXT,"
        "  excluded BOOLEAN DEFAULT false"
        ")"
    )
    conn.execute(
        "CREATE TABLE assignments ("
        "  slug TEXT PRIMARY KEY,"
        "  title TEXT,"
        "  points_possible DOUBLE"
        ")"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE logs (message TEXT, ts DOUBLE)")
    conn.execute(
        "INSERT INTO students VALUES (100, 'Alice Smith', 'alice@test.edu', false)"
    )
    conn.execute("INSERT INTO students VALUES (200, 'Bob Jones', 'bob@test.edu', true)")
    conn.execute("INSERT INTO assignments VALUES ('hw-01', 'Homework 1', 10.0)")
    yield conn
    conn.close()


@pytest.fixture
def server(viewer_conn):
    """HTTPServer on a random port using the test DuckDB connection."""
    ViewerHandler.conn = viewer_conn
    ViewerHandler.valid_tables = _get_table_names(viewer_conn)

    srv = HTTPServer(("127.0.0.1", 0), ViewerHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _get(base_url, path):
    """GET request, return parsed JSON."""
    with urlopen(f"{base_url}{path}") as resp:
        return json.loads(resp.read())


def _post(base_url, path, data):
    """POST request, return (status_code, parsed JSON)."""
    body = json.dumps(data).encode()
    req = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


# --- Unit tests (no server needed) ---


def test_get_tables_excludes_meta(viewer_conn):
    tables = _get_tables(viewer_conn)
    names = [t["name"] for t in tables]
    assert "meta" not in names
    assert "students" in names
    assert "assignments" in names
    assert "logs" in names


def test_get_tables_types(viewer_conn):
    tables = _get_tables(viewer_conn)
    by_name = {t["name"]: t["type"] for t in tables}
    assert by_name["students"] == "table"
    assert by_name["logs"] == "table"


def test_get_table_names(viewer_conn):
    names = _get_table_names(viewer_conn)
    assert "students" in names
    assert "meta" not in names


def test_get_schema_table(viewer_conn):
    schema = _get_schema(viewer_conn, "students")
    assert schema["table"] == "students"
    assert schema["editable"] is True
    assert schema["primary_keys"] == ["canvas_id"]
    columns: list[dict[str, object]] = schema["columns"]  # type: ignore[assignment]
    col_names = [c["name"] for c in columns]
    assert "canvas_id" in col_names
    assert "name" in col_names


def test_get_schema_no_pk(viewer_conn):
    """Tables without a primary key are not editable."""
    schema = _get_schema(viewer_conn, "logs")
    assert schema["editable"] is False
    assert schema["primary_keys"] == []


# --- Integration tests (with server) ---


def test_index_page(server):
    with urlopen(f"{server}/") as resp:
        assert resp.status == 200
        html = resp.read().decode()
        assert "ag-grid" in html.lower() or "AG Grid" in html


def test_tables_endpoint(server):
    data = _get(server, "/api/tables")
    names = [t["name"] for t in data["tables"]]
    assert "students" in names
    assert "meta" not in names


def test_schema_endpoint(server):
    data = _get(server, "/api/schema/students")
    assert data["editable"] is True
    assert "canvas_id" in data["primary_keys"]


def test_table_data_endpoint(server):
    data = _get(server, "/api/table/students")
    assert data["table"] == "students"
    assert len(data["rows"]) == 2
    assert "canvas_id" in data["columns"]


def test_update_cell(server):
    status, result = _post(
        server,
        "/api/update/students",
        {
            "pk": {"canvas_id": 100},
            "column": "name",
            "value": "Alice B. Smith",
        },
    )
    assert status == 200
    assert result["ok"] is True

    # Verify the change persisted
    data = _get(server, "/api/table/students")
    alice_row = next(
        r for r in data["rows"] if r[data["columns"].index("canvas_id")] == 100
    )
    assert alice_row[data["columns"].index("name")] == "Alice B. Smith"


def test_update_rejects_no_pk_table(server):
    """Tables without primary keys reject edits."""
    status, result = _post(
        server,
        "/api/update/logs",
        {
            "pk": {},
            "column": "message",
            "value": "test",
        },
    )
    assert status == 400
    assert result["ok"] is False


def test_update_rejects_unknown_table(server):
    status, result = _post(
        server,
        "/api/update/nonexistent",
        {
            "pk": {"id": 1},
            "column": "name",
            "value": "test",
        },
    )
    assert status == 404


def test_update_rejects_unknown_column(server):
    status, result = _post(
        server,
        "/api/update/students",
        {
            "pk": {"canvas_id": 100},
            "column": "nonexistent",
            "value": "test",
        },
    )
    assert status == 400
    assert "Unknown column" in result["error"]


def test_unknown_api_path(server):
    with pytest.raises(HTTPError, match="404"):
        urlopen(f"{server}/api/nonexistent")
