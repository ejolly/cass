"""Setup wizard and pull-progress pages for the NiceGUI viewer."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from pathlib import Path
from typing import Any

from nicegui import ui

from ..actions.config import parse_canvas_course_url
from .styles import load_styles


def setup_wizard_page(on_complete: Any) -> None:
    """Render the first-time setup form for Canvas.

    Args:
        on_complete: Callback invoked (no args) after config is written and
            the initial pull finishes. The caller should use this to
            navigate to the normal table view.
    """
    load_styles()
    with ui.column().classes("v-setup-container"):
        ui.label("Welcome to cass").classes("v-setup-title")
        ui.label("Connect Canvas, then pull your course data.").classes(
            "v-setup-subtitle"
        )

        # --- Canvas (required) ---
        with ui.card().classes("w-full v-setup-card"):
            ui.label("Canvas LMS").classes("v-setup-card-title")
            ui.label(
                "Paste the course URL exactly as it appears in your browser."
            ).classes("v-setup-card-subtitle")
            canvas_course_url = ui.input(
                label="Course URL",
                placeholder="https://canvas.ucsd.edu/courses/72335",
            ).classes("w-full")
            canvas_token = ui.input(
                label="API Token",
                password=True,
                password_toggle_button=True,
            ).classes("w-full")

        # --- Project directory ---
        cwd = Path.cwd()
        ui.label(f"Project directory: {cwd}").classes("v-setup-path")

        # --- Validation / status ---
        status_label = ui.label("").classes("text-sm")

        async def handle_submit() -> None:
            # Validate Canvas fields
            course_url = (
                canvas_course_url.value.strip() if canvas_course_url.value else ""
            )
            token = canvas_token.value.strip() if canvas_token.value else ""

            if not course_url:
                status_label.text = "Canvas course URL is required."
                status_label.classes(replace="text-sm v-text-error")
                return

            parsed = parse_canvas_course_url(course_url)
            if parsed is None:
                status_label.text = (
                    "Invalid course URL. "
                    "Expected format: https://canvas.ucsd.edu/courses/72335"
                )
                status_label.classes(replace="text-sm v-text-error")
                return

            url, cid = parsed

            if not token:
                status_label.text = "Canvas API token is required."
                status_label.classes(replace="text-sm v-text-error")
                return

            # Write config
            from ..actions.config import reset_config, update_config

            toml_path = cwd / "cass.toml"
            update_config(
                toml_path,
                canvas_base_url=url,
                canvas_course_id=cid,
            )
            reset_config()

            # Save Canvas token (need config loaded first for root path)
            from ..apis.canvas.client import save_token

            save_token(token)

            status_label.text = "Configuration saved. Starting data pull..."
            status_label.classes(replace="text-sm v-text-success")
            await asyncio.sleep(0.3)

            on_complete()

        ui.button(
            "Initialize & Pull Data",
            on_click=handle_submit,
        ).props("color=primary no-caps").classes("px-6 v-setup-submit")

        ui.label(
            "This creates cass.toml and .canvastoken in your project directory."
        ).classes("v-setup-hint")


def pull_progress_page(on_complete: Any) -> None:
    """Render a progress page that runs a full pull and then calls *on_complete*.

    Args:
        on_complete: Called (no args) once the pull finishes successfully.
    """
    load_styles()
    with ui.column().classes("v-progress-container"):
        ui.label("Pulling data...").classes("v-progress-title")

        steps_container = ui.column().classes("w-full gap-1")
        step_labels: dict[str, ui.label] = {}
        error_label = ui.label("").classes("text-sm v-text-error")

        STEP_ORDER = ["students", "assignments", "submissions"]

        with steps_container:
            for step in STEP_ORDER:
                lbl = ui.label(f"  {step}").classes("v-setup-step")
                step_labels[step] = lbl

        progress = ui.linear_progress(value=0, show_value=False).classes("w-full mt-4")

        def on_progress(step: str, detail: str) -> None:
            if step not in step_labels:
                return
            step_labels[step].text = f"  {step}: {detail}"
            step_labels[step].classes(replace="text-sm font-mono opacity-90")
            progress.value = (STEP_ORDER.index(step) + 0.5) / len(STEP_ORDER)

        async def run_pull() -> None:
            try:
                from nicegui import run

                from ..actions.config import get_config
                from ..actions.pull import pull_all

                cfg = get_config()
                loop = asyncio.get_running_loop()

                def threadsafe_progress(step: str, detail: str) -> None:
                    loop.call_soon_threadsafe(on_progress, step, detail)

                await run.io_bound(pull_all, cfg, threadsafe_progress)
                progress.value = 1.0
                for lbl in step_labels.values():
                    lbl.classes(replace="text-sm font-mono v-text-success")
                await asyncio.sleep(0.5)
                on_complete()
            except BaseException as exc:
                error_label.text = f"Error: {exc}"

        # Start pull on page load
        ui.timer(0.3, run_pull, once=True)
