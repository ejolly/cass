"""NiceGUI-based database viewer — pure Python, AG Grid, no build step."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

import duckdb
from nicegui import ui

from ..config import config_file_path
from ..db import DB_FILENAME, get_meta, get_pending_changes
from ..db import reset as db_reset
from .config import (
    CANVAS_PUSHABLE,
    DEV_TABLES,
    PendingChanges,
    display_name,
    group_tables,
)
from .grid import (
    apply_search,
    attach_date_autocommit,
    attach_edit_handler,
    attach_gradebook_edit_handler,
    build_column_defs,
    build_gh_gradebook_view,
    build_gradebook_view,
    export_csv,
    export_markdown,
    get_primary_keys,
    get_table_rows,
    get_tables,
    is_editable,
    pending_count,
    restore_pending_cells,
    revert_pending,
    row_id_js,
    track_change,
)
from .pull_gh_modal import open_pull_gh_modal
from .push_modal import open_push_modal

# Re-export for tests and external consumers
__all__ = [
    "get_tables",
    "is_editable",
    "pending_count",
    "start_nicegui_server",
    "track_change",
]

# Minimal CSS only for things that cannot be expressed via Tailwind/Quasar:
# - AG Grid cell class rules (applied dynamically by the grid engine)
# - Push-modal preview HTML tables (rendered via ui.html)
_GRID_CSS = """
.cell-pending { background: rgba(245, 158, 11, 0.15) !important; }
.push-table {
    width: 100%; border-collapse: collapse;
    font-size: 0.8rem; margin: 0.5rem 0;
}
.push-table th {
    text-align: left; padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.2);
    opacity: 0.6; font-weight: 600;
}
.push-table td {
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}
.push-table .conflict-row { background: rgba(234,179,8,0.1); }
.push-table .error-row { background: rgba(239,68,68,0.1); }
"""


# ---------------------------------------------------------------------------
# NiceGUI app
# ---------------------------------------------------------------------------


def _detect_state() -> str:
    """Return 'setup', 'pull', or 'ready' based on config/db presence."""
    from ..db import is_remote

    cfg_path = config_file_path()
    if cfg_path is None:
        return "setup"

    # Config exists — check database
    if is_remote():
        return "ready"

    from ..config import get_config

    cfg = get_config()
    db_file = cfg.root / DB_FILENAME
    if not db_file.exists():
        return "pull"

    return "ready"


def start_nicegui_server(port: int = 0) -> None:
    """Start the NiceGUI viewer, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.

    Routes based on project state:
    - No cass.toml → setup wizard
    - cass.toml but no database → auto-pull with progress
    - Both exist → normal table viewer
    """
    from .setup import pull_progress_page, setup_wizard_page

    @ui.page("/")
    def root_page() -> None:  # pyright: ignore[reportUnusedFunction]
        state = _detect_state()
        if state == "setup":
            setup_wizard_page(on_complete=lambda: ui.navigate.to("/pull"))
        elif state == "pull":
            pull_progress_page(on_complete=lambda: ui.navigate.to("/view"))
        else:
            ui.navigate.to("/view")

    @ui.page("/pull")
    def pull_page() -> None:  # pyright: ignore[reportUnusedFunction]
        pull_progress_page(on_complete=lambda: ui.navigate.to("/view"))

    @ui.page("/view")
    def view_page() -> None:  # pyright: ignore[reportUnusedFunction]
        _render_viewer()

    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass viewer",
        port=port if port > 0 else None,
        dark=True,
        reload=False,
        show=True,
        favicon="\U0001f4ca",
    )


def _render_viewer() -> None:
    """Render the main table viewer (the original index page content)."""
    from ..db import db_path

    db_reset()
    conn = duckdb.connect(db_path())
    tables = get_tables(conn)
    groups = group_tables(tables)
    pending: PendingChanges = get_pending_changes(conn)

    ui.add_head_html(f"<style>{_GRID_CSS}</style>")

    # --- State ---
    grid_container: dict[str, Any] = {"ref": None}
    default_table = next(
        (t["name"] for t in tables if t["name"] == "canvas_grades"),
        tables[0]["name"] if tables else "",
    )
    current_table: dict[str, str] = {"name": default_table}
    sidebar_items: dict[str, ui.element] = {}
    pending_badge: dict[str, ui.badge | None] = {"ref": None}
    table_label: dict[str, ui.label | None] = {"ref": None}
    meta_label: dict[str, ui.label | None] = {"ref": None}
    search_input: dict[str, ui.input | None] = {"ref": None}
    revert_btn: dict[str, ui.button | None] = {"ref": None}
    push_btn: dict[str, ui.button | None] = {"ref": None}

    # --- Helpers ---

    _ITEM_BASE = (
        "w-full items-center gap-1 px-4 py-1 cursor-pointer "
        "rounded-none text-white/70 hover:bg-white/[0.08] hover:text-white/95"
    )
    _ITEM_ACTIVE = "bg-blue-500/20 !text-white font-semibold"

    def update_pending_display() -> None:
        """Refresh the pending/sync badge and toggle revert/push visibility."""
        count = pending_count(pending)
        has_pending = count > 0
        badge = pending_badge["ref"]
        if badge is not None:
            if has_pending:
                badge.text = f"{count} pending"
                badge.props("color=amber-8 text-color=white")
            else:
                badge.text = "Synchronized"
                badge.props("color=green text-color=white")
        rb = revert_btn["ref"]
        if rb is not None:
            rb.set_visibility(has_pending)
        pb = push_btn["ref"]
        if pb is not None:
            pushable = current_table["name"] in CANVAS_PUSHABLE
            pb.set_visibility(has_pending and pushable)

    def load_table(table_name: str) -> None:
        """Load a table into the grid area."""
        old = current_table["name"]
        current_table["name"] = table_name

        # Update sidebar active states
        if old in sidebar_items:
            sidebar_items[old].classes(remove=_ITEM_ACTIVE)
        if table_name in sidebar_items:
            sidebar_items[table_name].classes(add=_ITEM_ACTIVE)

        # Update toolbar labels
        editable_flag = is_editable(conn, table_name)
        tl = table_label["ref"]
        if tl is not None:
            tl.text = display_name(table_name)

        # Build grid data
        is_canvas_gb = table_name == "canvas_grades"
        is_gh_gb = table_name == "gh_gradebook"
        is_gb = is_canvas_gb or is_gh_gb
        if is_canvas_gb:
            row_data, col_defs = build_gradebook_view(conn)
            pk_cols: list[str] = []
        elif is_gh_gb:
            row_data, col_defs = build_gh_gradebook_view(conn)
            pk_cols = []
        else:
            row_data = get_table_rows(conn, table_name)
            col_defs = build_column_defs(conn, table_name)
            pk_cols = get_primary_keys(conn, table_name) if editable_flag else []

        ml = meta_label["ref"]
        if ml is not None:
            n_visible = sum(
                1 for c in col_defs if not c.get("hide") and "children" not in c
            )
            n_visible += sum(len(c["children"]) for c in col_defs if "children" in c)
            if is_gb:
                ml.text = f"{len(row_data)} students \u00b7 {n_visible - 1} assignments"
            else:
                ml.text = f"{len(row_data)} rows \u00b7 {n_visible} columns"

        # Clear and rebuild grid container
        container = grid_container["ref"]
        if container is not None:
            container.clear()
            with container:
                grid_options: dict[str, Any] = {
                    "columnDefs": col_defs,
                    "rowData": row_data,
                    "defaultColDef": {
                        "sortable": True,
                        "resizable": True,
                        "minWidth": 80,
                    },
                    "animateRows": True,
                    "enableCellTextSelection": True,
                    "stopEditingWhenCellsLoseFocus": True,
                }

                if is_canvas_gb:
                    grid_options[":getRowId"] = (
                        "(params) => String(params.data._canvas_user_id)"
                    )
                elif is_gh_gb:
                    grid_options[":getRowId"] = (
                        "(params) => String(params.data._github_username)"
                    )
                else:
                    grid_options[":getRowId"] = f"(params) => {row_id_js(pk_cols)}"

                grid = (
                    ui.aggrid(grid_options, theme="quartz")
                    .classes("w-full")
                    .style("height: calc(100vh - 6rem)")
                )

                if is_canvas_gb:
                    attach_gradebook_edit_handler(
                        grid,
                        conn,
                        pending,
                        update_pending_display,
                    )
                elif editable_flag:
                    attach_edit_handler(
                        grid,
                        conn,
                        table_name,
                        pk_cols,
                        pending,
                        update_pending_display,
                    )

                if is_canvas_gb or editable_flag:
                    attach_date_autocommit(grid)

                # Restore pending cell highlights from persisted state
                if is_canvas_gb:
                    restore_pending_cells(
                        grid, pending, "canvas_grades", [], is_gradebook=True
                    )
                elif editable_flag:
                    restore_pending_cells(grid, pending, table_name, pk_cols)

        # Refresh pending/push display for new table context
        update_pending_display()

        # Clear search
        si = search_input["ref"]
        if si is not None:
            si.value = ""

    # --- Layout ---

    _SIDEBAR_PCT = 15
    splitter = ui.splitter(value=_SIDEBAR_PCT, limits=(0, 40)).classes(
        "w-full h-screen"
    )

    def _toggle_sidebar() -> None:
        splitter.value = 0 if splitter.value > 0 else _SIDEBAR_PCT  # pyright: ignore[reportAttributeAccessIssue]

    with splitter.before, ui.column().classes("w-full h-screen bg-[#1d1d1d] p-0 gap-0"):
        # Header
        course_name = get_meta("course_name", conn) or "Untitled Course"
        with ui.column().classes("w-full px-4 py-3 gap-0 border-b border-white/10"):
            ui.label(course_name).classes("text-sm font-semibold truncate")
            ui.label("cass viewer").classes("text-[0.65rem] opacity-40 tracking-wide")

        # Detect classroom config for Pull GH button
        try:
            from ..config import get_config

            has_classroom = get_config().has_classroom
        except SystemExit:
            has_classroom = False

        # Navigation
        scroll = ui.scroll_area().classes("flex-1")
        with scroll, ui.column().classes("w-full gap-0 py-2"):
            for group in groups:
                with ui.row().classes("w-full items-center px-4 pt-3 pb-1 gap-1"):
                    ui.label(group["label"]).classes(
                        "text-[0.7rem] font-bold tracking-wider opacity-50 uppercase"
                    )
                    if group["label"] == "GitHub Classroom" and has_classroom:
                        ui.space()
                        ui.button(
                            icon="sync",
                            on_click=open_pull_gh_modal,
                        ).props("flat dense round size=xs color=grey-6").tooltip(
                            "Pull repos from GitHub"
                        )
                # Inject GH gradebook virtual entry at top of GitHub group
                sidebar_entries: list[tuple[str, str, bool]] = []
                if group["label"] == "GitHub Classroom":
                    sidebar_entries.append(("gh_gradebook", "Gradebook", False))
                for t in group["items"]:
                    tn = t["name"]
                    sidebar_entries.append(
                        (tn, display_name(tn), is_editable(conn, tn))
                    )

                for tn, dn, editable_item in sidebar_entries:
                    is_active = tn == current_table["name"]

                    item = (
                        ui.row()
                        .classes(
                            f"{_ITEM_BASE}{' ' + _ITEM_ACTIVE if is_active else ''}"
                        )
                        .on(
                            "click",
                            lambda _e, n=tn: load_table(n),
                        )
                    )
                    with item:
                        ui.label(dn).classes("text-xs font-mono")
                        ui.space()
                        if editable_item:
                            ui.badge("editable").props("outline color=green").classes(
                                "text-[0.55rem]"
                            )
                        else:
                            ui.badge("view-only").props("outline color=grey-7").classes(
                                "text-[0.55rem]"
                            )
                    sidebar_items[tn] = item

        # Dev section — pinned to bottom of sidebar, outside scroll area
        dev_tables = sorted(DEV_TABLES)
        with (
            ui.column().classes("w-full gap-0 border-t border-white/10"),
            ui.expansion("Dev", icon="code")
            .classes(
                "w-full text-[0.7rem] font-bold tracking-wider"
                " opacity-40 uppercase px-0"
            )
            .props("dense header-class='px-4 py-1'"),
        ):
            for dt in dev_tables:
                item = (
                    ui.row()
                    .classes(_ITEM_BASE)
                    .on("click", lambda _e, n=dt: load_table(n))
                )
                with item:
                    ui.label(dt).classes("text-xs font-mono opacity-60")
                    ui.space()
                    ui.badge("internal").props("outline color=grey-8").classes(
                        "text-[0.55rem]"
                    )
                sidebar_items[dt] = item

    # Main content
    with splitter.after, ui.column().classes("w-full flex-1 gap-0"):
        # Toolbar row 1: title, metadata, export, status, actions
        with ui.row().classes(
            "w-full items-center gap-2 px-4 py-2 border-b border-white/10 bg-[#1d1d1d]"
        ):
            ui.button(
                icon="menu",
                on_click=_toggle_sidebar,
            ).props("flat dense round color=grey-6")

            tl = ui.label("").classes("text-sm font-semibold")
            table_label["ref"] = tl

            ml = ui.label("").classes("text-xs opacity-50")
            meta_label["ref"] = ml

            ui.button(
                "Export CSV",
                on_click=lambda: export_csv(grid_container),
            ).props("outline dense no-caps size=sm color=grey-5").classes("text-xs")
            ui.button(
                "Export Markdown",
                on_click=lambda: export_markdown(
                    grid_container,
                    current_table,
                ),
            ).props("outline dense no-caps size=sm color=grey-5").classes("text-xs")

            ui.space()

            # Status badge
            badge = ui.badge(
                "Synchronized",
                color="green",
                text_color="white",
            ).classes("text-[0.65rem] font-semibold")
            pending_badge["ref"] = badge

            # Revert button (hidden initially)
            rb = ui.button(
                "Revert",
                on_click=lambda: revert_pending(
                    conn,
                    pending,
                    update_pending_display,
                    grid_container,
                    current_table,
                ),
            ).props("flat dense no-caps size=sm color=red")
            rb.set_visibility(False)
            revert_btn["ref"] = rb

            # Push to Canvas button (hidden initially)
            pb = ui.button(
                "Push to Canvas",
                on_click=lambda: open_push_modal(
                    conn,
                    pending,
                    update_pending_display,
                    grid_container,
                    current_table,
                ),
            ).props("dense no-caps size=sm color=primary")
            pb.set_visibility(False)
            push_btn["ref"] = pb

        # Toolbar row 2: search
        with ui.row().classes("w-full px-4 py-1 border-b border-white/10 bg-[#1d1d1d]"):
            si = (
                ui.input(placeholder="Search rows...")
                .props("dense outlined rounded")
                .classes("w-1/3 min-w-[12rem] text-xs")
            )
            search_input["ref"] = si
            si.on(
                "update:model-value",
                lambda e: apply_search(
                    grid_container,
                    e.args,  # pyright: ignore[reportUnknownMemberType]
                ),
            )

        # Grid area
        gc = ui.element("div").classes("flex-1 w-full")
        grid_container["ref"] = gc

    # Keyboard shortcut: Ctrl/Cmd+K -> focus search
    def _focus_search() -> None:
        ui.run_javascript("document.querySelector('.q-field__native')?.focus()")

    ui.keyboard().on(
        "key",
        _focus_search,
        js_handler="""(e) => {
            if (e.key === 'k' && (e.ctrlKey || e.metaKey) && e.action === 'keydown') {
                emit(e);
                e.event.preventDefault();
            }
        }""",
    )

    # Load initial table
    if tables:
        load_table(default_table)
