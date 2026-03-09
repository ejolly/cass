"""Class-based viewer page — replaces the closure-heavy _render_viewer()."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

import sqlite_utils
from nicegui import ui

from ..db import (
    CANVAS_PUSHABLE,
    get_pending_changes,
    get_table_capability,
    get_tables,
    is_editable,
)
from .actions import pending_count
from .config import (
    PendingChanges,
    display_name,
    group_tables,
)
from .styles import NAV_ITEM_ACTIVE, load_styles

_SIDEBAR_PCT = 30


class ViewerPage:
    """Main table viewer page — renders sidebar, toolbar, and AG Grid.

    All UI state lives as instance attributes instead of dict-based refs.
    """

    def __init__(
        self,
        conn: sqlite_utils.Database,
        *,
        project_root: Path | None = None,
    ) -> None:
        self._init_state(conn, project_root=project_root)
        self._build()

    @property
    def conn(self) -> sqlite_utils.Database:
        """Return a live DB handle for the current viewer session."""
        if self._project_root is None:
            return self._conn
        try:
            self._conn.execute("SELECT 1").fetchone()
        except Exception:
            from ..db import get_db

            self._conn = get_db(self._project_root)
        return self._conn

    def _init_state(
        self,
        conn: sqlite_utils.Database,
        *,
        project_root: Path | None = None,
    ) -> None:
        """Initialize data and UI state (separated for testability)."""
        self._conn = conn
        self._project_root = project_root
        live_conn = self.conn
        self.tables = get_tables(live_conn)
        self.has_classroom = self._has_classroom_config()
        self.has_classroom_url = self._has_classroom_url_config()
        self.groups = group_tables(
            self.tables,
            has_classroom=self.has_classroom,
        )
        self.pending: PendingChanges = get_pending_changes(live_conn)
        self.has_canvas_assignments = any(
            t["name"] == "canvas_assignments" for t in self.tables
        )
        self.current_table = self._choose_initial_table()

        # UI refs — set during _build() by components
        self.pending_badge: ui.badge | None = None
        self.table_label: ui.label | None = None
        self.meta_label: ui.label | None = None
        self.search_input: ui.input | None = None
        self.grid_container: ui.element | None = None
        self.revert_btn: ui.button | None = None
        self.push_btn: ui.button | None = None
        self.sidebar_items: dict[str, ui.element] = {}

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def update_pending_display(self) -> None:
        """Refresh the pending/sync badge and toggle revert/push."""
        count = pending_count(self.pending)
        has_pending = count > 0

        if self.pending_badge is not None:
            if has_pending:
                self.pending_badge.text = f"{count} pending"
                self.pending_badge.props("color=amber-8 text-color=white")
            else:
                self.pending_badge.text = "Synchronized"
                self.pending_badge.props("color=green text-color=white")

        if self.revert_btn is not None:
            self.revert_btn.set_visibility(has_pending)

        if self.push_btn is not None:
            pushable = self.current_table in CANVAS_PUSHABLE
            self.push_btn.set_visibility(has_pending and pushable)

    def _choose_initial_table(self) -> str:
        """Pick the initial table for the viewer."""
        if not self.tables:
            return ""

        if any(table["name"] == "canvas_grades" for table in self.tables):
            return "canvas_grades"

        ranked = sorted(
            self.tables,
            key=lambda table: get_table_capability(table["name"]).viewer_rank,
        )
        return ranked[0]["name"]

    def _row_count(self, table: dict[str, str]) -> int:
        """Return the number of rows in a visible table or view."""
        return self.conn.table(table["name"]).count

    def _has_classroom_config(self) -> bool:
        """Return whether GitHub Classroom is configured for this project."""
        from ..db.core import _has_classroom_config

        return _has_classroom_config(self._project_root)

    def _has_classroom_url_config(self) -> bool:
        """Return whether a GitHub Classroom URL has been saved."""
        from ..db.core import _has_classroom_url_config

        return _has_classroom_url_config(self._project_root)

    def _empty_state_message(self, table_name: str, is_gradebook: bool) -> str:
        """Explain why an empty table is currently blank."""
        if table_name == "gh_gradebook":
            if self.has_classroom_url and not self.has_classroom:
                return (
                    "GitHub Classroom URL is saved, but the gh-classroom ID is "
                    "still unresolved. Run cass init after fixing gh auth or "
                    "Classroom access, then run cass pull."
                )
            if not self.has_classroom:
                return (
                    "No GitHub Classroom data is available. Add a [classroom] "
                    "section to cass.toml and run cass pull."
                )
            return (
                "No GitHub Classroom gradebook rows yet. Run cass pull to load "
                "roster, assignments, and submissions."
            )
        if table_name.startswith("gh_"):
            if self.has_classroom_url and not self.has_classroom:
                return (
                    "GitHub Classroom URL is saved, but the gh-classroom ID is "
                    "still unresolved. Run cass init after fixing gh auth or "
                    "Classroom access, then run cass pull."
                )
            if not self.has_classroom:
                return (
                    "No GitHub Classroom data is available. Add a [classroom] "
                    "section to cass.toml and run cass pull."
                )
            return (
                "No GitHub Classroom rows are available yet. Run cass pull to "
                "load the latest roster, assignments, and submissions."
            )
        capability = get_table_capability(table_name)
        if capability.editable:
            if is_gradebook:
                return (
                    "No gradebook rows yet. Run cass pull to load Canvas roster "
                    "and assignments."
                )
            return (
                "No Canvas-managed rows yet. Run cass pull to load data into this "
                "working table."
            )
        if is_editable(self.conn, table_name):
            return "No local rows are available in this table yet."
        return "No rows are available in this table yet."

    def load_table(self, table_name: str) -> None:
        """Load a table into the grid area."""
        from .components.grid_panel import GridPanel

        old = self.current_table
        self.current_table = table_name
        conn = self.conn

        # Update sidebar active states
        if old in self.sidebar_items:
            self.sidebar_items[old].classes(remove=NAV_ITEM_ACTIVE)
        if table_name in self.sidebar_items:
            self.sidebar_items[table_name].classes(add=NAV_ITEM_ACTIVE)

        # Update toolbar label
        if self.table_label is not None:
            self.table_label.text = display_name(table_name)

        # Build grid data
        is_canvas_gb = table_name == "canvas_grades"
        is_gh_gb = table_name == "gh_gradebook"
        is_gb = is_canvas_gb or is_gh_gb

        # Clear and rebuild grid container
        if self.grid_container is not None:
            self.grid_container.clear()
            with self.grid_container:
                row_data, col_defs = GridPanel.build_grid(
                    self.grid_container,
                    conn,
                    table_name,
                    self.pending,
                    self.update_pending_display,
                )
                if not row_data:
                    ui.label(
                        self._empty_state_message(table_name, is_canvas_gb)
                    ).classes("text-sm text-grey-6 px-4 pb-3")

            # Update metadata label
            if self.meta_label is not None:
                n_visible = sum(
                    1 for c in col_defs if not c.get("hide") and "children" not in c
                )
                n_visible += sum(
                    len(c["children"]) for c in col_defs if "children" in c
                )
                if is_gb:
                    self.meta_label.text = (
                        f"{len(row_data)} students \u00b7 {n_visible - 1} assignments"
                    )
                else:
                    self.meta_label.text = (
                        f"{len(row_data)} rows \u00b7 {n_visible} columns"
                    )

        self.update_pending_display()

        if self.search_input is not None:
            self.search_input.value = ""

    # ------------------------------------------------------------------
    # Private build methods
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Emit all NiceGUI elements for the viewer page."""
        from .components.grid_panel import GridPanel
        from .components.sidebar import Sidebar
        from .components.toolbar import Toolbar
        from .modals import (
            CreateAssignmentModal,
            DeleteAssignmentModal,
            PullGHModal,
            PushModal,
        )

        load_styles()

        # Create modal instances (dialog elements, hidden until .open())
        self.push_modal = PushModal(self)
        self.create_modal = CreateAssignmentModal(self)
        self.delete_modal = DeleteAssignmentModal(self)
        self.pull_gh_modal = PullGHModal(self)

        splitter = ui.splitter(value=_SIDEBAR_PCT, limits=(0, 50)).classes(
            "w-full h-screen"
        )
        self._splitter = splitter

        def _toggle_sidebar() -> None:
            splitter.value = 0 if splitter.value > 0 else _SIDEBAR_PCT  # pyright: ignore[reportAttributeAccessIssue]

        with splitter.before:
            Sidebar(self)

        with splitter.after, ui.column().classes("v-main-col"):
            Toolbar(self, toggle_sidebar=_toggle_sidebar)
            GridPanel(self)

        self._setup_keyboard()

        if self.tables:
            self.load_table(self.current_table)

    def _setup_keyboard(self) -> None:
        """Register Ctrl/Cmd+K keyboard shortcut for search focus."""

        def _focus_search() -> None:
            ui.run_javascript("document.querySelector('.q-field__native')?.focus()")

        ui.keyboard().on(
            "key",
            _focus_search,
            js_handler="""(e) => {
                if (e.key === 'k' && (e.ctrlKey || e.metaKey)
                    && e.action === 'keydown') {
                    emit(e);
                    e.event.preventDefault();
                }
            }""",
        )
