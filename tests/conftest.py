"""Shared fixtures for cass tests."""

import duckdb
import pytest

from cass import db


@pytest.fixture
def db_conn(monkeypatch):
    """Fresh in-memory DuckDB with schema initialized."""
    conn = duckdb.connect(":memory:")
    db._init_schema(conn)
    monkeypatch.setattr(db, "_conn", conn)
    yield conn
    conn.close()
    monkeypatch.setattr(db, "_conn", None)


@pytest.fixture
def project_dir(tmp_path):
    """Temp directory with a minimal cass.toml."""
    toml = tmp_path / "cass.toml"
    toml.write_text(
        '[classroom]\nid = 42\norg = "test-org"\n\n'
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    return tmp_path
