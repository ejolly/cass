"""Shared fixtures for cass tests."""

import duckdb
import pytest

from cass import db
from tests.seed import seed


@pytest.fixture
def db_conn(monkeypatch):
    """Fresh in-memory DuckDB with schema initialized."""
    conn = duckdb.connect(":memory:")
    db.init_schema(conn)
    monkeypatch.setattr(db, "_conn", conn)
    yield conn
    conn.close()
    monkeypatch.setattr(db, "_conn", None)


@pytest.fixture
def populated_db(monkeypatch):
    """In-memory DuckDB populated with anonymized realistic test data.

    Contains 15 Canvas students, 18 GH students (2 excluded, 1 unmatched),
    5 Canvas + 8 GH assignments, 75 Canvas grades/submissions, 141 GH
    submissions/grades, and synced shadow tables.
    """
    conn = duckdb.connect(":memory:")
    db.init_schema(conn)
    seed(conn)
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
