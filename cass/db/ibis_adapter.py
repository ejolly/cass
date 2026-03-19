"""Generic DB adapter via ibis-framework — DuckDB and SQLite backends."""

from __future__ import annotations

__docformat__ = "google"

import math
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import ibis
from ibis import BaseBackend


def connect_file(filepath: Path) -> BaseBackend:
    """Connect to a DuckDB or SQLite file via ibis.

    Raises:
        SystemExit: If the file does not exist or has an unsupported suffix.
    """
    if not filepath.exists():
        raise SystemExit(f"File not found: {filepath}")

    suffix = filepath.suffix.lower()
    if suffix == ".duckdb":
        return ibis.duckdb.connect(str(filepath))
    if suffix == ".db":
        return ibis.sqlite.connect(str(filepath))

    raise SystemExit(f"Unsupported file type: {suffix}")


def list_tables(con: BaseBackend) -> list[dict[str, str]]:
    """List all tables in the connected database."""
    return [{"name": t, "type": "table"} for t in sorted(con.list_tables())]


def get_schema(con: BaseBackend, table: str) -> list[tuple[str, str]]:
    """Return column names and type strings for a table."""
    t = con.table(table)
    return [(name, str(dtype)) for name, dtype in t.schema().items()]


def get_primary_keys(con: BaseBackend, table: str) -> list[str]:
    """Detect primary key columns via PRAGMA table_info.

    Works for both DuckDB (pk flag is bool) and SQLite (pk flag is int > 0).
    Falls back to empty list if detection fails.
    """
    try:
        native = con.raw_sql(f"PRAGMA table_info('{table}')")
        rows = native.fetchall()
        # Column layout: (cid, name, type, notnull, default_value, pk)
        pks = []
        for row in rows:
            pk_flag = row[5]
            is_pk = (isinstance(pk_flag, bool) and pk_flag) or (
                isinstance(pk_flag, int) and pk_flag > 0
            )
            if is_pk:
                pks.append(row[1])
        return pks
    except Exception:
        return []


def _sanitize(obj: object) -> object:
    """Replace float NaN/Inf with None and convert datetimes for JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%dT%H:%M")
    if isinstance(obj, (date, time)):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    return obj


def get_rows(
    con: BaseBackend, table: str, *, limit: int = 10_000
) -> list[dict[str, Any]]:
    """Fetch rows from a table as sanitized list of dicts."""
    t = con.table(table)
    df = t.limit(limit).execute()
    rows = df.to_dict("records")  # pyright: ignore[reportUnknownMemberType]
    return [
        {k: _sanitize(v) for k, v in row.items()}  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        for row in rows
    ]


def get_row_count(con: BaseBackend, table: str) -> int:
    """Return the number of rows in a table."""
    t = con.table(table)
    result = t.count().execute()  # pyright: ignore[reportUnknownMemberType]
    return int(result)  # type: ignore[arg-type]  # pyright: ignore[reportUnknownArgumentType]


def update_cell(
    con: BaseBackend,
    table: str,
    pk_col: str,
    pk_val: Any,
    column: str,
    value: Any,
) -> dict[str, Any]:
    """Update a single cell value and return status dict."""
    try:
        # Use raw SQL via native connection for UPDATE
        pk_literal = f"'{pk_val}'" if isinstance(pk_val, str) else str(pk_val)

        if isinstance(value, str):
            val_literal = f"'{value}'"
        elif value is None:
            val_literal = "NULL"
        else:
            val_literal = str(value)

        sql = (
            f"UPDATE {table} SET {column} = {val_literal} WHERE {pk_col} = {pk_literal}"
        )
        con.raw_sql(sql)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_sql(con: BaseBackend, sql: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Execute raw SQL and return (column_names, list_of_row_dicts)."""
    cursor = con.raw_sql(sql)
    columns = [desc[0] for desc in cursor.description]
    raw_rows = cursor.fetchall()
    rows = [dict(zip(columns, row, strict=False)) for row in raw_rows]
    return columns, rows


def backend_name(con: BaseBackend) -> str:
    """Return the backend name: 'duckdb' or 'sqlite'."""
    return con.name
