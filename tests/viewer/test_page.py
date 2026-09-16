"""TDD tests for class-based ViewerPage refactor.

Tests the ViewerPage class which replaces the _render_viewer() closure-based
function with a proper class that holds state as instance attributes.
"""

from __future__ import annotations

__docformat__ = "google"

import pytest
import sqlite_utils
from nicegui import ui
from nicegui.testing import User

from cass import db
from cass.actions.config import Config
from cass.db.core import _connection


def _make_ui_conn() -> sqlite_utils.Database:
    """In-memory DuckDB with a realistic viewer schema."""
    conn = sqlite_utils.Database(memory=True)
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
    return conn


def _make_ui_conn_without_assignments() -> sqlite_utils.Database:
    """In-memory DB without canvas_assignments for sparse viewer states."""
    conn = sqlite_utils.Database(memory=True)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('course_name', 'CS 101')")
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
    return conn


def _make_ui_conn_without_grades() -> sqlite_utils.Database:
    """In-memory DB with assignments but no gradebook rows."""
    conn = sqlite_utils.Database(memory=True)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('course_name', 'CS 101')")
    conn.execute(
        "CREATE TABLE canvas_assignments ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT,"
        "  points_possible DOUBLE,"
        "  due_at TEXT,"
        "  published BOOLEAN DEFAULT true,"
        "  assignment_group TEXT DEFAULT '',"
        "  post_manually BOOLEAN DEFAULT false"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_assignments VALUES "
        "(1, 'Homework 1', 10.0, '2026-02-01T23:59', true, 'Assignments', false)"
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
    return conn


@pytest.fixture
def ui_conn() -> sqlite_utils.Database:
    return _make_ui_conn()


@pytest.fixture
def ui_conn_no_assignments() -> sqlite_utils.Database:
    return _make_ui_conn_without_assignments()


@pytest.fixture
def ui_conn_no_grades() -> sqlite_utils.Database:
    return _make_ui_conn_without_grades()


class TestViewerPageInit:
    """ViewerPage.__init__ sets up instance attributes (not dict refs)."""

    def test_import(self):
        """ViewerPage is importable from cass.viewer.page."""
        from cass.viewer.page import ViewerPage

        assert ViewerPage is not None

    def test_has_instance_attrs(self, ui_conn: sqlite_utils.Database):
        """ViewerPage stores state as instance attributes, not dict refs."""
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn)

        # Core data
        assert hasattr(page, "conn")
        assert hasattr(page, "tables")
        assert hasattr(page, "groups")
        assert hasattr(page, "pending")
        assert hasattr(page, "current_table")

        # UI refs should be simple attributes (not dict wrappers)
        assert hasattr(page, "pending_badge")
        assert hasattr(page, "table_label")
        assert hasattr(page, "meta_label")
        assert hasattr(page, "search_input")
        assert hasattr(page, "grid_container")
        assert hasattr(page, "revert_btn")
        assert hasattr(page, "push_btn")
        assert hasattr(page, "sidebar_items")

    def test_default_table_canvas_grades(self, ui_conn: sqlite_utils.Database):
        """Default table is canvas_grades when it exists."""
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn)
        assert page.current_table == "canvas_grades"

    def test_pending_loaded(self, ui_conn: sqlite_utils.Database):
        """Pending changes loaded as a PendingChanges dict."""
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn)
        assert isinstance(page.pending, dict)

    def test_sidebar_items_empty_before_build(self, ui_conn: sqlite_utils.Database):
        """sidebar_items starts as empty dict before UI is built."""
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn)
        assert page.sidebar_items == {}

    def test_detects_missing_canvas_assignments(
        self, ui_conn_no_assignments: sqlite_utils.Database
    ):
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn_no_assignments)
        assert page.has_canvas_assignments is False

    def test_defaults_to_gradebook_when_gradebook_empty(
        self, ui_conn_no_grades: sqlite_utils.Database
    ):
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn_no_grades)
        assert page.current_table == "canvas_grades"

    def test_groups_only_canvas(self, ui_conn: sqlite_utils.Database):
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn)

        assert [g["label"] for g in page.groups] == ["Canvas LMS"]
        assert not hasattr(page, "has_classroom")

    def test_roster_listed_in_canvas_group(self, ui_conn: sqlite_utils.Database):
        from cass.viewer.page import ViewerPage

        page = ViewerPage.__new__(ViewerPage)
        page._init_state(ui_conn)

        names = [t["name"] for t in page.groups[0]["items"]]
        assert names == [
            "canvas_grades",
            "canvas_students",
            "canvas_assignments",
            "canvas_submissions",
        ]


class TestViewerPageMethods:
    """ViewerPage has update_pending_display and load_table as methods."""

    def test_update_pending_display_is_method(self):
        """update_pending_display is a regular method, not a closure."""
        from cass.viewer.page import ViewerPage

        assert callable(getattr(ViewerPage, "update_pending_display", None))

    def test_load_table_is_method(self):
        """load_table is a regular method, not a closure."""
        from cass.viewer.page import ViewerPage

        assert callable(getattr(ViewerPage, "load_table", None))


class TestComponents:
    """Sidebar, Toolbar, and GridPanel are importable component classes."""

    def test_sidebar_importable(self):
        from cass.viewer.components.sidebar import Sidebar

        assert Sidebar is not None

    def test_toolbar_importable(self):
        from cass.viewer.components.toolbar import Toolbar

        assert Toolbar is not None

    def test_grid_panel_importable(self):
        from cass.viewer.components.grid_panel import GridPanel

        assert GridPanel is not None


class TestComponentRendering:
    """Component rendering with NiceGUI User fixture."""

    async def test_sidebar_course_name(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Sidebar renders the course name from meta table."""
        from cass.viewer.components.sidebar import Sidebar
        from cass.viewer.page import ViewerPage

        @ui.page("/test-sidebar")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            Sidebar(vp)

        await user.open("/test-sidebar")
        await user.should_see("CS 101")
        await user.should_see("cass viewer")

    async def test_sidebar_table_groups(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Sidebar shows table groups (Canvas LMS) and entries."""
        from cass.viewer.components.sidebar import Sidebar
        from cass.viewer.page import ViewerPage

        @ui.page("/test-sidebar-groups")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            Sidebar(vp)

        await user.open("/test-sidebar-groups")
        await user.should_see("Canvas LMS")

    async def test_sidebar_populates_items(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Sidebar populates page.sidebar_items for all table entries."""
        from cass.viewer.components.sidebar import Sidebar
        from cass.viewer.page import ViewerPage

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-sidebar-items")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            Sidebar(vp)
            page_ref["ref"] = vp

        await user.open("/test-sidebar-items")
        vp = page_ref["ref"]
        assert vp is not None
        assert "canvas_assignments" in vp.sidebar_items
        assert "canvas_grades" in vp.sidebar_items

    async def test_sidebar_pending_badge(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Sidebar creates the pending badge on the page."""
        from cass.viewer.components.sidebar import Sidebar
        from cass.viewer.page import ViewerPage

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-sidebar-badge")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            Sidebar(vp)
            page_ref["ref"] = vp

        await user.open("/test-sidebar-badge")
        vp = page_ref["ref"]
        assert vp is not None
        assert vp.pending_badge is not None
        assert vp.revert_btn is not None
        assert vp.push_btn is not None

    async def test_toolbar_labels(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Toolbar creates table_label, meta_label, and search_input."""
        from cass.viewer.components.toolbar import Toolbar
        from cass.viewer.page import ViewerPage

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-toolbar")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            # Toolbar needs a grid_container ref for export buttons
            vp.grid_container = ui.element("div")
            Toolbar(vp, toggle_sidebar=lambda: None)
            page_ref["ref"] = vp

        await user.open("/test-toolbar")
        vp = page_ref["ref"]
        assert vp is not None
        assert vp.table_label is not None
        assert vp.meta_label is not None
        assert vp.search_input is not None

    async def test_toolbar_export_buttons(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Toolbar renders export CSV and Markdown buttons."""
        from cass.viewer.components.toolbar import Toolbar
        from cass.viewer.page import ViewerPage

        @ui.page("/test-toolbar-export")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            vp.grid_container = ui.element("div")
            Toolbar(vp, toggle_sidebar=lambda: None)

        await user.open("/test-toolbar-export")
        await user.should_see("Export CSV")
        await user.should_see("Export Markdown")

    async def test_grid_panel_container(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """GridPanel creates a grid container div on the page."""
        from cass.viewer.components.grid_panel import GridPanel
        from cass.viewer.page import ViewerPage

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-grid-panel")
        def page() -> None:
            vp = ViewerPage.__new__(ViewerPage)
            vp._init_state(ui_conn)
            GridPanel(vp)
            page_ref["ref"] = vp

        await user.open("/test-grid-panel")
        vp = page_ref["ref"]
        assert vp is not None
        assert vp.grid_container is not None


class TestViewerPageFull:
    """Full render with NiceGUI User fixture."""

    async def test_renders(self, user: User, ui_conn: sqlite_utils.Database) -> None:
        """ViewerPage renders a complete page with sidebar + grid."""
        from cass.viewer.page import ViewerPage

        @ui.page("/test-vp")
        def page() -> None:
            ViewerPage(ui_conn)

        await user.open("/test-vp")
        # Should see course name in sidebar
        await user.should_see("CS 101")
        # Should see the default table label
        await user.should_see("Gradebook")

    async def test_sidebar_navigation(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """Clicking sidebar items loads different tables via ViewerPage.load_table."""
        from cass.viewer.page import ViewerPage

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-vp-nav")
        def page() -> None:
            vp = ViewerPage(ui_conn)
            page_ref["ref"] = vp

        await user.open("/test-vp-nav")
        vp = page_ref["ref"]
        assert vp is not None
        assert vp.current_table == "canvas_grades"

    async def test_navigation_recovers_from_closed_db(
        self, user: User, tmp_path, monkeypatch
    ) -> None:
        """Viewer reloads a live DB connection before handling navigation."""
        from cass.viewer.page import ViewerPage

        cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
        monkeypatch.setattr("cass.db.core.get_config", lambda: cfg)
        file_db = db.open_db(tmp_path)
        file_db.execute("INSERT INTO meta VALUES ('course_name', 'CS 101')")
        file_db.execute(
            "INSERT INTO canvas_assignments "
            "(canvas_id, name, points_possible, due_at, published, assignment_group) "
            "VALUES (1, 'Homework 1', 10.0, '', 1, 'Assignments')"
        )
        file_db.execute(
            "INSERT INTO canvas_students (canvas_id, name, sortable_name, email) "
            "VALUES (100, 'Alice Smith', 'Smith, Alice', 'alice@test.edu')"
        )
        _connection(file_db).close()

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-vp-nav-reconnect")
        def page() -> None:
            vp = ViewerPage(db.open_db(tmp_path), project_root=tmp_path)
            page_ref["ref"] = vp

        await user.open("/test-vp-nav-reconnect")
        vp = page_ref["ref"]
        assert vp is not None

        _connection(vp._conn).close()
        vp.load_table("canvas_assignments")

        assert vp.current_table == "canvas_assignments"
        assert vp.table_label is not None
        assert vp.table_label.text == "Assignments"
        _connection(vp._conn).close()

    async def test_pending_display(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        """update_pending_display reflects pending count in the badge."""
        from cass.viewer.actions import pending_count, track_change
        from cass.viewer.page import ViewerPage

        page_ref: dict[str, ViewerPage | None] = {"ref": None}

        @ui.page("/test-vp-pending")
        def page() -> None:
            vp = ViewerPage(ui_conn)
            page_ref["ref"] = vp

        await user.open("/test-vp-pending")
        vp = page_ref["ref"]
        assert vp is not None

        # Initially synchronized
        assert pending_count(vp.pending) == 0

        # Track a change
        track_change(
            vp.pending,
            "canvas_grades",
            {"canvas_user_id": 100, "canvas_assignment_id": 1},
            "posted_grade",
            "9",
            "10",
        )
        vp.update_pending_display()
        assert vp.pending_badge is not None
        assert "1 pending" in vp.pending_badge.text


class TestBackwardCompat:
    """Existing test imports from nicegui_app continue to work."""

    def test_nicegui_app_reexports(self):
        from cass.viewer.nicegui_app import (
            get_tables,
            is_editable,
            pending_count,
            start_nicegui_server,
            track_change,
        )

        assert all(
            callable(f)
            for f in [
                get_tables,
                is_editable,
                pending_count,
                start_nicegui_server,
                track_change,
            ]
        )

    def test_detect_state_still_importable(self):
        from cass.viewer.nicegui_app import _detect_state

        assert callable(_detect_state)
