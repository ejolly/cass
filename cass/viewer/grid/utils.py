"""AG Grid utility functions — search, export, reload, revert, notifications."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any, Literal, cast

from nicegui import ui

from ...db import revert_changes
from ..config import PendingChanges, display_name
from .columns import (
    build_gradebook_view,
    get_table_rows,
)
from .pending import clear_pending_cells

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

_NotifyLevel = Literal["positive", "negative", "warning", "info"]


def notify(text: str, level: _NotifyLevel = "positive") -> None:
    """Show a toast notification in the bottom-left corner."""
    ui.notify(
        text,
        type=level,
        position="bottom-left",
        close_button=True,
    )


# ---------------------------------------------------------------------------
# Grid lookup
# ---------------------------------------------------------------------------


def find_grid(grid_container: dict[str, Any]) -> ui.aggrid | None:
    """Find the AG Grid element inside a container."""
    container = grid_container.get("ref")
    if container is None:
        return None
    for child in container:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(child, ui.aggrid):
            return child
    return None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def apply_search(grid_container: dict[str, Any], search_text: object) -> None:
    """Apply quick filter to the AG Grid in the container."""
    grid = find_grid(grid_container)
    if grid is None:
        return
    text = str(search_text) if search_text else ""
    grid.run_grid_method(  # pyright: ignore[reportUnknownMemberType]
        "setGridOption", "quickFilterText", text
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_csv(grid_container: dict[str, Any]) -> None:
    """Export current grid data as CSV via AG Grid's built-in export."""
    grid = find_grid(grid_container)
    if grid is not None:
        grid.run_grid_method("exportDataAsCsv")  # pyright: ignore[reportUnknownMemberType]


def _grid_to_markdown(grid: ui.aggrid) -> str:
    """Convert AG Grid options to a markdown table string."""
    col_defs = cast(
        list[Any],
        grid.options.get("columnDefs", []),  # pyright: ignore[reportUnknownMemberType]
    )
    row_data = cast(
        list[Any],
        grid.options.get("rowData", []),  # pyright: ignore[reportUnknownMemberType]
    )

    headers: list[str] = []
    fields: list[str] = []
    for col in col_defs:
        children: list[Any] = col.get("children", [])  # pyright: ignore[reportUnknownMemberType]
        if children:
            for child in children:  # pyright: ignore[reportUnknownVariableType]
                if not child.get("hide"):  # pyright: ignore[reportUnknownMemberType]
                    headers.append(str(child.get("headerName", child["field"])))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
                    fields.append(str(child["field"]))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        elif not col.get("hide"):  # pyright: ignore[reportUnknownMemberType]
            headers.append(str(col.get("headerName", col["field"])))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            fields.append(str(col["field"]))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]

    widths = [len(h) for h in headers]
    rows_str: list[list[str]] = []
    for row in row_data:  # pyright: ignore[reportUnknownVariableType]
        cells = [str(row.get(f, "") or "") for f in fields]  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))
        rows_str.append(cells)

    def fmt(cells: list[str]) -> str:
        return (
            "| "
            + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True))
            + " |"
        )

    lines = [
        fmt(headers),
        "| " + " | ".join("-" * w for w in widths) + " |",
        *[fmt(r) for r in rows_str],
    ]
    return "\n".join(lines) + "\n"


def export_markdown(
    grid_container: dict[str, Any],
    current_table: dict[str, str],
) -> None:
    """Export current grid data as a markdown file download."""
    grid = find_grid(grid_container)
    if grid is None:
        return
    title = display_name(current_table["name"])
    md = f"# {title}\n\n{_grid_to_markdown(grid)}"
    filename = f"{current_table['name']}.md"
    ui.download(md.encode(), filename)


# ---------------------------------------------------------------------------
# Reload & Revert
# ---------------------------------------------------------------------------


def reload_current_grid(
    conn: Any,
    grid_container: dict[str, Any],
    table_name: str,
) -> None:
    """Reload the AG Grid with fresh data from the DB."""
    grid = find_grid(grid_container)
    if grid is not None:
        if table_name == "canvas_grades":
            new_rows, _col_defs = build_gradebook_view(conn)
        else:
            new_rows = get_table_rows(conn, table_name)
        grid.options["rowData"] = new_rows  # pyright: ignore[reportUnknownMemberType]
        grid.update()


def revert_pending(
    conn: Any,
    pending: PendingChanges,
    update_pending_display: Any,
    grid_container: dict[str, Any],
    current_table: dict[str, str],
) -> None:
    """Revert all pending changes in the DB and reload the grid."""
    count = revert_changes(conn, pending)
    pending.clear()
    clear_pending_cells()
    update_pending_display()
    reload_current_grid(conn, grid_container, current_table["name"])
    grid = find_grid(grid_container)
    if grid is not None:
        grid.run_grid_method("refreshCells", {"force": True})  # pyright: ignore[reportUnknownMemberType]
    notify(f"Reverted {count} change{'s' if count != 1 else ''}")
