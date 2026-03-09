"""Sidebar navigation component for the viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from nicegui import ui

from ...db import get_meta, is_editable
from ..config import DEV_TABLES, display_name
from ..grid import revert_pending
from ..styles import NAV_ITEM, NAV_ITEM_ACTIVE

if TYPE_CHECKING:
    from ..page import ViewerPage


class Sidebar:
    """Sidebar navigation panel — table groups, badges, action buttons."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._build()

    def _build(self) -> None:
        with ui.column().classes("v-sidebar"):
            self._build_header()
            self._build_nav_groups()
            self._build_dev_section()

    def _build_header(self) -> None:
        p = self.page
        course_name = get_meta("course_name", p.conn) or "Untitled"
        with ui.column().classes("v-sidebar-header"):
            ui.label(course_name).classes("v-course-name")
            ui.label("cass viewer").classes("v-app-label")

            # Sync status
            with ui.row().classes("v-sync-row"):
                ui.button(
                    icon="sync",
                    on_click=lambda: ui.navigate.to("/pull"),
                ).props("flat dense round size=xs color=grey-6").tooltip(
                    "Pull latest data"
                )
                p.pending_badge = ui.badge(
                    "Synchronized",
                    color="green",
                    text_color="white",
                ).classes("v-pending-badge")

            with ui.row().classes("v-action-row"):
                p.revert_btn = ui.button(
                    "Revert",
                    on_click=lambda: revert_pending(
                        p.conn,
                        p.pending,
                        p.update_pending_display,
                        {"ref": p.grid_container},
                        {"name": p.current_table},
                    ),
                ).props("flat dense no-caps size=xs color=red")
                p.revert_btn.set_visibility(False)

                p.push_btn = ui.button(
                    "Push to Canvas",
                    on_click=lambda: p.push_modal.open(),
                ).props("dense no-caps size=xs color=primary")
                p.push_btn.set_visibility(False)

    def _build_nav_groups(self) -> None:
        p = self.page

        scroll = ui.scroll_area().classes("flex-1")
        with scroll, ui.column().classes("v-nav-scroll-col"):
            for group in p.groups:
                with ui.row().classes("v-nav-group-row"):
                    ui.label(group["label"]).classes("v-nav-group-label")
                    if group["label"] == "Canvas LMS" and p.has_canvas_assignments:
                        ui.space()
                        ui.button(
                            icon="add",
                            on_click=lambda: p.create_modal.open(),
                        ).props("flat dense round size=xs color=grey-6").tooltip(
                            "Create assignment"
                        )
                        ui.button(
                            icon="delete",
                            on_click=lambda: p.delete_modal.open(),
                        ).props("flat dense round size=xs color=grey-6").tooltip(
                            "Delete assignment"
                        )
                    if group["label"] == "GitHub Classroom" and p.has_classroom:
                        ui.space()
                        ui.button(
                            "Pull Repos",
                            icon="download",
                            on_click=lambda: p.pull_gh_modal.open(),
                        ).props("flat dense no-caps size=xs color=grey-6").classes(
                            "v-pull-repos-btn"
                        )

                # Sidebar entries
                sidebar_entries: list[tuple[str, str, bool]] = []
                if group["label"] == "GitHub Classroom":
                    sidebar_entries.append(("gh_gradebook", "Gradebook", False))
                for t in group["items"]:
                    tn = t["name"]
                    show_editable = is_editable(p.conn, tn) and tn != "gh_students"
                    sidebar_entries.append((tn, display_name(tn), show_editable))

                for tn, dn, editable_item in sidebar_entries:
                    is_active = tn == p.current_table
                    item = (
                        ui.row()
                        .classes(
                            f"{NAV_ITEM}{' ' + NAV_ITEM_ACTIVE if is_active else ''}"
                        )
                        .on(
                            "click",
                            lambda _e, n=tn: p.load_table(n),
                        )
                    )
                    with item:
                        ui.label(dn).classes("v-nav-table-name")
                        ui.space()
                        if editable_item:
                            ui.badge("editable").props("outline color=green").classes(
                                "v-nav-badge"
                            )
                        else:
                            ui.badge("view-only").props("outline color=grey-7").classes(
                                "v-nav-badge"
                            )
                    p.sidebar_items[tn] = item

    def _build_dev_section(self) -> None:
        p = self.page
        dev_tables = sorted(DEV_TABLES)
        with (
            ui.column().classes("v-dev-section"),
            ui.expansion("Dev", icon="code")
            .classes("v-dev-expansion")
            .props("dense header-class='px-4 py-1'"),
        ):
            for dt in dev_tables:
                item = (
                    ui.row()
                    .classes(NAV_ITEM)
                    .on(
                        "click",
                        lambda _e, n=dt: p.load_table(n),
                    )
                )
                with item:
                    ui.label(dt).classes("v-nav-dev-table")
                    ui.space()
                    ui.badge("internal").props("outline color=grey-8").classes(
                        "v-nav-badge"
                    )
                p.sidebar_items[dt] = item
