"""NiceGUI User-fixture integration tests for the viewer.

Uses nicegui.testing.User to simulate browser interaction entirely in Python —
no Selenium, no headless Chrome, runs as fast as unit tests.
"""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Generator
from types import SimpleNamespace

import duckdb
import pytest
from nicegui import ui
from nicegui.testing import User

from cass.db import get_primary_keys, get_tables, is_editable, update_cell
from cass.viewer.actions import pending_count, track_change
from cass.viewer.config import DEV_TABLES, PendingChanges, display_name, group_tables
from cass.viewer.grid import (
    _grid_to_markdown,
    attach_edit_handler,
    attach_gradebook_edit_handler,
    build_column_defs,
    build_gradebook_view,
    find_grid,
    get_table_rows,
    reload_current_grid,
    revert_pending,
    row_id_js,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_listener(element: ui.element, event_type: str):
    """Find an event listener by type on a NiceGUI element."""
    for listener in element._event_listeners.values():  # pyright: ignore[reportAttributeAccessIssue]
        if listener.type == event_type:
            return listener.handler  # pyright: ignore[reportUnknownMemberType]
    msg = f"No listener for {event_type!r}"
    raise LookupError(msg)


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
        "  submitted_at TIMESTAMP,"
        "  score DOUBLE,"
        "  workflow_state TEXT DEFAULT 'graded',"
        "  late BOOLEAN DEFAULT false,"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_submissions VALUES "
        "(100, 1, '2026-02-01 12:00:00', 9.0, 'graded', false),"
        "(200, 1, '2026-02-02 14:00:00', 7.0, 'graded', true)"
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


# ===========================================================================
# Tier 1 — Core functionality integration tests
# ===========================================================================


# ---------------------------------------------------------------------------
# Edit handler round-trip: edit cell → DB updated → pending tracked
# ---------------------------------------------------------------------------


async def test_edit_handler_updates_db_and_pending(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Editing a cell via the grid handler updates DB and tracks pending."""
    table = "canvas_assignments"
    pk_cols = get_primary_keys(ui_conn, table)
    rows = get_table_rows(ui_conn, table)
    col_defs = build_column_defs(ui_conn, table)
    pending: PendingChanges = {}
    badge_label: dict[str, ui.label | None] = {"ref": None}

    def refresh_badge() -> None:
        lbl = badge_label["ref"]
        if lbl is not None:
            count = pending_count(pending)
            lbl.text = f"{count} pending" if count else "Synchronized"

    @ui.page("/test-edit")
    def page() -> None:
        bl = ui.label("Synchronized").mark("badge")
        badge_label["ref"] = bl
        grid = ui.aggrid(
            {
                "columnDefs": col_defs,
                "rowData": rows,
                ":getRowId": f"(params) => {row_id_js(pk_cols)}",
            }
        ).mark("grid")
        attach_edit_handler(grid, ui_conn, table, pk_cols, pending, refresh_badge)

        # Button that simulates a cell edit inside the NiceGUI context
        def _simulate_edit() -> None:
            handler = _find_listener(grid, "cellValueChanged")
            handler(
                SimpleNamespace(
                    args={
                        "colDef": {"field": "name"},
                        "value": "Homework 1 Updated",
                        "data": {
                            "canvas_id": 1,
                            "name": "Homework 1 Updated",
                            "assignment_group": "Assignments",
                            "points_possible": 10.0,
                            "due_at": "2026-02-01T23:59",
                            "published": True,
                        },
                    }
                )
            )

        ui.button("Simulate Edit", on_click=_simulate_edit).mark("sim-edit")

    await user.open("/test-edit")
    await user.should_see(content="Synchronized")

    user.find(marker="sim-edit").click()

    # DB should be updated
    result = ui_conn.execute(
        "SELECT name FROM canvas_assignments WHERE canvas_id = 1"
    ).fetchone()
    assert result is not None
    assert result[0] == "Homework 1 Updated"

    # Pending change should be tracked (name is in CANVAS_PUSHABLE)
    assert pending_count(pending) == 1
    assert "canvas_assignments" in pending


async def test_edit_handler_non_pushable_no_pending(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Editing a non-pushable column updates DB but does NOT track pending."""
    table = "canvas_assignments"
    pk_cols = get_primary_keys(ui_conn, table)
    rows = get_table_rows(ui_conn, table)
    col_defs = build_column_defs(ui_conn, table)
    pending: PendingChanges = {}

    @ui.page("/test-edit-nopush")
    def page() -> None:
        grid = ui.aggrid(
            {
                "columnDefs": col_defs,
                "rowData": rows,
                ":getRowId": f"(params) => {row_id_js(pk_cols)}",
            }
        ).mark("grid")
        attach_edit_handler(grid, ui_conn, table, pk_cols, pending, lambda: None)

        def _simulate_edit() -> None:
            handler = _find_listener(grid, "cellValueChanged")
            handler(
                SimpleNamespace(
                    args={
                        "colDef": {"field": "assignment_group"},
                        "value": "Labs",
                        "data": {
                            "canvas_id": 1,
                            "assignment_group": "Labs",
                            "name": "Homework 1",
                            "points_possible": 10.0,
                            "due_at": "2026-02-01T23:59",
                            "published": True,
                        },
                    }
                )
            )

        ui.button("Simulate Edit", on_click=_simulate_edit).mark("sim-edit")

    await user.open("/test-edit-nopush")

    user.find(marker="sim-edit").click()

    # DB updated
    result = ui_conn.execute(
        "SELECT assignment_group FROM canvas_assignments WHERE canvas_id = 1"
    ).fetchone()
    assert result is not None
    assert result[0] == "Labs"

    # No pending change (not pushable)
    assert pending_count(pending) == 0


# ---------------------------------------------------------------------------
# Gradebook pivot rendering
# ---------------------------------------------------------------------------


async def test_canvas_gradebook_renders(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Canvas gradebook renders students x assignments pivot."""
    row_data, col_defs = build_gradebook_view(ui_conn)

    @ui.page("/test-gb")
    def page() -> None:
        ui.label(f"{len(row_data)} students").mark("student-count")
        # Count assignment columns (fields starting with _a)
        n_assignments = sum(
            1
            for c in col_defs
            if c.get("field", "").startswith("_a")
            or any(ch.get("field", "").startswith("_a") for ch in c.get("children", []))
        )
        ui.label(f"{n_assignments} assignments").mark("assignment-count")
        ui.aggrid({"columnDefs": col_defs, "rowData": row_data}).mark("gb-grid")

    await user.open("/test-gb")
    await user.should_see(content="2 students")
    await user.should_see(content="2 assignments")

    # Verify row data structure
    assert len(row_data) == 2
    # Students sorted by sortable_name: Jones before Smith
    assert row_data[0]["_student_name"] == "Jones, Bob"
    assert row_data[1]["_student_name"] == "Smith, Alice"
    # Grades populated
    assert row_data[1]["_a1"] == "9"  # Alice, HW1
    assert row_data[1]["_a2"] == "18"  # Alice, HW2
    assert row_data[0]["_a1"] == "7"  # Bob, HW1
    assert row_data[0]["_a2"] == ""  # Bob, HW2 — no grade


# ---------------------------------------------------------------------------
# Pending badge state transitions
# ---------------------------------------------------------------------------


async def test_pending_badge_updates_on_edit(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Badge changes from 'Synchronized' to 'N pending' after edit."""
    pending: PendingChanges = {}
    badge_ref: dict[str, ui.label | None] = {"ref": None}

    def refresh() -> None:
        lbl = badge_ref["ref"]
        if lbl is not None:
            count = pending_count(pending)
            lbl.text = f"{count} pending" if count else "Synchronized"

    @ui.page("/test-badge")
    def page() -> None:
        badge_ref["ref"] = ui.label("Synchronized").mark("status")
        ui.button(
            "Edit grade",
            on_click=lambda: _do_edit(),
        ).mark("edit-btn")
        ui.button(
            "Edit another",
            on_click=lambda: _do_edit2(),
        ).mark("edit-btn2")

    def _do_edit() -> None:
        update_cell(
            ui_conn,
            "canvas_grades",
            {"canvas_user_id": 100, "canvas_assignment_id": 1},
            "posted_grade",
            "10",
        )
        track_change(
            pending,
            "canvas_grades",
            {"canvas_user_id": 100, "canvas_assignment_id": 1},
            "posted_grade",
            "9",
            "10",
        )
        refresh()

    def _do_edit2() -> None:
        update_cell(
            ui_conn,
            "canvas_grades",
            {"canvas_user_id": 200, "canvas_assignment_id": 1},
            "posted_grade",
            "8",
        )
        track_change(
            pending,
            "canvas_grades",
            {"canvas_user_id": 200, "canvas_assignment_id": 1},
            "posted_grade",
            "7",
            "8",
        )
        refresh()

    await user.open("/test-badge")
    await user.should_see(content="Synchronized")

    user.find(marker="edit-btn").click()
    await user.should_see(content="1 pending")

    user.find(marker="edit-btn2").click()
    await user.should_see(content="2 pending")


# ---------------------------------------------------------------------------
# Revert pending — restores DB and clears pending state
# ---------------------------------------------------------------------------


async def test_revert_pending_restores_db(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Reverting pending changes restores original DB values."""
    table = "canvas_assignments"
    pk_cols = get_primary_keys(ui_conn, table)
    pending: PendingChanges = {}

    # Make an edit
    update_cell(ui_conn, table, {"canvas_id": 1}, "name", "Changed Name")
    track_change(pending, table, {"canvas_id": 1}, "name", "Homework 1", "Changed Name")
    assert pending_count(pending) == 1

    # Verify DB has new value
    row = ui_conn.execute(
        "SELECT name FROM canvas_assignments WHERE canvas_id = 1"
    ).fetchone()
    assert row is not None
    assert row[0] == "Changed Name"

    badge_ref: dict[str, ui.label | None] = {"ref": None}
    grid_container: dict[str, object] = {"ref": None}
    current_table: dict[str, str] = {"name": table}

    def refresh() -> None:
        lbl = badge_ref["ref"]
        if lbl is not None:
            count = pending_count(pending)
            lbl.text = f"{count} pending" if count else "Synchronized"

    @ui.page("/test-revert")
    def page() -> None:
        badge_ref["ref"] = ui.label("1 pending").mark("status")
        container = ui.element("div").mark("grid-container")
        grid_container["ref"] = container
        with container:
            rows = get_table_rows(ui_conn, table)
            col_defs = build_column_defs(ui_conn, table)
            ui.aggrid(
                {
                    "columnDefs": col_defs,
                    "rowData": rows,
                    ":getRowId": f"(params) => {row_id_js(pk_cols)}",
                }
            )
        ui.button(
            "Revert",
            on_click=lambda: revert_pending(
                ui_conn, pending, refresh, grid_container, current_table
            ),
        ).mark("revert-btn")

    await user.open("/test-revert")
    await user.should_see(content="1 pending")

    user.find(marker="revert-btn").click()
    await user.should_see(content="Synchronized")

    # Pending should be empty
    assert pending_count(pending) == 0

    # DB should have original value
    row = ui_conn.execute(
        "SELECT name FROM canvas_assignments WHERE canvas_id = 1"
    ).fetchone()
    assert row is not None
    assert row[0] == "Homework 1"


# ---------------------------------------------------------------------------
# Column defs correctness — editors, hidden columns, display names
# ---------------------------------------------------------------------------


async def test_column_defs_editable_table(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Editable table columns get proper editors; hidden cols are hidden."""
    col_defs = build_column_defs(ui_conn, "canvas_assignments")

    # Collect all visible and hidden fields
    visible = [c for c in col_defs if not c.get("hide")]
    hidden = [c for c in col_defs if c.get("hide")]

    # canvas_id should be hidden (per HIDDEN_COLUMNS config)
    hidden_fields = [c["field"] for c in hidden]
    assert "canvas_id" in hidden_fields

    # Editable columns should have editors
    editable_cols = [c for c in visible if c.get("editable")]
    editable_fields = [c["field"] for c in editable_cols]
    assert "name" in editable_fields
    assert "points_possible" in editable_fields
    assert "published" in editable_fields
    assert "due_at" in editable_fields

    # points_possible should have number editor
    pts_col = next(c for c in editable_cols if c["field"] == "points_possible")
    assert pts_col.get("cellEditor") == "agNumberCellEditor"

    # published should have checkbox editor
    pub_col = next(c for c in editable_cols if c["field"] == "published")
    assert pub_col.get("cellEditor") == "agCheckboxCellEditor"

    # due_at is TEXT in schema — editable but no special editor
    due_col = next(c for c in editable_cols if c["field"] == "due_at")
    assert due_col.get("editable") is True


async def test_column_defs_readonly_table(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Read-only table columns should NOT have editors."""
    col_defs = build_column_defs(ui_conn, "canvas_submissions")

    editable_cols = [c for c in col_defs if c.get("editable")]
    assert len(editable_cols) == 0


async def test_column_display_names(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Column defs use human-readable display names from config."""
    col_defs = build_column_defs(ui_conn, "canvas_assignments")

    by_field = {c["field"]: c for c in col_defs}
    assert by_field["assignment_group"].get("headerName") == "Group"
    assert by_field["points_possible"].get("headerName") == "Points"
    assert by_field["due_at"].get("headerName") == "Deadline"


# ---------------------------------------------------------------------------
# Gradebook edit handler round-trip
# ---------------------------------------------------------------------------


async def test_gradebook_edit_handler(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """Editing a grade in the gradebook pivot updates DB and tracks pending."""
    row_data, col_defs = build_gradebook_view(ui_conn)
    pending: PendingChanges = {}
    badge_ref: dict[str, ui.label | None] = {"ref": None}

    def refresh() -> None:
        lbl = badge_ref["ref"]
        if lbl is not None:
            count = pending_count(pending)
            lbl.text = f"{count} pending" if count else "Synchronized"

    @ui.page("/test-gb-edit")
    def page() -> None:
        badge_ref["ref"] = ui.label("Synchronized").mark("status")
        grid = ui.aggrid(
            {
                "columnDefs": col_defs,
                "rowData": row_data,
                ":getRowId": "(params) => String(params.data._canvas_user_id)",
            }
        ).mark("gb-grid")
        attach_gradebook_edit_handler(grid, ui_conn, pending, refresh)

        def _simulate_grade_edit() -> None:
            handler = _find_listener(grid, "cellValueChanged")
            handler(
                SimpleNamespace(
                    args={
                        "colDef": {"field": "_a1"},
                        "value": "10",
                        "data": {
                            "_canvas_user_id": 100,
                            "_student_name": "Smith, Alice",
                            "_a1": "10",
                            "_a2": "18",
                        },
                    }
                )
            )

        ui.button("Simulate Grade Edit", on_click=_simulate_grade_edit).mark(
            "sim-grade"
        )

    await user.open("/test-gb-edit")
    await user.should_see(content="Synchronized")

    user.find(marker="sim-grade").click()

    # DB should be updated via upsert_canvas_grade
    result = ui_conn.execute(
        "SELECT posted_grade FROM canvas_grades "
        "WHERE canvas_user_id = 100 AND canvas_assignment_id = 1"
    ).fetchone()
    assert result is not None
    assert result[0] == "10"

    # Pending should track the grade change
    assert pending_count(pending) == 1
    assert "canvas_grades" in pending


# ===========================================================================
# Tier 2C — UI integration tests (User fixture)
# ===========================================================================


# ---------------------------------------------------------------------------
# find_grid — locates AG Grid inside a container
# ---------------------------------------------------------------------------


async def test_find_grid_in_container(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """find_grid() returns the AG Grid from a nested container."""
    grid_container: dict[str, object] = {"ref": None}
    found_grid: dict[str, object] = {"ref": None}

    @ui.page("/test-find-grid")
    def page() -> None:
        container = ui.element("div")
        grid_container["ref"] = container
        with container:
            ui.aggrid(
                {
                    "columnDefs": [{"field": "name"}],
                    "rowData": [{"name": "test"}],
                }
            )

        def _check() -> None:
            found_grid["ref"] = find_grid(grid_container)

        ui.button("Check", on_click=_check).mark("check-btn")

    await user.open("/test-find-grid")
    user.find(marker="check-btn").click()
    assert found_grid["ref"] is not None
    assert isinstance(found_grid["ref"], ui.aggrid)


async def test_find_grid_empty_container(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """find_grid() returns None for an empty container."""
    grid_container: dict[str, object] = {"ref": None}
    result: dict[str, object] = {"ref": "sentinel"}

    @ui.page("/test-find-grid-empty")
    def page() -> None:
        container = ui.element("div")
        grid_container["ref"] = container
        # No grid inside container

        def _check() -> None:
            result["ref"] = find_grid(grid_container)

        ui.button("Check", on_click=_check).mark("check-btn")

    await user.open("/test-find-grid-empty")
    user.find(marker="check-btn").click()
    assert result["ref"] is None


async def test_find_grid_none_ref(user: User) -> None:
    """find_grid() returns None when container ref is None."""
    result = find_grid({"ref": None})
    assert result is None


# ---------------------------------------------------------------------------
# reload_current_grid — refreshes grid data from DB
# ---------------------------------------------------------------------------


async def test_reload_current_grid(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """reload_current_grid() updates grid rowData with fresh DB data."""
    grid_container: dict[str, object] = {"ref": None}
    grid_ref: dict[str, ui.aggrid | None] = {"ref": None}

    @ui.page("/test-reload")
    def page() -> None:
        container = ui.element("div")
        grid_container["ref"] = container
        with container:
            rows = get_table_rows(ui_conn, "canvas_assignments")
            col_defs = build_column_defs(ui_conn, "canvas_assignments")
            g = ui.aggrid({"columnDefs": col_defs, "rowData": rows})
            grid_ref["ref"] = g

        def _add_and_reload() -> None:
            ui_conn.execute(
                "INSERT INTO canvas_assignments VALUES "
                "(3, 'Homework 3', 30.0, '2026-03-01T23:59', true, '')"
            )
            reload_current_grid(ui_conn, grid_container, "canvas_assignments")

        ui.button("Add & Reload", on_click=_add_and_reload).mark("reload-btn")

    await user.open("/test-reload")
    user.find(marker="reload-btn").click()

    grid = grid_ref["ref"]
    assert grid is not None
    assert len(grid.options["rowData"]) == 3


# ---------------------------------------------------------------------------
# export_markdown — triggers download with markdown content
# ---------------------------------------------------------------------------


async def test_export_markdown(user: User, ui_conn: duckdb.DuckDBPyConnection) -> None:
    """export_markdown() generates correct markdown content."""
    grid_container: dict[str, object] = {"ref": None}
    md_content: dict[str, str] = {"ref": ""}

    @ui.page("/test-export-md")
    def page() -> None:
        container = ui.element("div")
        grid_container["ref"] = container
        with container:
            ui.aggrid(
                {
                    "columnDefs": [
                        {"field": "name", "headerName": "Name"},
                        {"field": "score", "headerName": "Score"},
                    ],
                    "rowData": [
                        {"name": "Alice", "score": "95"},
                        {"name": "Bob", "score": "87"},
                    ],
                }
            )

        def _export() -> None:
            grid = find_grid(grid_container)
            if grid:
                md_content["ref"] = _grid_to_markdown(grid)

        ui.button("Export", on_click=_export).mark("export-btn")

    await user.open("/test-export-md")
    user.find(marker="export-btn").click()

    md = md_content["ref"]
    assert "Name" in md
    assert "Score" in md
    assert "Alice" in md
    assert "Bob" in md
    assert "95" in md


# ---------------------------------------------------------------------------
# Sidebar dev section — dev tables in collapsed expansion
# ---------------------------------------------------------------------------


async def test_dev_tables_config(
    user: User, ui_conn: duckdb.DuckDBPyConnection
) -> None:
    """DEV_TABLES config correctly identifies internal tables."""
    assert "_canvas_assignments_synced" in DEV_TABLES
    assert "_canvas_grades_synced" in DEV_TABLES
    assert "students" in DEV_TABLES
    assert "assignments" in DEV_TABLES
    # Regular tables should NOT be dev tables
    assert "canvas_assignments" not in DEV_TABLES
    assert "canvas_grades" not in DEV_TABLES
