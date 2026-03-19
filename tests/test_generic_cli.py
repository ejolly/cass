"""TDD tests for generic view CLI argument and routing."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def duckdb_file(tmp_path: Path) -> Path:
    """Create a small DuckDB file."""
    import duckdb

    fp = tmp_path / "test.duckdb"
    con = duckdb.connect(str(fp))
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    con.execute("INSERT INTO t VALUES (1, 'hello')")
    con.close()
    return fp


class TestViewCommandArgs:
    def test_view_nonexistent_file_exits(self) -> None:
        from cass.cli import app

        result = runner.invoke(app, ["view", "/tmp/nope.duckdb"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or result.exit_code != 0

    def test_view_unsupported_extension_exits(self, tmp_path: Path) -> None:
        from cass.cli import app

        fp = tmp_path / "data.csv"
        fp.write_text("a,b\n1,2\n")
        result = runner.invoke(app, ["view", str(fp)])
        assert result.exit_code != 0

    def test_view_accepts_duckdb_suffix(self, duckdb_file: Path) -> None:
        """The CLI should accept .duckdb files without error.

        We can't test the full server start (it blocks), so we mock it.
        """
        from unittest.mock import patch

        from cass.cli import app

        with patch("cass.viewer.nicegui_app.start_nicegui_server") as mock_start:
            result = runner.invoke(app, ["view", str(duckdb_file)])
            assert result.exit_code == 0
            mock_start.assert_called_once()
            call_kwargs = mock_start.call_args
            assert call_kwargs.kwargs.get("generic_file") is not None
