"""API response cache — separate DuckDB file to keep the main DB lean."""

from __future__ import annotations

__docformat__ = "google"

import time

import duckdb

from .config import get_config

CACHE_FILENAME = ".cass_cache.duckdb"

_conn: duckdb.DuckDBPyConnection | None = None


def cache_path() -> str:
    return str(get_config().root / CACHE_FILENAME)


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is not None:
        return _conn
    _conn = duckdb.connect(cache_path())
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            endpoint TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            fetched_at DOUBLE NOT NULL
        )
    """)
    return _conn


def reset() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def cache_load(key: str, ttl_hours: float = 6) -> str | None:
    """Return cached JSON string if fresh, else None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT data, fetched_at FROM api_cache WHERE endpoint = ?", [key]
    ).fetchone()
    if row is None:
        return None
    age_hours = (time.time() - row[1]) / 3600
    if age_hours > ttl_hours:
        return None
    return row[0]


def cache_save(key: str, data: str) -> None:
    """Write JSON string to cache."""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (endpoint, data, fetched_at) "
        "VALUES (?, ?, ?)",
        [key, data, time.time()],
    )


def cache_clear() -> None:
    conn = get_conn()
    conn.execute("DELETE FROM api_cache")


def cache_count() -> int:
    try:
        conn = get_conn()
        row = conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def cache_size_kb() -> float:
    """Return the cache file size in KB."""
    from pathlib import Path

    p = Path(cache_path())
    return p.stat().st_size / 1024 if p.exists() else 0.0


def cache_list() -> list[tuple[str, float]]:
    conn = get_conn()
    return conn.execute(
        "SELECT endpoint, fetched_at FROM api_cache ORDER BY fetched_at DESC"
    ).fetchall()
