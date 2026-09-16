"""Shared fixtures for cass tests."""

import os
import shutil
from pathlib import Path

import pytest
import sqlite_utils

from cass import db
from cass.db.core import _db  # noqa: F401 — needed for monkeypatch target

# Rich reads the terminal width at console creation; pin it so CLI output
# assertions do not depend on the runner's terminal.
os.environ.setdefault("COLUMNS", "200")

_TESTDB = Path(__file__).parent / "testdb" / "cass.db"


@pytest.fixture
def db_conn(monkeypatch):
    """Fresh in-memory SQLite with schema initialized."""
    sdb = sqlite_utils.Database(memory=True)
    db.init_schema(sdb)
    monkeypatch.setattr("cass.db.core._db", sdb)
    monkeypatch.setattr("cass.db.core._db_path", None)
    return sdb


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    """Writable copy of the real pulled snapshot. Skip if absent."""
    if not _TESTDB.exists():
        pytest.skip("No test snapshot — run 'uv run poe seed-testdb'")
    copy = tmp_path / "cass.db"
    shutil.copy2(_TESTDB, copy)
    sdb = sqlite_utils.Database(str(copy))
    monkeypatch.setattr("cass.db.core._db", sdb)
    monkeypatch.setattr("cass.db.core._db_path", None)
    return sdb


@pytest.fixture
def project_dir(tmp_path):
    """Temp directory with a minimal cass.toml."""
    toml = tmp_path / "cass.toml"
    toml.write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    return tmp_path
