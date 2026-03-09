"""Viewer DB introspection — table metadata, cell editing, and revert.

Functions used by the viewer (and tests) to inspect table structure,
update individual cells, and revert pending changes.
"""

from __future__ import annotations

__docformat__ = "google"

import json

import sqlite_utils

from .catalog import get_table_capability
from .core import _SAFE_IDENT_RE, EXCLUDED_TABLES, _connection


def _validate_identifier(name: str, kind: str = "identifier") -> None:
    """Raise ValueError if *name* is not a safe SQL identifier."""
    if not _SAFE_IDENT_RE.match(name):
        msg = f"Invalid SQL {kind}: {name!r}"
        raise ValueError(msg)


def get_tables(
    sdb: sqlite_utils.Database,
) -> list[dict[str, str]]:
    """Return list of non-excluded tables with their type."""
    results: list[dict[str, str]] = []
    for name in sorted(sdb.table_names()):
        if name not in EXCLUDED_TABLES and not name.startswith("sqlite_"):
            results.append({"name": name, "type": "table"})
    for name in sorted(sdb.view_names()):
        if name not in EXCLUDED_TABLES and not name.startswith("sqlite_"):
            results.append({"name": name, "type": "view"})
    return results


def get_primary_keys(sdb: sqlite_utils.Database, table: str) -> list[str]:
    """Return primary key column names for a table."""
    try:
        return sdb.table(table).pks  # pyright: ignore[reportReturnType]
    except Exception:
        return []


def get_column_names(sdb: sqlite_utils.Database, table: str) -> list[str]:
    """Return column names for a table."""
    return [col.name for col in sdb.table(table).columns]  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


def is_editable(sdb: sqlite_utils.Database, table: str) -> bool:
    """Check if a table is editable (has PKs, is a real table, not read-only)."""
    tables = get_tables(sdb)
    table_type = next((t["type"] for t in tables if t["name"] == table), None)
    pk_cols = get_primary_keys(sdb, table)
    capability = get_table_capability(table)
    return table_type == "table" and len(pk_cols) > 0 and capability.editable


def update_cell(
    sdb: sqlite_utils.Database,
    table: str,
    pk: dict[str, object],
    column: str,
    value: object,
) -> dict[str, object]:
    """Update a single cell in a table.

    Returns:
        Dict with ``ok`` and ``old_value`` on success, or ``ok`` and ``error``.
    """
    _validate_identifier(table, "table name")

    pk_cols = get_primary_keys(sdb, table)
    if not pk_cols:
        return {"ok": False, "error": "Table is not editable"}

    valid_cols = get_column_names(sdb, table)
    if column not in valid_cols:
        return {"ok": False, "error": f"Unknown column: {column}"}

    if set(pk.keys()) != set(pk_cols):
        return {"ok": False, "error": f"Expected PK columns: {pk_cols}"}

    where_parts = [f"{col} = ?" for col in pk_cols]
    where_clause = " AND ".join(where_parts)
    pk_values = [pk[col] for col in pk_cols]

    old_row = sdb.execute(
        f"SELECT {column} FROM {table} WHERE {where_clause}",
        pk_values,
    ).fetchone()
    old_value = old_row[0] if old_row else None

    sql_stmt = f"UPDATE {table} SET {column} = ? WHERE {where_clause}"
    sdb.execute(sql_stmt, [value, *pk_values])
    _connection(sdb).commit()

    return {"ok": True, "old_value": old_value}


def revert_changes(
    sdb: sqlite_utils.Database,
    pending: dict[str, dict[str, dict[str, dict[str, object]]]],
) -> int:
    """Revert all pending changes in the DB by restoring baseline values.

    Returns:
        Number of field changes reverted.
    """
    count = sum(len(cols) for rows in pending.values() for cols in rows.values())
    for table, rows in pending.items():
        _validate_identifier(table, "table name")
        pk_cols = get_primary_keys(sdb, table)
        valid_cols = set(get_column_names(sdb, table))
        for pk_key, cols in rows.items():
            pk = {pk_cols[0]: pk_key} if len(pk_cols) == 1 else json.loads(pk_key)
            where_parts = [f"{col} = ?" for col in pk_cols]
            where_clause = " AND ".join(where_parts)
            pk_values = [pk[col] for col in pk_cols]
            for col_name, change in cols.items():
                if col_name not in valid_cols:
                    continue
                sql_stmt = f"UPDATE {table} SET {col_name} = ? WHERE {where_clause}"
                sdb.execute(sql_stmt, [change["baseline"], *pk_values])
    _connection(sdb).commit()
    return count
