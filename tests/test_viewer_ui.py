"""Proof-of-concept: NiceGUI User-fixture integration tests for the viewer.

These tests use nicegui.testing.User to simulate browser interaction entirely
in Python — no Selenium, no headless Chrome, runs as fast as unit tests.

Run with:
    uv run pytest tests/test_viewer_ui.py -v -p nicegui.testing.user_plugin
"""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Generator

import duckdb
import pytest
from nicegui import ui
from nicegui.testing import User

from cass.viewer.config import display_name, group_tables
from cass.viewer.grid import (
    build_column_defs,
    get_table_rows,
    get_tables,
    is_editable,
)


@pytest.fixture
def ui_conn() -> Generator[duckdb.DuckDBPyConnection]:
    """In-memory DuckDB with a realistic schema for viewer UI tests."""
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('course_name', 'CS 101')")

    conn.execute(
        "CREATE TABLE canvas_assignments ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  points_possible DOUBLE,"
        "  due_at TEXT,"
        "  published BOOLEAN DEFAULT true,"
        "  assignment_group TEXT DEFAULT ''"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_assignments VALUES "
        "(1, 'Homework 1', 10.0, '2026-02-01T23:59', true, 'Assignments'),"
        "(2, 'Homework 2', 20.0, '2026-02-15T23:59', true, 'Assignments')"
    )

    conn.execute(
        "CREATE TABLE canvas_grades ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  score DOUBLE,"
        "  posted_grade TEXT NOT NULL DEFAULT '',"
        "  updated_at TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_grades VALUES "
        "(100, 1, 9.0, '9', '2026-02-02T10:00'),"
        "(100, 2, 18.0, '18', '2026-02-16T10:00'),"
        "(200, 1, 7.0, '7', '2026-02-02T11:00')"
    )

    conn.execute(
        "CREATE TABLE canvas_students ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  sortable_name TEXT,"
        "  email TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_students VALUES "
        "(100, 'Smith, Alice', 'alice@test.edu'),"
        "(200, 'Jones, Bob', 'bob@test.edu')"
    )

    conn.execute(
        "CREATE TABLE canvas_submissions ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  submitted_at TEXT,"
        "  score DOUBLE,"
        "  workflow_state TEXT DEFAULT 'graded',"
        "  late BOOLEAN DEFAULT false,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_submissions VALUES "
        "(100, 1, '2026-02-01T12:00', 9.0, 'graded', false),"
        "(200, 1, '2026-02-02T14:00', 7.0, 'graded', true)"
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Test 1: Render a simple page with table data, verify elements appear
# ---------------------------------------------------------------------------


async def test_table_list_renders(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Tables from the DB appear as labels on the page."""
    tables = get_tables(ui_conn)

    @ui.page("/test")
    def page() -> None:
        with ui.column():
            for t in tables:
                ui.label(display_name(t["name"])).mark(f"table-{t['name']}")

    await user.open("/test")
    await user.should_see("Assignments")
    await user.should_see("Gradebook")  # canvas_grades -> "Gradebook"
    await user.should_see("Submissions")


# ---------------------------------------------------------------------------
# Test 2: Render an AG Grid with column defs and row data, verify content
# ---------------------------------------------------------------------------


async def test_aggrid_renders_rows(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """AG Grid renders with correct row data from the DB."""
    table_name = "canvas_assignments"
    rows = get_table_rows(ui_conn, table_name)
    col_defs = build_column_defs(ui_conn, table_name)

    @ui.page("/test-grid")
    def page() -> None:
        ui.label(f"{len(rows)} rows").mark("row-count")
        ui.aggrid(
            {
                "columnDefs": col_defs,
                "rowData": rows,
            }
        )

    await user.open("/test-grid")
    await user.should_see(content="2 rows")


# ---------------------------------------------------------------------------
# Test 3: Sidebar navigation pattern — clicking loads different content
# ---------------------------------------------------------------------------


async def test_sidebar_navigation(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Clicking a sidebar item updates the main content area."""
    tables = get_tables(ui_conn)
    content_label: dict[str, ui.label | None] = {"ref": None}

    @ui.page("/test-nav")
    def page() -> None:
        with ui.row().classes("w-full"):
            # Sidebar
            with ui.column().mark("sidebar"):
                for t in tables:
                    ui.button(
                        display_name(t["name"]),
                        on_click=lambda _, n=t["name"]: _load(n),
                    ).mark(f"nav-{t['name']}")

            # Content
            with ui.column().mark("content"):
                lbl = ui.label("Select a table").mark("content-label")
                content_label["ref"] = lbl

        def _load(name: str) -> None:
            lbl = content_label["ref"]
            if lbl is not None:
                rows = get_table_rows(ui_conn, name)
                lbl.text = f"Showing {name}: {len(rows)} rows"

    await user.open("/test-nav")
    await user.should_see("Select a table")

    # Click the assignments nav button
    user.find(marker="nav-canvas_assignments").click()
    await user.should_see("Showing canvas_assignments: 2 rows")

    # Click grades
    user.find(marker="nav-canvas_grades").click()
    await user.should_see("Showing canvas_grades: 3 rows")


# ---------------------------------------------------------------------------
# Test 4: Editable vs read-only badge rendering
# ---------------------------------------------------------------------------


async def test_editable_badges(user: User, ui_conn: duckdb.DuckDBPyConnection) -> None:
    """Editable tables show an 'editable' badge; read-only show 'view-only'."""
    tables = get_tables(ui_conn)

    @ui.page("/test-badges")
    def page() -> None:
        for t in tables:
            name = t["name"]
            editable = is_editable(ui_conn, name)
            with ui.row().mark(f"row-{name}"):
                ui.label(display_name(name))
                ui.badge("editable" if editable else "view-only").mark(f"badge-{name}")

    await user.open("/test-badges")
    # canvas_assignments is editable, canvas_submissions is read-only
    await user.should_see(marker="badge-canvas_assignments", content="editable")
    await user.should_see(marker="badge-canvas_submissions", content="view-only")


# ---------------------------------------------------------------------------
# Test 5: Table grouping renders correctly
# ---------------------------------------------------------------------------


async def test_grouped_sidebar(user: User, ui_conn: duckdb.DuckDBPyConnection) -> None:
    """Tables are grouped by prefix in the sidebar."""
    tables = get_tables(ui_conn)
    groups = group_tables(tables)

    @ui.page("/test-groups")
    def page() -> None:
        for group in groups:
            with ui.column().mark(f"group-{group['label']}"):
                ui.label(group["label"]).classes("font-bold")
                for t in group["items"]:
                    ui.label(display_name(t["name"]))

    await user.open("/test-groups")
    await user.should_see("Canvas LMS")
