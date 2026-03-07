"""Pull GH repos modal dialog for the viewer."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
import shutil
from pathlib import Path
from typing import Any

from nicegui import ui


def open_pull_gh_modal() -> None:
    """Open a modal to clone/pull student repos from GitHub Classroom."""
    from .. import db
    from ..github.fetch import get_sortable_names, student_dir_name

    # Load GH-linked assignments for the select dropdown
    all_assignments = db.load_assignments()
    gh_assignments_all = [a for a in all_assignments if a.gh_assignment_slug]
    assignment_options: dict[str, str] = {a.slug: a.title for a in gh_assignments_all}

    # Load students with folder-name labels (last-first)
    all_students = db.load_students()
    sortable_map = get_sortable_names()
    student_options: dict[int, str] = {
        s.canvas_id: student_dir_name(s, sortable_map) for s in all_students
    }

    with ui.dialog() as dialog, ui.card().classes("min-w-[28rem] max-w-[36rem]"):
        dialog.open()

        ui.label("Pull GH Repos").classes("text-lg font-bold mb-2")
        ui.label(
            "Clone or update student repos from GitHub Classroom into gh-classroom/."
        ).classes("text-xs opacity-60 mb-3")

        # --- Controls ---
        student_select = (
            ui.select(
                options=student_options,
                label="Students",
                multiple=True,
                value=list(student_options.keys()),
            )
            .props("dense outlined use-chips")
            .classes("w-full")
        )

        assignment_select = (
            ui.select(
                options=assignment_options,
                label="Assignments",
                multiple=True,
                value=list(assignment_options.keys()),
            )
            .props("dense outlined use-chips")
            .classes("w-full mt-1")
        )

        # --- Progress area ---
        log_area = ui.element("div").classes(
            "w-full mt-3 max-h-[16rem] overflow-y-auto"
        )
        log_area.set_visibility(False)

        # --- Action buttons ---
        action_row = ui.row().classes("w-full justify-end gap-2 mt-4")
        state: dict[str, Any] = {"running": False}

        def _append_log(msg: str) -> None:
            log_area.set_visibility(True)
            with log_area:
                ui.label(msg).classes("text-xs font-mono opacity-80")

        async def _run_pull() -> None:
            if state["running"]:
                return
            state["running"] = True

            # Rebuild action row to show running state
            action_row.clear()
            with action_row:
                ui.button(
                    "Pulling...",
                    on_click=lambda: None,
                ).props("color=primary disabled dense no-caps size=sm")

            log_area.clear()
            log_area.set_visibility(True)

            try:
                from ..config import get_config
                from ..github import fetch as fetch_mod
                from ..github.client import GitHubClient

                cfg = get_config()
                if not cfg.has_classroom:
                    _append_log("ERROR: No classroom configured")
                    return

                selected_slugs: list[str] = assignment_select.value or []
                if not selected_slugs:
                    _append_log("No assignments selected.")
                    return

                selected_ids: set[int] = set(student_select.value or [])
                if not selected_ids:
                    _append_log("No students selected.")
                    return

                gh_assignments = [
                    a for a in gh_assignments_all if a.slug in selected_slugs
                ]
                roster = [s for s in all_students if s.canvas_id in selected_ids]

                _append_log(
                    f"Pulling {len(gh_assignments)} assignment(s), "
                    f"{len(roster)} student(s)..."
                )

                async with GitHubClient() as client:
                    counts = await fetch_mod.pull_gh(
                        client,
                        gh_assignments,
                        roster,
                        on_progress=_append_log,
                    )

                # Summary
                _append_log("")
                _append_log(
                    f"Done: {counts['cloned']} cloned, "
                    f"{counts['updated']} updated, "
                    f"{counts['up_to_date']} up-to-date, "
                    f"{counts['skipped']} skipped, "
                    f"{counts['errors']} errors"
                )
            except Exception as exc:
                _append_log(f"ERROR: {exc}")
            finally:
                state["running"] = False
                action_row.clear()
                with action_row:
                    ui.button("Close", on_click=dialog.close).props(
                        "flat dense no-caps size=sm"
                    )

        async def _run_remove() -> None:
            if state["running"]:
                return
            state["running"] = True
            action_row.clear()
            with action_row:
                ui.button("Removing...", on_click=lambda: None).props(
                    "color=negative disabled dense no-caps size=sm"
                )

            log_area.clear()
            log_area.set_visibility(True)

            try:
                from ..github.fetch import GH_CLASSROOM_DIR

                gh_dir = Path(GH_CLASSROOM_DIR)
                if not gh_dir.exists():
                    _append_log("Nothing to remove — gh-classroom/ not found.")
                    return

                subdirs = [p for p in gh_dir.iterdir() if p.is_dir()]
                if not subdirs:
                    _append_log("gh-classroom/ is already empty.")
                    return

                for p in subdirs:
                    shutil.rmtree(p)
                _append_log(f"Removed {len(subdirs)} folder(s) from gh-classroom/.")
            except Exception as exc:
                _append_log(f"ERROR: {exc}")
            finally:
                state["running"] = False
                action_row.clear()
                with action_row:
                    ui.button("Close", on_click=dialog.close).props(
                        "flat dense no-caps size=sm"
                    )

        with action_row:
            ui.button(
                "Remove All",
                icon="delete",
                on_click=lambda: asyncio.ensure_future(_run_remove()),
            ).props("flat dense no-caps size=sm color=negative")
            ui.space()
            ui.button("Cancel", on_click=dialog.close).props(
                "flat dense no-caps size=sm"
            )
            ui.button(
                "Pull",
                on_click=lambda: asyncio.ensure_future(_run_pull()),
            ).props("color=primary dense no-caps size=sm")
