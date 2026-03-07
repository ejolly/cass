"""Class-based viewer page — replaces the closure-heavy _render_viewer()."""

from __future__ import annotations

__docformat__ = "google"

import duckdb
from nicegui import ui

from ..db import get_pending_changes
from .config import (
    CANVAS_PUSHABLE,
    PendingChanges,
    display_name,
    group_tables,
)
from .grid import (
    get_tables,
    pending_count,
)
from .styles import NAV_ITEM_ACTIVE, load_styles

_SIDEBAR_PCT = 30


class ViewerPage:
    """Main table viewer page — renders sidebar, toolbar, and AG Grid.

    All UI state lives as instance attributes instead of dict-based refs.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._init_state(conn)
        self._build()

    def _init_state(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initialize data and UI state (separated for testability)."""
        self.conn = conn
        self.tables = get_tables(conn)
        self.groups = group_tables(self.tables)
        self.pending: PendingChanges = get_pending_changes(conn)

        self.current_table: str = next(
            (t["name"] for t in self.tables if t["name"] == "canvas_grades"),
            self.tables[0]["name"] if self.tables else "",
        )

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

    def load_table(self, table_name: str) -> None:
        """Load a table into the grid area."""
        from .components.grid_panel import GridPanel

        old = self.current_table
        self.current_table = table_name

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
                    self.conn,
                    table_name,
                    self.pending,
                    self.update_pending_display,
                )

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

        load_styles()

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

    def open_push_modal(self) -> None:
        """Open the push-to-Canvas modal."""
        from .push_modal import open_push_modal

        open_push_modal(
            self.conn,
            self.pending,
            self.update_pending_display,
            {"ref": self.grid_container},
            {"name": self.current_table},
        )
