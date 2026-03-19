"""TDD tests for ibis_adapter — generic DB viewer backend."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

import pytest


@pytest.fixture
def duckdb_file(tmp_path: Path) -> Path:
    """Create a small DuckDB file with two tables."""
    import duckdb

    fp = tmp_path / "test.duckdb"
    con = duckdb.connect(str(fp))
    con.execute(
        "CREATE TABLE students (id INTEGER PRIMARY KEY, name VARCHAR, gpa DOUBLE)"
    )
    con.execute("INSERT INTO students VALUES (1, 'Alice', 3.8), (2, 'Bob', 3.2)")
    con.execute(
        "CREATE TABLE courses "
        "(code VARCHAR PRIMARY KEY, title VARCHAR, credits INTEGER)"
    )
    con.execute(
        "INSERT INTO courses VALUES "
        "('CS101', 'Intro CS', 3), ('MA201', 'Linear Algebra', 4)"
    )
    con.close()
    return fp


@pytest.fixture
def sqlite_file(tmp_path: Path) -> Path:
    """Create a small SQLite file with two tables."""
    import sqlite3

    fp = tmp_path / "test.db"
    con = sqlite3.connect(str(fp))
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT, price REAL)")
    con.execute("INSERT INTO items VALUES (1, 'Widget', 9.99), (2, 'Gadget', 19.99)")
    con.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO tags VALUES (1, 'sale'), (2, 'new')")
    con.commit()
    con.close()
    return fp


# ── connect_file ──────────────────────────────────────────────────────


class TestConnectFile:
    def test_connect_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file

        con = connect_file(duckdb_file)
        assert con is not None
        assert "students" in con.list_tables()

    def test_connect_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file

        con = connect_file(sqlite_file)
        assert con is not None
        assert "items" in con.list_tables()

    def test_connect_nonexistent_raises(self, tmp_path: Path) -> None:
        from cass.db.ibis_adapter import connect_file

        with pytest.raises(SystemExit):
            connect_file(tmp_path / "nope.duckdb")

    def test_connect_unsupported_suffix_raises(self, tmp_path: Path) -> None:
        from cass.db.ibis_adapter import connect_file

        fp = tmp_path / "data.csv"
        fp.write_text("a,b\n1,2\n")
        with pytest.raises(SystemExit):
            connect_file(fp)


# ── list_tables ───────────────────────────────────────────────────────


class TestListTables:
    def test_list_tables_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, list_tables

        con = connect_file(duckdb_file)
        tables = list_tables(con)
        names = [t["name"] for t in tables]
        assert "students" in names
        assert "courses" in names
        assert all(t["type"] == "table" for t in tables)

    def test_list_tables_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, list_tables

        con = connect_file(sqlite_file)
        tables = list_tables(con)
        names = [t["name"] for t in tables]
        assert "items" in names
        assert "tags" in names


# ── get_schema ────────────────────────────────────────────────────────


class TestGetSchema:
    def test_schema_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_schema

        con = connect_file(duckdb_file)
        schema = get_schema(con, "students")
        col_names = [s[0] for s in schema]
        assert "id" in col_names
        assert "name" in col_names
        assert "gpa" in col_names
        # Types should be strings
        assert all(isinstance(s[1], str) for s in schema)

    def test_schema_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_schema

        con = connect_file(sqlite_file)
        schema = get_schema(con, "items")
        col_names = [s[0] for s in schema]
        assert "id" in col_names
        assert "label" in col_names
        assert "price" in col_names


# ── get_primary_keys ──────────────────────────────────────────────────


class TestGetPrimaryKeys:
    def test_pk_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_primary_keys

        con = connect_file(duckdb_file)
        pks = get_primary_keys(con, "students")
        assert pks == ["id"]

    def test_pk_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_primary_keys

        con = connect_file(sqlite_file)
        pks = get_primary_keys(con, "items")
        assert pks == ["id"]

    def test_no_pk_returns_empty(self, tmp_path: Path) -> None:
        """Table without explicit PK should return empty list."""
        import duckdb

        fp = tmp_path / "nopk.duckdb"
        con = duckdb.connect(str(fp))
        con.execute("CREATE TABLE loose (a INTEGER, b TEXT)")
        con.execute("INSERT INTO loose VALUES (1, 'x')")
        con.close()

        from cass.db.ibis_adapter import connect_file, get_primary_keys

        ib = connect_file(fp)
        pks = get_primary_keys(ib, "loose")
        assert pks == []


# ── get_rows ──────────────────────────────────────────────────────────


class TestGetRows:
    def test_rows_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_rows

        con = connect_file(duckdb_file)
        rows = get_rows(con, "students")
        assert len(rows) == 2
        assert all(isinstance(r, dict) for r in rows)
        names = {r["name"] for r in rows}
        assert names == {"Alice", "Bob"}

    def test_rows_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_rows

        con = connect_file(sqlite_file)
        rows = get_rows(con, "items")
        assert len(rows) == 2

    def test_rows_limit(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_rows

        con = connect_file(duckdb_file)
        rows = get_rows(con, "students", limit=1)
        assert len(rows) == 1


# ── get_row_count ─────────────────────────────────────────────────────


class TestGetRowCount:
    def test_count_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_row_count

        con = connect_file(duckdb_file)
        assert get_row_count(con, "students") == 2

    def test_count_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_row_count

        con = connect_file(sqlite_file)
        assert get_row_count(con, "items") == 2


# ── update_cell ───────────────────────────────────────────────────────


class TestUpdateCell:
    def test_update_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_rows, update_cell

        con = connect_file(duckdb_file)
        result = update_cell(con, "students", "id", 1, "name", "Alicia")
        assert result["ok"] is True
        rows = get_rows(con, "students")
        alice_row = next(r for r in rows if r["id"] == 1)
        assert alice_row["name"] == "Alicia"

    def test_update_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, get_rows, update_cell

        con = connect_file(sqlite_file)
        result = update_cell(con, "items", "id", 1, "label", "Doohickey")
        assert result["ok"] is True
        rows = get_rows(con, "items")
        item = next(r for r in rows if r["id"] == 1)
        assert item["label"] == "Doohickey"


# ── run_sql ───────────────────────────────────────────────────────────


class TestRunSql:
    def test_select_duckdb(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, run_sql

        con = connect_file(duckdb_file)
        columns, rows = run_sql(con, "SELECT name, gpa FROM students ORDER BY name")
        assert "name" in columns
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"

    def test_select_sqlite(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import connect_file, run_sql

        con = connect_file(sqlite_file)
        columns, rows = run_sql(con, "SELECT label FROM items ORDER BY label")
        assert "label" in columns
        assert len(rows) == 2


# ── backend_name ──────────────────────────────────────────────────────


class TestBackendName:
    def test_duckdb_name(self, duckdb_file: Path) -> None:
        from cass.db.ibis_adapter import backend_name, connect_file

        con = connect_file(duckdb_file)
        assert backend_name(con) == "duckdb"

    def test_sqlite_name(self, sqlite_file: Path) -> None:
        from cass.db.ibis_adapter import backend_name, connect_file

        con = connect_file(sqlite_file)
        assert backend_name(con) == "sqlite"
