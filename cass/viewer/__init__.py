"""Shared viewer backend — Canvas sync, pending changes, and DB helpers."""

from __future__ import annotations

__docformat__ = "google"
__all__ = ["_canvas_apply", "_canvas_preview"]

import json
from datetime import date, datetime
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from ..canvas.client import CanvasClient

# Type aliases for the pending-changes structure:
#   table -> pk_key -> column -> {"baseline": ..., "current": ...}
_ChangeFields = dict[str, object]
_RowChanges = dict[str, _ChangeFields]
_TableChanges = dict[str, _RowChanges]
_PendingChanges = dict[str, _TableChanges]


# ---------------------------------------------------------------------------
# Pending change tracking
# ---------------------------------------------------------------------------


def _values_equal(a: object, b: object) -> bool:
    """Compare values loosely, handling datetime/string equivalence."""
    if a == b:
        return True
    if isinstance(a, (datetime, date)) and isinstance(b, str):
        return a.isoformat() == b or str(a) == b
    if isinstance(b, (datetime, date)) and isinstance(a, str):
        return b.isoformat() == a or str(b) == a
    return False


def _resolve_row_name(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    pk_key: str,
) -> str:
    """Resolve a pending-change pk_key to a human-readable row name."""
    if table == "canvas_assignments":
        row = conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [int(pk_key)],
        ).fetchone()
        return row[0] if row else pk_key
    if table == "canvas_grades":
        pk = json.loads(pk_key)
        uid, aid = pk["canvas_user_id"], pk["canvas_assignment_id"]
        row = conn.execute(
            "SELECT st.name, ca.name "
            "FROM canvas_students st, canvas_assignments ca "
            "WHERE st.canvas_id = ? AND ca.canvas_id = ?",
            [uid, aid],
        ).fetchone()
        if row:
            return f"{row[0]} — {row[1]}"
        return pk_key
    return pk_key


# ---------------------------------------------------------------------------
# Canvas sync: preview and apply
# ---------------------------------------------------------------------------


def _preview_assignments(
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
                conflict = not _values_equal(live_val, vals["baseline"])
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


def _preview_grades(
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
        assignment_name = _resolve_row_name(conn, "canvas_assignments", str(aid))

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
                    conflict = not _values_equal(live_val, vals["baseline"])
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


def _canvas_preview(
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
            results.extend(_preview_assignments(conn, assignment_changes, c))
        if grade_changes:
            results.extend(_preview_grades(conn, grade_changes, c))

    return {
        "ok": True,
        "changes": results,
        "has_conflicts": any(r.get("conflict") for r in results),
        "has_errors": any("error" in r for r in results),
    }


def _apply_assignments(
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Push pending assignment changes to Canvas."""
    results: list[dict[str, object]] = []
    for pk_key, columns in list(table_changes.items()):
        canvas_id = int(pk_key)
        kwargs = {col: vals["current"] for col, vals in columns.items()}
        try:
            client.update_assignment(canvas_id, **kwargs)
            results.append({"canvas_id": canvas_id, "ok": True})
            del table_changes[pk_key]
        except Exception as e:
            results.append({"canvas_id": canvas_id, "ok": False, "error": str(e)})
    return results


def _apply_grades(
    table_changes: _TableChanges,
    client: CanvasClient,
    conn: duckdb.DuckDBPyConnection,
) -> list[dict[str, object]]:
    """Push pending grade changes to Canvas via bulk update_grades.

    For assignments with ``post_manually=True``, grades are also posted
    (made visible to students) via the Canvas GraphQL API.
    """
    results: list[dict[str, object]] = []

    # Group by assignment_id for bulk push
    by_assignment: dict[int, dict[int, str]] = {}
    pk_keys_by_assignment: dict[int, list[str]] = {}
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        # Use posted_grade for the push
        grade_val = columns.get("posted_grade", {}).get("current")
        if grade_val is not None:
            by_assignment.setdefault(aid, {})[uid] = str(grade_val)
            pk_keys_by_assignment.setdefault(aid, []).append(pk_key)

    # Look up post_manually status
    manual_rows = conn.execute(
        "SELECT canvas_id, post_manually FROM canvas_assignments"
    ).fetchall()
    post_manually_map = {r[0]: r[1] for r in manual_rows}

    pushed_aids: list[int] = []
    for aid, grade_data in by_assignment.items():
        try:
            progress = client.bulk_push_grades(aid, grade_data)
            client.wait_for_progress(progress.id)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": True,
                    "count": len(grade_data),
                }
            )
            pushed_aids.append(aid)
            # Clear successful changes
            for pk_key in pk_keys_by_assignment[aid]:
                table_changes.pop(pk_key, None)
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "error": str(e),
                    "count": len(grade_data),
                }
            )

    # Post grades for manual-post assignments (make visible to students)
    for aid in pushed_aids:
        if not post_manually_map.get(aid):
            continue
        try:
            p = client.post_assignment_grades(aid, graded_only=True)
            if p:
                client.wait_for_progress(p.id)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": True,
                    "action": "posted_to_students",
                }
            )
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "action": "posted_to_students",
                    "error": str(e),
                }
            )

    return results


def _canvas_apply(
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
    with CanvasClient() as c:
        if assignment_changes:
            results.extend(_apply_assignments(assignment_changes, c))
        if grade_changes:
            results.extend(_apply_grades(grade_changes, c, conn))

    # Clean up empty table entries
    if not assignment_changes:
        pending.pop("canvas_assignments", None)
    if not grade_changes:
        pending.pop("canvas_grades", None)

    return {"ok": all(r.get("ok") for r in results), "results": results}
