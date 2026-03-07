"""Pull GH repos modal dialog for the viewer."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from typing import Any

from nicegui import ui


def open_pull_gh_modal() -> None:
    """Open a modal to clone/pull student repos from GitHub Classroom."""
    with ui.dialog() as dialog, ui.card().classes("min-w-[28rem] max-w-[36rem]"):
        dialog.open()

        ui.label("Pull GH Repos").classes("text-lg font-bold mb-2")
        ui.label(
            "Clone or update student repos from GitHub Classroom into gh-classroom/."
        ).classes("text-xs opacity-60 mb-3")

        # --- Controls ---
        with ui.row().classes("w-full gap-4"):
            limit_students = (
                ui.number(
                    "Limit students",
                    value=0,
                    min=0,
                    step=1,
                )
                .props("dense outlined")
                .classes("flex-1")
            )
            limit_assignments = (
                ui.number(
                    "Limit assignments",
                    value=0,
                    min=0,
                    step=1,
                )
                .props("dense outlined")
                .classes("flex-1")
            )

        assignment_filter = (
            ui.input(
                "Assignment slug filter (optional)",
            )
            .props("dense outlined")
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
                from .. import db
                from ..config import get_config
                from ..github import fetch as fetch_mod
                from ..github.client import GitHubClient

                cfg = get_config()
                if not cfg.has_classroom:
                    _append_log("ERROR: No classroom configured")
                    return

                roster = db.load_students()
                assignments = db.load_assignments()
                gh_assignments = [a for a in assignments if a.gh_assignment_slug]

                if not gh_assignments:
                    _append_log("No GitHub-linked assignments found.")
                    return

                # Apply assignment filter
                slug_filter = (assignment_filter.value or "").strip()
                if slug_filter:
                    gh_assignments = [
                        a for a in gh_assignments if slug_filter in a.slug
                    ]
                    if not gh_assignments:
                        _append_log(f"No assignment matching '{slug_filter}'")
                        return

                ls = int(limit_students.value or 0)
                la = int(limit_assignments.value or 0)

                _append_log(
                    f"Pulling {len(gh_assignments)} assignment(s), "
                    f"{len(roster)} student(s)..."
                )

                async with GitHubClient() as client:
                    counts = await fetch_mod.pull_gh(
                        client,
                        gh_assignments,
                        roster,
                        limit_students=ls,
                        limit_assignments=la,
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

        with action_row:
            ui.button("Cancel", on_click=dialog.close).props(
                "flat dense no-caps size=sm"
            )
            ui.button(
                "Start",
                on_click=lambda: asyncio.ensure_future(_run_pull()),
            ).props("color=primary dense no-caps size=sm")
