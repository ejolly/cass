"""Sidebar navigation component for the viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from nicegui import ui

from ...db import get_meta
from ..config import DEV_TABLES, display_name
from ..grid import is_editable, revert_pending

if TYPE_CHECKING:
    from ..page import ViewerPage

_ITEM_BASE = (
    "w-full items-center gap-1 px-4 py-1 cursor-pointer "
    "rounded-none text-white/70 hover:bg-white/[0.08] hover:text-white/95 "
    "flex-nowrap"
)
_ITEM_ACTIVE = "bg-blue-500/20 !text-white font-semibold"


class Sidebar:
    """Sidebar navigation panel — table groups, badges, action buttons."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._build()

    def _build(self) -> None:
        with ui.column().classes("w-full h-screen bg-[#1d1d1d] p-0 gap-0"):
            self._build_header()
            self._build_nav_groups()
            self._build_dev_section()

    def _build_header(self) -> None:
        p = self.page
        course_name = get_meta("course_name", p.conn) or "Untitled"
        with ui.column().classes("w-full px-4 py-3 gap-0 border-b border-white/10"):
            ui.label(course_name).classes("text-sm font-semibold break-words")
            ui.label("cass viewer").classes("text-[0.65rem] opacity-40 tracking-wide")

            # Sync status
            with ui.row().classes("w-full items-center gap-2 mt-2"):
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
                ).classes("text-[0.6rem] font-semibold")

            with ui.row().classes("w-full items-center gap-2"):
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
                    on_click=lambda: p.open_push_modal(),
                ).props("dense no-caps size=xs color=primary")
                p.push_btn.set_visibility(False)

    def _build_nav_groups(self) -> None:
        from ..create_assignment_modal import open_create_assignment_modal
        from ..delete_assignment_modal import open_delete_assignment_modal
        from ..pull_gh_modal import open_pull_gh_modal

        p = self.page

        # Detect classroom config
        try:
            from ...config import get_config

            has_classroom = get_config().has_classroom
        except SystemExit:
            has_classroom = False

        scroll = ui.scroll_area().classes("flex-1")
        with scroll, ui.column().classes("w-full gap-0 py-2"):
            for group in p.groups:
                with ui.row().classes("w-full items-center px-4 pt-3 pb-1 gap-1"):
                    ui.label(group["label"]).classes(
                        "text-[0.7rem] font-bold tracking-wider opacity-50 uppercase"
                    )
                    if group["label"] == "Canvas LMS":
                        ui.space()
                        ui.button(
                            icon="add",
                            on_click=lambda: open_create_assignment_modal(
                                p.conn,
                                {"ref": p.grid_container},
                                {"name": p.current_table},
                                p.load_table,
                            ),
                        ).props("flat dense round size=xs color=grey-6").tooltip(
                            "Create assignment"
                        )
                        ui.button(
                            icon="delete",
                            on_click=lambda: open_delete_assignment_modal(
                                p.conn,
                                p.pending,
                                p.update_pending_display,
                                {"ref": p.grid_container},
                                {"name": p.current_table},
                                p.load_table,
                            ),
                        ).props("flat dense round size=xs color=grey-6").tooltip(
                            "Delete assignment"
                        )
                    if group["label"] == "GitHub Classroom" and has_classroom:
                        ui.space()
                        ui.button(
                            "Pull Repos",
                            icon="download",
                            on_click=open_pull_gh_modal,
                        ).props("flat dense no-caps size=xs color=grey-6").classes(
                            "text-[0.6rem]"
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
                            f"{_ITEM_BASE}{' ' + _ITEM_ACTIVE if is_active else ''}"
                        )
                        .on(
                            "click",
                            lambda _e, n=tn: p.load_table(n),
                        )
                    )
                    with item:
                        ui.label(dn).classes("text-xs font-mono")
                        ui.space()
                        if editable_item:
                            ui.badge("editable").props("outline color=green").classes(
                                "text-[0.55rem] shrink-0"
                            )
                        else:
                            ui.badge("view-only").props("outline color=grey-7").classes(
                                "text-[0.55rem] shrink-0"
                            )
                    p.sidebar_items[tn] = item

    def _build_dev_section(self) -> None:
        p = self.page
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
                    .on(
                        "click",
                        lambda _e, n=dt: p.load_table(n),
                    )
                )
                with item:
                    ui.label(dt).classes("text-xs font-mono opacity-60")
                    ui.space()
                    ui.badge("internal").props("outline color=grey-8").classes(
                        "text-[0.55rem]"
                    )
                p.sidebar_items[dt] = item
