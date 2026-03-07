"""Setup wizard and pull-progress pages for the NiceGUI viewer."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
import re
from pathlib import Path
from typing import Any

from nicegui import ui

from .styles import load_styles

# Matches Canvas course URLs like https://canvas.ucsd.edu/courses/72335
_CANVAS_COURSE_URL_RE = re.compile(
    r"^(https?://[^/]+)/courses/(\d+)",
)


def _parse_canvas_url(raw: str) -> tuple[str, int] | None:
    """Extract (base_url, course_id) from a Canvas course URL.

    Returns None if the URL doesn't match the expected pattern.
    """
    m = _CANVAS_COURSE_URL_RE.match(raw.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def setup_wizard_page(on_complete: Any) -> None:
    """Render the first-time setup form. Canvas is required, GitHub optional.

    Args:
        on_complete: Callback invoked (no args) after config is written and
            the initial pull finishes. The caller should use this to
            navigate to the normal table view.
    """
    load_styles()
    with ui.column().classes("v-setup-container"):
        ui.label("Welcome to cass").classes("v-setup-title")
        ui.label("Configure your course to get started.").classes("v-setup-subtitle")

        # --- Canvas (required) ---
        with ui.card().classes("w-full"):
            ui.label("Canvas LMS").classes("v-setup-card-title")
            canvas_course_url = ui.input(
                label="Course URL",
                placeholder="https://canvas.ucsd.edu/courses/72335",
            ).classes("w-full")
            canvas_token = ui.input(
                label="API Token",
                password=True,
                password_toggle_button=True,
            ).classes("w-full")

        # --- GitHub Classroom (optional) ---
        with ui.expansion(
            "GitHub Classroom",
            caption="Optional",
            icon="school",
        ).classes("w-full v-setup-expansion"):
            gh_classroom_id = ui.input(
                label="Classroom ID",
                placeholder="299058",
            ).classes("w-full")
            gh_org = ui.input(
                label="Organization",
                placeholder="psyc-201",
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

            parsed = _parse_canvas_url(course_url)
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

            # Optional GitHub fields
            gh_id = 0
            org = ""
            gh_id_raw = gh_classroom_id.value.strip() if gh_classroom_id.value else ""
            org_raw = gh_org.value.strip() if gh_org.value else ""
            if gh_id_raw and org_raw:
                try:
                    gh_id = int(gh_id_raw)
                except ValueError:
                    status_label.text = "Classroom ID must be a number."
                    status_label.classes(replace="text-sm v-text-error")
                    return

                org = org_raw

            # Write config
            from ..config import reset_config, write_config

            toml_path = cwd / "cass.toml"
            write_config(toml_path, gh_id, org, url, cid)
            reset_config()

            # Save Canvas token (need config loaded first for root path)
            from ..canvas.client import save_token

            save_token(token)

            status_label.text = "Configuration saved. Starting data pull..."
            status_label.classes(replace="text-sm v-text-success")
            await asyncio.sleep(0.3)

            on_complete()

        ui.button(
            "Initialize & Pull Data",
            on_click=handle_submit,
        ).props("color=primary no-caps").classes("px-6")

        ui.label(
            "This creates cass.toml and canvas-token.txt in your project directory."
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

        STEP_ORDER = ["students", "assignments", "submissions", "grades"]

        with steps_container:
            for step in STEP_ORDER:
                lbl = ui.label(f"  {step}").classes("v-setup-step")
                step_labels[step] = lbl

        progress = ui.linear_progress(value=0, show_value=False).classes("w-full mt-4")

        def on_progress(step: str, detail: str) -> None:
            if step in step_labels:
                step_labels[step].text = f"  {step}: {detail}"
                step_labels[step].classes(replace="text-sm font-mono opacity-90")
            idx = STEP_ORDER.index(step) if step in STEP_ORDER else 0
            progress.value = (idx + 0.5) / len(STEP_ORDER)

        async def run_pull() -> None:
            try:
                from ..config import get_config
                from ..pull import pull_all_async

                cfg = get_config()
                await pull_all_async(cfg, on_progress=on_progress)
                progress.value = 1.0
                for lbl in step_labels.values():
                    lbl.classes(replace="text-sm font-mono v-text-success")
                await asyncio.sleep(0.5)
                on_complete()
            except BaseException as exc:
                error_label.text = f"Error: {exc}"

        # Start pull on page load
        ui.timer(0.3, run_pull, once=True)
