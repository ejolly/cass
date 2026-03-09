"""API response cache — separate SQLite file to keep the main DB lean."""

from __future__ import annotations

__docformat__ = "google"

import time

import sqlite_utils

from ..actions.config import get_config

CACHE_FILENAME = ".cass_cache.db"

_db: sqlite_utils.Database | None = None


def cache_path() -> str:
    return str(get_config().root / CACHE_FILENAME)


def _table(db: sqlite_utils.Database) -> sqlite_utils.db.Table | sqlite_utils.db.View:
    """Return the api_cache table, creating it on first access."""
    tbl = db.table("api_cache")
    if "api_cache" not in db.table_names():
        tbl.create(  # pyright: ignore[reportUnknownMemberType]
            {"endpoint": str, "data": str, "fetched_at": float},
            pk="endpoint",
            not_null={"endpoint", "data", "fetched_at"},
        )
    return tbl


def get_conn() -> sqlite_utils.Database:
    global _db
    if _db is not None:
        return _db
    _db = sqlite_utils.Database(cache_path())
    _table(_db)  # ensure table exists
    return _db


def reset() -> None:
    global _db
    if _db is not None:
        conn = _db.conn
        if conn is not None:
            conn.close()
        _db = None


def cache_load(key: str, ttl_hours: float = 6) -> str | None:
    """Return cached JSON string if fresh, else None."""
    db = get_conn()
    try:
        row = _table(db).get(key)  # pyright: ignore[reportUnknownMemberType]
    except sqlite_utils.db.NotFoundError:
        return None
    age_hours = (time.time() - row["fetched_at"]) / 3600  # pyright: ignore[reportOperatorIssue]
    if age_hours > ttl_hours:
        return None
    return row["data"]  # pyright: ignore[reportReturnType]


def cache_save(key: str, data: str) -> None:
    """Write JSON string to cache."""
    db = get_conn()
    _table(db).insert(  # pyright: ignore[reportUnknownMemberType]
        {"endpoint": key, "data": data, "fetched_at": time.time()},
        pk="endpoint",
        replace=True,
    )


def cache_clear() -> None:
    db = get_conn()
    _table(db).delete_where()  # pyright: ignore[reportUnknownMemberType]


def cache_count() -> int:
    try:
        db = get_conn()
        return _table(db).count
    except Exception:
        return 0


def cache_size_kb() -> float:
    """Return the cache file size in KB."""
    from pathlib import Path

    p = Path(cache_path())
    return p.stat().st_size / 1024 if p.exists() else 0.0


def cache_list() -> list[tuple[str, float]]:
    db = get_conn()
    return [
        (row["endpoint"], row["fetched_at"])
        for row in _table(db).rows_where(order_by="-fetched_at")  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    ]
