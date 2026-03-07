"""Tests for _grid_to_markdown() and _detect_state() — Tier 2A pure function tests."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from nicegui import ui

# ---------------------------------------------------------------------------
# _grid_to_markdown tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_grid():
    """Create a mock AG Grid with configurable options."""

    def _make(col_defs: list, row_data: list) -> ui.aggrid:
        grid = SimpleNamespace(options={"columnDefs": col_defs, "rowData": row_data})
        return grid  # pyright: ignore[reportReturnType]  # ty: ignore[invalid-return-type]

    return _make


def test_markdown_basic(mock_grid):
    """Basic markdown table with headers and rows."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [{"field": "name"}, {"field": "score"}],
        [
            {"name": "Alice", "score": "95"},
            {"name": "Bob", "score": "87"},
        ],
    )
    md = _grid_to_markdown(grid)
    lines = md.strip().split("\n")
    assert len(lines) == 4  # header + separator + 2 rows
    assert "name" in lines[0]
    assert "score" in lines[0]
    assert "---" in lines[1]
    assert "Alice" in lines[2]
    assert "Bob" in lines[3]


def test_markdown_header_names(mock_grid):
    """headerName overrides field name in output."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [
            {"field": "points_possible", "headerName": "Points"},
            {"field": "name", "headerName": "Assignment"},
        ],
        [{"points_possible": "10", "name": "HW1"}],
    )
    md = _grid_to_markdown(grid)
    assert "Points" in md
    assert "Assignment" in md


def test_markdown_hidden_cols_excluded(mock_grid):
    """Hidden columns are excluded from markdown output."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [
            {"field": "canvas_id", "hide": True},
            {"field": "name"},
            {"field": "score"},
        ],
        [{"canvas_id": "1", "name": "HW1", "score": "10"}],
    )
    md = _grid_to_markdown(grid)
    assert "canvas_id" not in md
    assert "name" in md
    assert "score" in md


def test_markdown_grouped_children(mock_grid):
    """Column groups with children are flattened correctly."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [
            {"field": "student"},
            {
                "headerName": "Grades",
                "children": [
                    {"field": "hw1", "headerName": "HW 1"},
                    {"field": "hw2", "headerName": "HW 2"},
                ],
            },
        ],
        [{"student": "Alice", "hw1": "9", "hw2": "18"}],
    )
    md = _grid_to_markdown(grid)
    assert "student" in md
    assert "HW 1" in md
    assert "HW 2" in md
    assert "Alice" in md
    assert "9" in md


def test_markdown_hidden_children(mock_grid):
    """Hidden children within column groups are excluded."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [
            {
                "headerName": "Info",
                "children": [
                    {"field": "id", "hide": True},
                    {"field": "name"},
                ],
            }
        ],
        [{"id": "1", "name": "Alice"}],
    )
    md = _grid_to_markdown(grid)
    assert "id" not in md.split("\n")[0]  # header line
    assert "name" in md


def test_markdown_column_padding(mock_grid):
    """Column widths are padded to the widest value."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [{"field": "x"}],
        [{"x": "short"}, {"x": "a much longer value"}],
    )
    md = _grid_to_markdown(grid)
    lines = md.strip().split("\n")
    # All lines should have consistent pipe positions
    pipe_positions = [line.rindex("|") for line in lines]
    assert len(set(pipe_positions)) == 1


def test_markdown_empty_row_data(mock_grid):
    """Empty row data still produces a valid header + separator."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [{"field": "a"}, {"field": "b"}],
        [],
    )
    md = _grid_to_markdown(grid)
    lines = md.strip().split("\n")
    assert len(lines) == 2  # header + separator only


def test_markdown_missing_field_in_row(mock_grid):
    """Missing fields in row data render as empty string."""
    from cass.viewer.grid import _grid_to_markdown

    grid = mock_grid(
        [{"field": "name"}, {"field": "email"}],
        [{"name": "Alice"}],  # email missing
    )
    md = _grid_to_markdown(grid)
    assert "Alice" in md
    # Should not crash; email cell is empty


# ---------------------------------------------------------------------------
# _detect_state tests
# ---------------------------------------------------------------------------


def test_detect_state_no_config():
    """Returns 'setup' when no config file exists."""
    from cass.viewer.nicegui_app import _detect_state

    with patch("cass.viewer.nicegui_app.config_file_path", return_value=None):
        assert _detect_state() == "setup"


def test_detect_state_config_no_db(tmp_path):
    """Returns 'pull' when config exists but DB file is missing."""
    from cass.viewer.nicegui_app import _detect_state

    cfg = SimpleNamespace(root=tmp_path)
    with (
        patch(
            "cass.viewer.nicegui_app.config_file_path",
            return_value=tmp_path / "cass.toml",
        ),
        patch("cass.db.is_remote", return_value=False),
        patch("cass.config.get_config", return_value=cfg),
    ):
        assert _detect_state() == "pull"


def test_detect_state_config_and_db(tmp_path):
    """Returns 'ready' when config and DB both exist."""
    from cass.viewer.nicegui_app import _detect_state

    # Create the DB file
    db_file = tmp_path / "cass.duckdb"
    db_file.touch()
    cfg = SimpleNamespace(root=tmp_path)
    with (
        patch(
            "cass.viewer.nicegui_app.config_file_path",
            return_value=tmp_path / "cass.toml",
        ),
        patch("cass.db.is_remote", return_value=False),
        patch("cass.config.get_config", return_value=cfg),
        patch("cass.viewer.nicegui_app.DB_FILENAME", "cass.duckdb"),
    ):
        assert _detect_state() == "ready"


def test_detect_state_remote_db():
    """Returns 'ready' for remote DB (no local file check needed)."""
    from cass.viewer.nicegui_app import _detect_state

    with (
        patch(
            "cass.viewer.nicegui_app.config_file_path",
            return_value=Path("/some/cass.toml"),
        ),
        patch("cass.db.is_remote", return_value=True),
    ):
        assert _detect_state() == "ready"
