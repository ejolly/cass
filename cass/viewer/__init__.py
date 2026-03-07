"""Viewer backend — Canvas sync orchestration with pending-change tracking."""

from __future__ import annotations

__docformat__ = "google"
__all__ = ["canvas_apply", "canvas_preview", "values_equal"]

import json
from typing import TYPE_CHECKING

import duckdb

from ..canvas.sync import (
    is_valid_grade,
    push_assignments,
    push_grades,
    resolve_row_name,
    values_equal,
)
from ..db import mark_synced_assignments, mark_synced_grades

if TYPE_CHECKING:
    from ..canvas.client import CanvasClient

# Type aliases for the pending-changes structure:
#   table -> pk_key -> column -> {"baseline": ..., "current": ...}
_ChangeFields = dict[str, object]
_RowChanges = dict[str, _ChangeFields]
_TableChanges = dict[str, _RowChanges]
_PendingChanges = dict[str, _TableChanges]


# ---------------------------------------------------------------------------
# Canvas sync: preview and apply
# ---------------------------------------------------------------------------


def preview_assignments(
    conn: duckdb.DuckDBPyConnection,
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending assignment changes against live Canvas state."""
    results: list[dict[str, object]] = []
    for pk_key, columns in table_changes.items():
        canvas_id = int(pk_key)
        name_row = conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [canvas_id],
        ).fetchone()
        assignment_name = name_row[0] if name_row else f"ID {canvas_id}"

        try:
            live = client.get_assignment(canvas_id)
            for col, vals in columns.items():
                live_val = getattr(live, col, None)
                conflict = not values_equal(live_val, vals["baseline"])
                results.append(
                    {
                        "table": "canvas_assignments",
                        "canvas_id": canvas_id,
                        "name": assignment_name,
                        "column": col,
                        "baseline": vals["baseline"],
                        "current": vals["current"],
                        "live": live_val,
                        "conflict": conflict,
                    }
                )
        except Exception as e:
            results.append(
                {
                    "table": "canvas_assignments",
                    "canvas_id": canvas_id,
                    "name": assignment_name,
                    "error": str(e),
                }
            )
    return results


def preview_grades(
    conn: duckdb.DuckDBPyConnection,
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending grade changes against live Canvas submissions."""
    results: list[dict[str, object]] = []

    # Group changes by assignment_id for efficient fetching
    by_assignment: dict[int, list[tuple[int, _RowChanges]]] = {}
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        by_assignment.setdefault(aid, []).append((uid, columns))

    for aid, student_changes in by_assignment.items():
        assignment_name = resolve_row_name(conn, "canvas_assignments", str(aid))

        try:
            live_subs = client.list_submissions(aid)
            live_by_user = {s.user_id: s for s in live_subs}

            for uid, columns in student_changes:
                student_row = conn.execute(
                    "SELECT name FROM canvas_students WHERE canvas_id = ?",
                    [uid],
                ).fetchone()
                student_name = student_row[0] if student_row else f"User {uid}"

                live_sub = live_by_user.get(uid)
                for col, vals in columns.items():
                    live_val = None
                    if live_sub:
                        if col == "posted_grade":
                            live_val = live_sub.grade
                        elif col == "score":
                            live_val = live_sub.score
                    conflict = not values_equal(live_val, vals["baseline"])
                    results.append(
                        {
                            "table": "canvas_grades",
                            "canvas_assignment_id": aid,
                            "canvas_user_id": uid,
                            "name": f"{student_name} — {assignment_name}",
                            "column": col,
                            "baseline": vals["baseline"],
                            "current": vals["current"],
                            "live": live_val,
                            "conflict": conflict,
                        }
                    )
        except Exception as e:
            results.append(
                {
                    "table": "canvas_grades",
                    "canvas_assignment_id": aid,
                    "name": assignment_name,
                    "error": str(e),
                }
            )

    return results


def canvas_preview(
    conn: duckdb.DuckDBPyConnection,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Compare pending changes against live Canvas state (dry-run)."""
    from ..canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "changes": []}

    results: list[dict[str, object]] = []
    with CanvasClient() as c:
        if assignment_changes:
            results.extend(preview_assignments(conn, assignment_changes, c))
        if grade_changes:
            results.extend(preview_grades(conn, grade_changes, c))

    return {
        "ok": True,
        "changes": results,
        "has_conflicts": any(r.get("conflict") for r in results),
        "has_errors": any("error" in r for r in results),
    }


def _extract_assignment_updates(
    table_changes: _TableChanges,
) -> dict[int, dict[str, object]]:
    """Convert pending assignment changes to {canvas_id: {field: value}}."""
    updates: dict[int, dict[str, object]] = {}
    for pk_key, columns in table_changes.items():
        canvas_id = int(pk_key)
        updates[canvas_id] = {col: vals["current"] for col, vals in columns.items()}
    return updates


def _extract_grade_data(
    table_changes: _TableChanges,
) -> tuple[dict[int, dict[int, str]], dict[int, list[str]]]:
    """Convert pending grade changes to grade_data_by_aid and pk_keys_by_aid."""
    grade_data_by_aid: dict[int, dict[int, str]] = {}
    pk_keys_by_aid: dict[int, list[str]] = {}
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        grade_val = columns.get("posted_grade", {}).get("current")
        if grade_val is not None and is_valid_grade(str(grade_val)):
            grade_data_by_aid.setdefault(aid, {})[uid] = str(grade_val)
            pk_keys_by_aid.setdefault(aid, []).append(pk_key)
    return grade_data_by_aid, pk_keys_by_aid


def canvas_apply(
    conn: duckdb.DuckDBPyConnection,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Push pending changes to Canvas and clear them on success."""
    from ..canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "results": []}

    results: list[dict[str, object]] = []
    synced_assignment_ids: list[int] = []
    synced_grade_keys: list[tuple[int, int]] = []

    with CanvasClient() as c:
        if assignment_changes:
            updates = _extract_assignment_updates(assignment_changes)
            a_results = push_assignments(c, updates)
            results.extend(a_results)
            # Clear successful entries from pending
            for r in a_results:
                if r.get("ok"):
                    cid = int(r["canvas_id"])  # type: ignore[arg-type]
                    assignment_changes.pop(str(cid), None)
                    synced_assignment_ids.append(cid)

        if grade_changes:
            grade_data, pk_keys = _extract_grade_data(grade_changes)
            g_results = push_grades(c, conn, grade_data)
            results.extend(g_results)
            # Clear successful entries from pending
            for r in g_results:
                if r.get("ok") and "action" not in r:
                    aid: int = r["canvas_assignment_id"]  # type: ignore[assignment]
                    for pk_key in pk_keys.get(aid, []):
                        grade_changes.pop(pk_key, None)
                        pk = json.loads(pk_key)
                        synced_grade_keys.append(
                            (pk["canvas_user_id"], pk["canvas_assignment_id"])
                        )

    # Update synced shadow tables for successfully pushed entries
    if synced_assignment_ids:
        mark_synced_assignments(conn, synced_assignment_ids)
    if synced_grade_keys:
        mark_synced_grades(conn, synced_grade_keys)

    # Clean up empty table entries
    if not assignment_changes:
        pending.pop("canvas_assignments", None)
    if not grade_changes:
        pending.pop("canvas_grades", None)

    return {"ok": all(r.get("ok") for r in results), "results": results}
