"""TDD tests for GenericViewerPage — generic DB browser viewer."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User


@pytest.fixture
def duckdb_file(tmp_path: Path) -> Path:
    """Create a DuckDB file with test data."""
    import duckdb

    fp = tmp_path / "test.duckdb"
    con = duckdb.connect(str(fp))
    con.execute(
        "CREATE TABLE students (id INTEGER PRIMARY KEY, name VARCHAR, gpa DOUBLE)"
    )
    con.execute("INSERT INTO students VALUES (1, 'Alice', 3.8), (2, 'Bob', 3.2)")
    con.execute("CREATE TABLE courses (code VARCHAR PRIMARY KEY, title VARCHAR)")
    con.execute(
        "INSERT INTO courses VALUES ('CS101', 'Intro CS'), ('MA201', 'Linear Algebra')"
    )
    con.close()
    return fp


@pytest.fixture
def sqlite_file(tmp_path: Path) -> Path:
    """Create a SQLite file with test data."""
    import sqlite3

    fp = tmp_path / "test.db"
    con = sqlite3.connect(str(fp))
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT, price REAL)")
    con.execute("INSERT INTO items VALUES (1, 'Widget', 9.99), (2, 'Gadget', 19.99)")
    con.commit()
    con.close()
    return fp


class TestGenericViewerPage:
    async def test_page_renders_with_duckdb(
        self, user: User, duckdb_file: Path
    ) -> None:
        from cass.db.ibis_adapter import connect_file
        from cass.viewer.generic_page import GenericViewerPage

        con = connect_file(duckdb_file)

        @ui.page("/test-generic-duckdb")
        def page() -> None:
            GenericViewerPage(con, duckdb_file)

        await user.open("/test-generic-duckdb")
        await user.should_see(duckdb_file.name)

    async def test_page_shows_table_list(self, user: User, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file
        from cass.viewer.generic_page import GenericViewerPage

        con = connect_file(duckdb_file)

        @ui.page("/test-generic-tables")
        def page() -> None:
            GenericViewerPage(con, duckdb_file)

        await user.open("/test-generic-tables")
        await user.should_see("students")
        await user.should_see("courses")

    async def test_page_renders_with_sqlite(
        self, user: User, sqlite_file: Path
    ) -> None:
        from cass.db.ibis_adapter import connect_file
        from cass.viewer.generic_page import GenericViewerPage

        con = connect_file(sqlite_file)

        @ui.page("/test-generic-sqlite")
        def page() -> None:
            GenericViewerPage(con, sqlite_file)

        await user.open("/test-generic-sqlite")
        await user.should_see(sqlite_file.name)
        await user.should_see("items")
