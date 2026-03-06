"""NiceGUI-based database viewer — pure Python, AG Grid, no build step."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any

import duckdb
from nicegui import ui

from ..db import db_path
from ..db import reset as db_reset
from .config import (
    PendingChanges,
    display_name,
    group_tables,
)
from .grid import (
    apply_search,
    attach_edit_handler,
    attach_gradebook_edit_handler,
    build_column_defs,
    build_gradebook_view,
    export_csv,
    export_markdown,
    get_primary_keys,
    get_table_rows,
    get_tables,
    is_editable,
    pending_count,
    revert_pending,
    row_id_js,
    track_change,
)
from .push_modal import open_push_modal

# Re-export for tests and external consumers
__all__ = [
    "get_tables",
    "is_editable",
    "pending_count",
    "start_nicegui_server",
    "track_change",
]


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CUSTOM_CSS = """
/* Sidebar styling */
.sidebar {
    width: 14rem;
    min-width: 14rem;
    background: var(--q-dark-page, #1d1d1d);
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
}
.sidebar-header {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.sidebar-title {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    opacity: 0.6;
    text-transform: uppercase;
}
.sidebar-nav {
    flex: 1;
    overflow-y: auto;
    padding: 0.5rem 0;
}
.sidebar-group-label {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    opacity: 0.5;
    text-transform: uppercase;
    padding: 0.75rem 1rem 0.25rem 1rem;
}
.sidebar-item {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    text-align: left;
    padding: 0.35rem 1rem;
    font-size: 0.8rem;
    font-family: 'SF Mono', 'Fira Code', 'Consolas',
        ui-monospace, monospace;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    border: none;
    background: transparent;
    border-radius: 0;
    transition: background 0.15s;
}
.sidebar-item:hover {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.95);
}
.sidebar-item.active {
    background: rgba(59, 130, 246, 0.2);
    color: white;
    font-weight: 600;
}
.sidebar-pill {
    font-size: 0.55rem;
    padding: 0.05rem 0.35rem;
    border-radius: 9999px;
    font-weight: 600;
    white-space: nowrap;
    margin-left: auto;
}
.sidebar-pill-viewonly {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.35);
}
.sidebar-pill-editable {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
}
/* Toolbar */
.toolbar {
    padding: 0.5rem 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    align-items: center;
    gap: 0.625rem;
    min-height: 2.75rem;
    background: var(--q-dark-page, #1d1d1d);
}
.toolbar-label {
    font-size: 0.875rem;
    font-weight: 600;
}
.toolbar-badge {
    font-size: 0.65rem;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-weight: 600;
}
.badge-editable {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
}
.badge-readonly {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.5);
}
.toolbar-meta {
    font-size: 0.75rem;
    opacity: 0.5;
}
.pending-badge {
    font-size: 0.65rem;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-weight: 600;
    background: rgba(245, 158, 11, 0.2);
    color: #fbbf24;
}
.toolbar-btn-danger {
    background: rgba(239, 68, 68, 0.15);
    border-color: rgba(239, 68, 68, 0.4);
    color: #fca5a5;
}
.toolbar-btn-danger:hover {
    background: rgba(239, 68, 68, 0.3);
}
.toolbar-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.search-input {
    font-size: 0.75rem;
    padding: 0.25rem 0.5rem;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 0.25rem;
    background: transparent;
    color: inherit;
    width: 18rem;
    outline: none;
}
.search-input:focus {
    border-color: rgba(59, 130, 246, 0.5);
}
.search-input::placeholder {
    opacity: 0.4;
}
/* Toolbar buttons */
.toolbar-btn {
    font-size: 0.7rem;
    padding: 0.2rem 0.55rem;
    border-radius: 0.25rem;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: transparent;
    color: rgba(255, 255, 255, 0.8);
    cursor: pointer;
    white-space: nowrap;
}
.toolbar-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: white;
}
.toolbar-btn-primary {
    background: rgba(59, 130, 246, 0.2);
    border-color: rgba(59, 130, 246, 0.4);
    color: #93c5fd;
}
.toolbar-btn-primary:hover {
    background: rgba(59, 130, 246, 0.35);
}
/* Sidebar collapse */
.sidebar-collapsed {
    display: none !important;
}
.expand-btn {
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 100;
    background: var(--q-dark-page, #1d1d1d);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-left: none;
    border-radius: 0 0.25rem 0.25rem 0;
    color: rgba(255, 255, 255, 0.6);
    cursor: pointer;
    padding: 0.5rem 0.25rem;
    font-size: 0.75rem;
}
.expand-btn:hover {
    color: white;
    background: rgba(255, 255, 255, 0.08);
}
.collapse-btn {
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    font-size: 0.85rem;
    padding: 0 0.25rem;
}
.collapse-btn:hover {
    color: rgba(255, 255, 255, 0.8);
}
/* Push modal tables */
.push-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
    margin: 0.5rem 0;
}
.push-table th {
    text-align: left;
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
    opacity: 0.6;
    font-weight: 600;
}
.push-table td {
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.push-table .conflict-row {
    background: rgba(234, 179, 8, 0.1);
}
.push-table .error-row {
    background: rgba(239, 68, 68, 0.1);
}
/* Main layout */
.app-layout {
    display: flex;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
}
.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.grid-container {
    flex: 1;
    overflow: hidden;
    padding: 0;
}
"""


# ---------------------------------------------------------------------------
# NiceGUI app
# ---------------------------------------------------------------------------


def start_nicegui_server(port: int = 0) -> None:
    """Start the NiceGUI viewer, open the browser, block until Ctrl+C.

    Args:
        port: Port number to bind to. 0 = auto-select an available port.
    """
    db_reset()
    conn = duckdb.connect(db_path())
    tables = get_tables(conn)
    groups = group_tables(tables)
    pending: PendingChanges = {}

    @ui.page("/")
    def index() -> None:  # pyright: ignore[reportUnusedFunction]
        ui.add_head_html(f"<style>{_CUSTOM_CSS}</style>")

        # State containers for this page
        grid_container: dict[str, Any] = {"ref": None}
        # Default to gradebook if available, otherwise first table
        default_table = next(
            (t["name"] for t in tables if t["name"] == "canvas_grades"),
            tables[0]["name"] if tables else "",
        )
        current_table: dict[str, str] = {"name": default_table}
        sidebar_buttons: dict[str, ui.element] = {}
        pending_label: dict[str, Any] = {"ref": None}
        table_label: dict[str, Any] = {"ref": None}
        badge_el: dict[str, Any] = {"ref": None}
        meta_label: dict[str, Any] = {"ref": None}
        search_ref: dict[str, Any] = {"ref": None}
        clear_btn_ref: dict[str, Any] = {"ref": None}
        push_btn_ref: dict[str, Any] = {"ref": None}
        export_btn_ref: dict[str, Any] = {"ref": None}
        sidebar_ref: dict[str, Any] = {"ref": None}
        expand_btn_ref: dict[str, Any] = {"ref": None}
        sidebar_state: dict[str, bool] = {"collapsed": False}

        def update_pending_display() -> None:
            """Update pending badge and toggle revert/push button visibility."""
            count = pending_count(pending)
            visible = count > 0
            el = pending_label["ref"]
            if el is not None:
                el.text = f"{count} pending" if visible else ""
                el.set_visibility(visible)
            cb = clear_btn_ref["ref"]
            if cb is not None:
                cb.set_visibility(visible)
            pb = push_btn_ref["ref"]
            if pb is not None:
                pb.set_visibility(visible)

        def load_table(table_name: str) -> None:
            """Load a table into the grid area."""
            old = current_table["name"]
            current_table["name"] = table_name

            # Update sidebar active states
            if old in sidebar_buttons:
                sidebar_buttons[old].classes(remove="active", add="")
            if table_name in sidebar_buttons:
                sidebar_buttons[table_name].classes(add="active")

            # Update toolbar
            editable = is_editable(conn, table_name)
            tl = table_label["ref"]
            if tl is not None:
                tl.text = display_name(table_name)

            be = badge_el["ref"]
            if be is not None:
                if editable:
                    be.text = "EDITABLE"
                    be.classes(
                        remove="badge-readonly",
                        add="badge-editable",
                    )
                else:
                    be.text = "VIEW ONLY"
                    be.classes(
                        remove="badge-editable",
                        add="badge-readonly",
                    )

            # Build grid data
            is_gb = table_name == "canvas_grades"
            if is_gb:
                row_data, col_defs = build_gradebook_view(conn)
                pk_cols: list[str] = []
            else:
                row_data = get_table_rows(conn, table_name)
                col_defs = build_column_defs(conn, table_name)
                pk_cols = get_primary_keys(conn, table_name) if editable else []

            ml = meta_label["ref"]
            if ml is not None:
                n_visible = sum(
                    1 for c in col_defs if not c.get("hide") and "children" not in c
                )
                n_visible += sum(
                    len(c["children"]) for c in col_defs if "children" in c
                )
                if is_gb:
                    ml.text = (
                        f"{len(row_data)} students \u00b7 {n_visible - 1} assignments"
                    )
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
                    }

                    if is_gb:
                        grid_options[":getRowId"] = (
                            "(params) => String(params.data._canvas_user_id)"
                        )
                    else:
                        grid_options[":getRowId"] = f"(params) => {row_id_js(pk_cols)}"

                    grid = (
                        ui.aggrid(grid_options, theme="quartz")
                        .classes("w-full")
                        .style("height: calc(100vh - 3rem)")
                    )

                    if is_gb:
                        attach_gradebook_edit_handler(
                            grid,
                            conn,
                            pending,
                            update_pending_display,
                        )
                    elif editable:
                        attach_edit_handler(
                            grid,
                            conn,
                            table_name,
                            pk_cols,
                            pending,
                            update_pending_display,
                        )

            # Clear search
            sr = search_ref["ref"]
            if sr is not None:
                sr.value = ""

        def toggle_sidebar() -> None:
            """Toggle sidebar collapsed/expanded state."""
            collapsed = not sidebar_state["collapsed"]
            sidebar_state["collapsed"] = collapsed
            sb = sidebar_ref["ref"]
            eb = expand_btn_ref["ref"]
            if sb is not None:
                if collapsed:
                    sb.classes(add="sidebar-collapsed")
                else:
                    sb.classes(remove="sidebar-collapsed")
            if eb is not None:
                eb.set_visibility(collapsed)

        # --- Layout ---
        with ui.element("div").classes("app-layout"):
            # Expand button (visible only when sidebar is collapsed)
            expand_btn = (
                ui.element("button")
                .classes("expand-btn")
                .props('innerHTML="\u203a"')
                .on("click", lambda _: toggle_sidebar())
            )
            expand_btn.set_visibility(False)
            expand_btn_ref["ref"] = expand_btn

            # --- Sidebar ---
            sidebar_el = ui.element("div").classes("sidebar")
            sidebar_ref["ref"] = sidebar_el
            with sidebar_el:
                with ui.element("div").classes("sidebar-header"):
                    ui.element("span").classes("sidebar-title").props(
                        'innerHTML="CASS"'
                    )
                    ui.element("button").classes("collapse-btn").props(
                        'innerHTML="\u2039"'
                    ).on("click", lambda _: toggle_sidebar())

                with ui.element("div").classes("sidebar-nav"):
                    for group in groups:
                        ui.element("div").classes("sidebar-group-label").props(
                            f'innerHTML="{group["label"]}"'
                        )
                        for t in group["items"]:
                            tn = t["name"]
                            dn = display_name(tn)
                            editable_item = is_editable(conn, tn)
                            if editable_item:
                                pill = (
                                    "<span class='sidebar-pill"
                                    " sidebar-pill-editable'>"
                                    "editable</span>"
                                )
                            else:
                                pill = (
                                    "<span class='sidebar-pill"
                                    " sidebar-pill-viewonly'>"
                                    "view-only</span>"
                                )
                            btn = (
                                ui.element("button")
                                .classes("sidebar-item")
                                .props(f'innerHTML="{dn}{pill}"')
                                .on(
                                    "click",
                                    lambda _e, n=tn: load_table(n),
                                )
                            )
                            sidebar_buttons[tn] = btn
                            if tn == current_table["name"]:
                                btn.classes(add="active")

            # --- Main content ---
            with ui.element("div").classes("main-content"):
                # Toolbar
                with ui.element("div").classes("toolbar"):
                    tl = ui.label("").classes("toolbar-label")
                    table_label["ref"] = tl
                    be = ui.label("").classes("toolbar-badge badge-readonly")
                    badge_el["ref"] = be
                    ml = ui.label("").classes("toolbar-meta")
                    meta_label["ref"] = ml

                    pl = ui.label("").classes("pending-badge")
                    pl.set_visibility(False)
                    pending_label["ref"] = pl

                    # Revert button (hidden initially)
                    rb = (
                        ui.element("button")
                        .classes("toolbar-btn toolbar-btn-danger")
                        .props('innerHTML="Revert"')
                        .on(
                            "click",
                            lambda _: revert_pending(
                                conn,
                                pending,
                                update_pending_display,
                                grid_container,
                                current_table,
                            ),
                        )
                    )
                    rb.set_visibility(False)
                    clear_btn_ref["ref"] = rb

                    with ui.element("div").classes("toolbar-right"):
                        # Export CSV button
                        eb = (
                            ui.element("button")
                            .classes("toolbar-btn")
                            .props('innerHTML="CSV"')
                            .on("click", lambda _: export_csv(grid_container))
                        )
                        export_btn_ref["ref"] = eb

                        # Export Markdown button
                        (
                            ui.element("button")
                            .classes("toolbar-btn")
                            .props('innerHTML="Markdown"')
                            .on(
                                "click",
                                lambda _: export_markdown(
                                    grid_container, current_table
                                ),
                            )
                        )

                        si = (
                            ui.input(
                                placeholder="Search rows...",
                            )
                            .classes("search-input")
                            .props("dense outlined")
                        )
                        search_ref["ref"] = si
                        si.on(
                            "update:model-value",
                            lambda e: apply_search(
                                grid_container,
                                e.args,  # pyright: ignore[reportUnknownMemberType]
                            ),
                        )

                        # Push to Canvas button (hidden initially)
                        pb = (
                            ui.element("button")
                            .classes("toolbar-btn toolbar-btn-primary")
                            .props('innerHTML="Push to Canvas"')
                            .on(
                                "click",
                                lambda _: open_push_modal(
                                    conn,
                                    pending,
                                    update_pending_display,
                                    grid_container,
                                    current_table,
                                ),
                            )
                        )
                        pb.set_visibility(False)
                        push_btn_ref["ref"] = pb

                # Grid area
                gc = ui.element("div").classes("grid-container")
                grid_container["ref"] = gc

        # Keyboard shortcuts: Ctrl/Cmd+K -> focus search
        ui.add_body_html("""
        <script>
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const input = document.querySelector('.search-input input');
                if (input) input.focus();
            }
        });
        </script>
        """)

        # Load initial table
        if tables:
            load_table(default_table)

    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="cass viewer",
        port=port if port > 0 else None,
        dark=True,
        reload=False,
        show=True,
        favicon="\U0001f4ca",
    )
