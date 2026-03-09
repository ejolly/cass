"""Pull GH repos modal dialog."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from typing import TYPE_CHECKING, Any

from nicegui import ui

if TYPE_CHECKING:
    from ..page import ViewerPage


class PullGHModal:
    """Modal to clone/pull student repos from GitHub Classroom."""

    def __init__(self, page: ViewerPage) -> None:
        self.page = page
        self._state: dict[str, Any] = {"running": False}
        self._build()

    def _build(self) -> None:
        with ui.dialog() as self.dialog, ui.card().classes("v-modal-card"):
            ui.label("Pull GH Repos").classes("v-modal-title")
            ui.label(
                "Clone or update student repos from GitHub Classroom "
                "into gh-classroom/."
            ).classes("v-modal-subtitle")

            self._student_select = (
                ui.select(
                    options={},
                    label="Students",
                    multiple=True,
                    value=[],
                )
                .props("dense outlined use-chips")
                .classes("w-full")
            )

            self._assignment_select = (
                ui.select(
                    options={},
                    label="Assignments",
                    multiple=True,
                    value=[],
                )
                .props("dense outlined use-chips")
                .classes("w-full mt-1")
            )

            self._log_area = ui.element("div").classes("v-log-area")
            self._log_area.set_visibility(False)

            self._action_row = ui.row().classes("v-modal-actions")
            self._build_default_actions()

    def _build_default_actions(self) -> None:
        with self._action_row:
            ui.button(
                "Remove All",
                icon="delete",
                on_click=lambda: asyncio.ensure_future(self._run_remove()),
            ).props("flat dense no-caps size=sm color=negative")
            ui.space()
            ui.button("Cancel", on_click=self.dialog.close).props(
                "flat dense no-caps size=sm"
            )
            ui.button(
                "Pull",
                on_click=lambda: asyncio.ensure_future(self._run_pull()),
            ).props("color=primary dense no-caps size=sm")

    def open(self) -> None:
        from ... import db
        from ...apis.github.fetch import get_sortable_names, student_dir_name

        all_assignments = db.load_assignments()
        gh_all = [a for a in all_assignments if a.gh_assignment_slug]
        self._gh_assignments_all = gh_all
        assignment_options = {a.slug: a.title for a in gh_all}

        all_students = db.load_students()
        self._all_students = all_students
        sortable_map = get_sortable_names()
        student_options = {
            s.canvas_id: student_dir_name(s, sortable_map) for s in all_students
        }

        self._student_select.options = student_options  # pyright: ignore[reportAttributeAccessIssue]
        self._student_select.value = list(student_options.keys())
        self._assignment_select.options = assignment_options  # pyright: ignore[reportAttributeAccessIssue]
        self._assignment_select.value = list(assignment_options.keys())

        self._log_area.clear()
        self._log_area.set_visibility(False)
        self._action_row.clear()
        self._build_default_actions()

        self.dialog.open()

    def _append_log(self, msg: str) -> None:
        self._log_area.set_visibility(True)
        with self._log_area:
            ui.label(msg).classes("v-log-line")

    def _show_close_button(self) -> None:
        self._action_row.clear()
        with self._action_row:
            ui.button("Close", on_click=self.dialog.close).props(
                "flat dense no-caps size=sm"
            )

    async def _run_pull(self) -> None:
        if self._state["running"]:
            return
        self._state["running"] = True

        self._action_row.clear()
        with self._action_row:
            ui.button("Pulling...", on_click=lambda: None).props(
                "color=primary disabled dense no-caps size=sm"
            )

        self._log_area.clear()
        self._log_area.set_visibility(True)

        try:
            from ...actions.config import get_config
            from ...apis.github import fetch as fetch_mod
            from ...apis.github.client import GitHubClient

            cfg = get_config()
            if not cfg.has_classroom:
                self._append_log("ERROR: No classroom configured")
                return

            selected_slugs: list[str] = self._assignment_select.value or []
            if not selected_slugs:
                self._append_log("No assignments selected.")
                return

            selected_ids: set[int] = set(self._student_select.value or [])
            if not selected_ids:
                self._append_log("No students selected.")
                return

            gh_assignments = [
                a for a in self._gh_assignments_all if a.slug in selected_slugs
            ]
            roster = [s for s in self._all_students if s.canvas_id in selected_ids]

            self._append_log(
                f"Pulling {len(gh_assignments)} assignment(s), "
                f"{len(roster)} student(s)..."
            )

            async with GitHubClient() as client:
                counts = await fetch_mod.pull_gh(
                    client,
                    gh_assignments,
                    roster,
                    on_progress=self._append_log,
                )

            self._append_log("")
            self._append_log(
                f"Done: {counts['cloned']} cloned, "
                f"{counts['updated']} updated, "
                f"{counts['up_to_date']} up-to-date, "
                f"{counts['skipped']} skipped, "
                f"{counts['errors']} errors"
            )
        except Exception as exc:
            self._append_log(f"ERROR: {exc}")
        finally:
            self._state["running"] = False
            self._show_close_button()

    async def _run_remove(self) -> None:
        if self._state["running"]:
            return
        self._state["running"] = True
        self._action_row.clear()
        with self._action_row:
            ui.button("Removing...", on_click=lambda: None).props(
                "color=negative disabled dense no-caps size=sm"
            )

        self._log_area.clear()
        self._log_area.set_visibility(True)

        try:
            from ...actions.config import get_config
            from ...apis.github.fetch import gh_classroom_dir, remove_gh_classroom_repos

            cfg = get_config()
            gh_dir = gh_classroom_dir(cfg.root)
            if not gh_dir.exists():
                self._append_log("Nothing to remove — gh-classroom/ not found.")
                return

            removed = remove_gh_classroom_repos(cfg.root)
            if not removed:
                self._append_log("gh-classroom/ is already empty.")
                return

            self._append_log(f"Removed {removed} folder(s) from gh-classroom/.")
        except Exception as exc:
            self._append_log(f"ERROR: {exc}")
        finally:
            self._state["running"] = False
            self._show_close_button()
