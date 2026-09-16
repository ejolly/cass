"""TDD tests for class-based modal refactor.

Tests that modal classes are importable, instantiate with a ViewerPage,
and render expected UI when opened.
"""

from __future__ import annotations

__docformat__ = "google"

import pytest
import sqlite_utils
from nicegui import ui
from nicegui.testing import User


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
        "  assignment_group TEXT DEFAULT '',"
        "  post_manually BOOLEAN DEFAULT false"
        ")"
    )
    conn.execute(
        "INSERT INTO canvas_assignments VALUES "
        "(1, 'Homework 1', 10.0, '2026-02-01T23:59', true, 'Assignments', false),"
        "(2, 'Homework 2', 20.0, '2026-02-15T23:59', true, 'Assignments', false)"
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

    # Shadow tables for pending-change tracking
    conn.execute(
        "CREATE TABLE _canvas_assignments_synced ("
        "  canvas_id INTEGER PRIMARY KEY,"
        "  name TEXT, points_possible DOUBLE, due_at TEXT,"
        "  published BOOLEAN, assignment_group TEXT, post_manually BOOLEAN"
        ")"
    )
    conn.execute(
        "INSERT INTO _canvas_assignments_synced SELECT * FROM canvas_assignments"
    )
    conn.execute(
        "CREATE TABLE _canvas_grades_synced ("
        "  canvas_user_id INTEGER NOT NULL,"
        "  canvas_assignment_id INTEGER NOT NULL,"
        "  posted_grade TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (canvas_user_id, canvas_assignment_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO _canvas_grades_synced "
        "SELECT canvas_user_id, canvas_assignment_id, posted_grade FROM canvas_grades"
    )
    return conn


@pytest.fixture
def ui_conn() -> sqlite_utils.Database:
    return _make_ui_conn()


def _make_page(conn: sqlite_utils.Database):
    """Create a ViewerPage with state initialized but no UI built."""
    from cass.viewer.page import ViewerPage

    page = ViewerPage.__new__(ViewerPage)
    page._init_state(conn)
    # Provide minimal UI refs that modals may touch
    page.grid_container = ui.element("div")
    return page


class TestModalImports:
    def test_push_modal_importable(self):
        from cass.viewer.modals.push import PushModal

        assert PushModal is not None

    def test_create_assignment_modal_importable(self):
        from cass.viewer.modals.create_assignment import CreateAssignmentModal

        assert CreateAssignmentModal is not None

    def test_delete_assignment_modal_importable(self):
        from cass.viewer.modals.delete_assignment import DeleteAssignmentModal

        assert DeleteAssignmentModal is not None

    def test_package_reexports(self):
        from cass.viewer.modals import (
            CreateAssignmentModal,
            DeleteAssignmentModal,
            PushModal,
        )

        assert all(
            cls is not None
            for cls in [
                PushModal,
                CreateAssignmentModal,
                DeleteAssignmentModal,
            ]
        )


class TestModalInterface:
    def test_push_modal_has_open(self):
        from cass.viewer.modals.push import PushModal

        assert callable(getattr(PushModal, "open", None))

    def test_create_assignment_modal_has_open(self):
        from cass.viewer.modals.create_assignment import CreateAssignmentModal

        assert callable(getattr(CreateAssignmentModal, "open", None))

    def test_delete_assignment_modal_has_open(self):
        from cass.viewer.modals.delete_assignment import DeleteAssignmentModal

        assert callable(getattr(DeleteAssignmentModal, "open", None))


class TestModalRendering:
    async def test_push_title(self, user: User, ui_conn: sqlite_utils.Database) -> None:
        from cass.viewer.modals.push import PushModal

        @ui.page("/test-push-modal")
        def page() -> None:
            vp = _make_page(ui_conn)
            modal = PushModal(vp)
            modal.open()

        await user.open("/test-push-modal")
        await user.should_see("Push to Canvas")

    async def test_create_title(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        from cass.viewer.modals.create_assignment import CreateAssignmentModal

        @ui.page("/test-create-modal")
        def page() -> None:
            vp = _make_page(ui_conn)
            modal = CreateAssignmentModal(vp)
            modal.open()

        await user.open("/test-create-modal")
        await user.should_see("Create Assignment")

    async def test_create_form_fields(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        from cass.viewer.modals.create_assignment import CreateAssignmentModal

        @ui.page("/test-create-fields")
        def page() -> None:
            vp = _make_page(ui_conn)
            modal = CreateAssignmentModal(vp)
            modal.open()

        await user.open("/test-create-fields")
        await user.should_see("Name")
        await user.should_see("Points Possible")
        await user.should_see("Cancel")
        await user.should_see("Create")

    async def test_delete_title(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        from cass.viewer.modals.delete_assignment import DeleteAssignmentModal

        @ui.page("/test-delete-modal")
        def page() -> None:
            vp = _make_page(ui_conn)
            modal = DeleteAssignmentModal(vp)
            modal.open()

        await user.open("/test-delete-modal")
        await user.should_see("Delete Assignment")

    async def test_delete_select_and_buttons(
        self, user: User, ui_conn: sqlite_utils.Database
    ) -> None:
        from cass.viewer.modals.delete_assignment import DeleteAssignmentModal

        @ui.page("/test-delete-fields")
        def page() -> None:
            vp = _make_page(ui_conn)
            modal = DeleteAssignmentModal(vp)
            modal.open()

        await user.open("/test-delete-fields")
        await user.should_see("Assignment")
        await user.should_see("Cancel")
        await user.should_see("Delete")
