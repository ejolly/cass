"""Viewer CRUD actions — pure business logic shared by CLI and viewer modals.

All functions here are UI-free: they operate on DuckDB connections, dicts, and
domain types.  Modal classes and CLI commands import from here; nothing in this
module imports NiceGUI.
"""

from __future__ import annotations

__docformat__ = "google"

import json
from html import escape
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from ..canvas.client import CanvasClient
    from .config import PendingChanges

# ---------------------------------------------------------------------------
# Assignment validation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Assignment CRUD
# ---------------------------------------------------------------------------


def list_assignments_for_select(
    conn: duckdb.DuckDBPyConnection,
) -> dict[int, str]:
    """Return {canvas_id: name} for all assignments, sorted by name."""
    rows = conn.execute(
        "SELECT canvas_id, name FROM canvas_assignments ORDER BY name"
    ).fetchall()
    return {int(r[0]): r[1] for r in rows}


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

    # Resolve group name -> Canvas group ID
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


def delete_local_assignment(
    conn: duckdb.DuckDBPyConnection,
    canvas_id: int,
) -> None:
    """Delete an assignment and all related rows from the local DB."""
    conn.execute(
        "DELETE FROM canvas_grades WHERE canvas_assignment_id = ?", [canvas_id]
    )
    conn.execute(
        "DELETE FROM canvas_submissions WHERE canvas_assignment_id = ?", [canvas_id]
    )
    conn.execute(
        "DELETE FROM _canvas_grades_synced WHERE canvas_assignment_id = ?", [canvas_id]
    )
    conn.execute(
        "DELETE FROM _canvas_assignments_synced WHERE canvas_id = ?", [canvas_id]
    )
    conn.execute("DELETE FROM canvas_assignments WHERE canvas_id = ?", [canvas_id])


def delete_assignment_from_canvas(
    conn: duckdb.DuckDBPyConnection,
    canvas_id: int,
    client: CanvasClient,
) -> dict[str, object]:
    """Delete an assignment from Canvas (if remote) and locally.

    Local-only assignments (negative IDs) skip the Canvas API call.
    On Canvas API error, the local deletion still proceeds.

    Returns:
        Result dict with ``ok`` and optionally ``error``.
    """
    canvas_error: str | None = None
    if canvas_id > 0:
        try:
            client.delete_assignment(canvas_id)
        except Exception as e:
            canvas_error = str(e)

    delete_local_assignment(conn, canvas_id)

    if canvas_error:
        return {"ok": False, "error": canvas_error}
    return {"ok": True}


def purge_pending_for_assignment(
    pending: PendingChanges,
    canvas_id: int,
) -> None:
    """Remove any pending changes referencing a deleted assignment."""
    # canvas_assignments: pk_key is str(canvas_id)
    assign_pending = pending.get("canvas_assignments", {})
    assign_pending.pop(str(canvas_id), None)
    if not assign_pending:
        pending.pop("canvas_assignments", None)

    # canvas_grades: pk_key is JSON with canvas_assignment_id
    grade_pending = pending.get("canvas_grades", {})
    to_remove = [
        pk_key
        for pk_key in grade_pending
        if json.loads(pk_key).get("canvas_assignment_id") == canvas_id
    ]
    for pk_key in to_remove:
        grade_pending.pop(pk_key, None)
    if not grade_pending:
        pending.pop("canvas_grades", None)


# ---------------------------------------------------------------------------
# Push preview HTML
# ---------------------------------------------------------------------------


def build_preview_html(
    assignment_changes: list[dict[str, object]],
    grade_changes: list[dict[str, object]],
    has_conflicts: bool,
) -> str:
    """Build HTML for the push preview tables."""
    parts: list[str] = []

    if assignment_changes:
        parts.append("<h4 class='v-preview-header'>Assignment changes</h4>")
        parts.append('<table class="push-table"><thead><tr>')
        for h in ("Assignment", "Field", "On Canvas", "New value"):
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for ch in assignment_changes:
            cls = (
                "error-row"
                if "error" in ch
                else "conflict-row"
                if ch.get("conflict")
                else ""
            )
            parts.append(f'<tr class="{cls}">')
            if "error" in ch:
                name = escape(str(ch.get("name", "")))
                err = escape(str(ch.get("error", "")))
                parts.append(f'<td colspan="4" class="v-text-error">{name}: {err}</td>')
            else:
                name = escape(str(ch.get("name", "")))
                col = escape(str(ch.get("column", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}</td>")
                parts.append(f"<td>{col}{warn}</td>")
                parts.append(f'<td class="opacity-50">{live}</td>')
                parts.append(f'<td class="font-semibold">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if grade_changes:
        parts.append("<h4 class='v-preview-header-spaced'>Grade changes</h4>")
        parts.append('<table class="push-table"><thead><tr>')
        for h in ("Student \u2014 Assignment", "On Canvas", "New grade"):
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for ch in grade_changes:
            cls = (
                "error-row"
                if "error" in ch
                else "conflict-row"
                if ch.get("conflict")
                else ""
            )
            parts.append(f'<tr class="{cls}">')
            if "error" in ch:
                name = escape(str(ch.get("name", "")))
                err = escape(str(ch.get("error", "")))
                parts.append(f'<td colspan="3" class="v-text-error">{name}: {err}</td>')
            else:
                name = escape(str(ch.get("name", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}{warn}</td>")
                parts.append(f'<td class="opacity-50">{live}</td>')
                parts.append(f'<td class="font-semibold">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if has_conflicts:
        parts.append(
            '<div class="v-conflict-warning">'
            "\u26a0 Some Canvas values differ from when you "
            "last pulled. Pushing will overwrite.</div>"
        )

    return "".join(parts)
