"""Create Assignment modal dialog for the viewer."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, Any

import duckdb
from nicegui import ui

from ..db import get_assignment_groups
from .grid import notify

if TYPE_CHECKING:
    from ..canvas.client import CanvasClient


def validate_assignment_fields(*, name: str, points: float | None) -> list[str]:
    """Validate assignment creation fields.

    Args:
        name: Assignment name.
        points: Points possible (from ui.number).

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    if not name.strip():
        errors.append("Name is required.")
    if points is not None and points < 0:
        errors.append("Points must be ≥ 0.")
    return errors


def create_local_assignment(
    conn: duckdb.DuckDBPyConnection,
    *,
    name: str,
    points_possible: float = 0.0,
    due_at: str | None = None,
    published: bool = False,
    assignment_group: str = "",
) -> int:
    """Insert a locally-created assignment with a negative canvas_id.

    Negative IDs distinguish local assignments from Canvas-sourced ones.

    Returns:
        The generated (negative) canvas_id.
    """
    row = conn.execute("SELECT MIN(canvas_id) FROM canvas_assignments").fetchone()
    min_id = row[0] if row and row[0] is not None else 0
    new_id = min(min_id, 0) - 1

    conn.execute(
        "INSERT INTO canvas_assignments "
        "(canvas_id, name, points_possible, due_at, published, assignment_group) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [new_id, name, points_possible, due_at, published, assignment_group],
    )
    return new_id


def replace_local_id(
    conn: duckdb.DuckDBPyConnection,
    local_id: int,
    real_id: int,
) -> None:
    """Replace a local (negative) canvas_id with the real Canvas-assigned ID."""
    row = conn.execute(
        "SELECT name, points_possible, due_at, published, assignment_group, "
        "post_manually FROM canvas_assignments WHERE canvas_id = ?",
        [local_id],
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM canvas_assignments WHERE canvas_id = ?", [local_id])
    conn.execute(
        "INSERT INTO canvas_assignments "
        "(canvas_id, name, points_possible, due_at, published, "
        "assignment_group, post_manually) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [real_id, *row],
    )


def push_new_assignment(
    conn: duckdb.DuckDBPyConnection,
    local_id: int,
    client: CanvasClient,
) -> dict[str, object]:
    """Push a locally-created assignment to Canvas and update the local DB.

    Args:
        conn: DuckDB connection.
        local_id: The negative local canvas_id.
        client: Authenticated Canvas API client.

    Returns:
        Result dict with ``ok``, ``canvas_id``, and optionally ``error``.
    """
    row = conn.execute(
        "SELECT name, points_possible, due_at, published, assignment_group "
        "FROM canvas_assignments WHERE canvas_id = ?",
        [local_id],
    ).fetchone()
    if row is None:
        return {"ok": False, "error": "Assignment not found"}

    name, points, due_at, published, group_name = row

    # Resolve group name → Canvas group ID
    group_id: int | None = None
    if group_name:
        groups = client.list_assignment_groups()
        for g in groups:
            if g.name == group_name:
                group_id = g.id
                break

    try:
        created = client.create_assignment(
            name,
            points_possible=float(points),
            due_at=str(due_at) if due_at else None,
            published=bool(published),
            assignment_group_id=group_id,
        )
        replace_local_id(conn, local_id, created.id)
        return {"ok": True, "canvas_id": created.id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_create_assignment_modal(
    conn: duckdb.DuckDBPyConnection,
    grid_container: dict[str, Any],
    current_table: dict[str, str],
    load_table: Any,
) -> None:
    """Open a modal to create a new local assignment."""
    group_values = get_assignment_groups(conn)

    with (
        ui.dialog() as dialog,
        ui.card().classes("v-modal-card-scroll"),
    ):
        dialog.open()

        ui.label("Create Assignment").classes("v-modal-title")
        ui.label(
            "Add a local assignment to canvas_assignments. "
            "Use Push to Canvas to sync it upstream."
        ).classes("v-modal-subtitle")

        name_input = (
            ui.input(label="Name", placeholder="e.g. Homework 3")
            .props("dense outlined")
            .classes("w-full")
        )

        points_input = (
            ui.number(label="Points Possible", value=0, min=0, format="%.1f")
            .props("dense outlined")
            .classes("w-full mt-1")
        )

        with (
            ui.input("Due Date")
            .props("dense outlined")
            .classes("w-full mt-1") as due_input
        ):
            with (
                ui.menu().props("no-parent-event") as menu,
                ui.date().bind_value(due_input),
                ui.row().classes("justify-end"),
            ):
                ui.button("Close", on_click=menu.close).props("flat")
            with due_input.add_slot("append"):
                ui.icon("edit_calendar").on("click", menu.open).classes(
                    "cursor-pointer"
                )

        group_options = {g: g for g in group_values} if group_values else {}
        group_select = (
            ui.select(
                options=group_options,
                label="Assignment Group",
                value=None,
                with_input=True,
                new_value_mode="add-unique",
            )
            .props("dense outlined")
            .classes("w-full mt-1")
        )

        published_toggle = ui.switch("Published", value=False).classes("mt-1")

        error_label = ui.label("").classes("v-modal-error")
        error_label.set_visibility(False)

        status_label = ui.label("").classes("v-modal-status")
        status_label.set_visibility(False)

        async def _on_create() -> None:
            name_val = name_input.value or ""
            pts = points_input.value
            errors = validate_assignment_fields(name=name_val, points=pts)
            if errors:
                error_label.text = " · ".join(errors)
                error_label.set_visibility(True)
                return

            error_label.set_visibility(False)
            due_val = due_input.value or None
            group_val = group_select.value or ""

            local_id = create_local_assignment(
                conn,
                name=name_val.strip(),
                points_possible=pts or 0.0,
                due_at=due_val if due_val and due_val.strip() else None,
                published=published_toggle.value,
                assignment_group=group_val,
            )

            # Auto-push to Canvas
            status_label.text = "Pushing to Canvas..."
            status_label.set_visibility(True)
            create_btn.props("disabled")

            import asyncio

            from ..canvas.client import CanvasClient

            def _do_push() -> dict[str, object]:
                with CanvasClient() as client:
                    return push_new_assignment(conn, local_id, client)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _do_push)

            if result["ok"]:
                dialog.close()
                notify(
                    f"Created assignment: {name_val.strip()} "
                    f"(Canvas ID {result['canvas_id']})"
                )
            else:
                status_label.text = f"Canvas error: {result['error']}"
                status_label.classes("v-text-error", remove="v-modal-status")
                create_btn.props(remove="disabled")
                notify(
                    f"Created locally but Canvas push failed: {result['error']}",
                    "warning",
                )

            # Refresh grid
            tbl = current_table["name"]
            if tbl in ("canvas_assignments", "canvas_grades"):
                load_table(tbl)

        with ui.row().classes("v-modal-actions"):
            ui.button("Cancel", on_click=dialog.close).props(
                "flat dense no-caps size=sm"
            )
            create_btn = ui.button("Create", on_click=_on_create).props(
                "color=primary dense no-caps size=sm"
            )
