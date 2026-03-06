"""Canvas sync primitives — push grades and assignments to Canvas LMS.

Shared by both the CLI (``cass gradebook push``) and the NiceGUI viewer.
"""

from __future__ import annotations

__docformat__ = "google"

import json
from datetime import date, datetime
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from .client import CanvasClient


def values_equal(a: object, b: object) -> bool:
    """Compare values loosely, handling datetime/string equivalence."""
    if a == b:
        return True
    if isinstance(a, (datetime, date)) and isinstance(b, str):
        return a.isoformat() == b or str(a) == b
    if isinstance(b, (datetime, date)) and isinstance(a, str):
        return b.isoformat() == a or str(b) == a
    return False


def resolve_row_name(
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
# Core push functions
# ---------------------------------------------------------------------------


def push_grades(
    client: CanvasClient,
    conn: duckdb.DuckDBPyConnection,
    grade_data_by_aid: dict[int, dict[int, str]],
) -> list[dict[str, object]]:
    """Bulk-push grades to Canvas, handling progress tracking and post_manually.

    Args:
        client: Authenticated Canvas API client.
        conn: DuckDB connection (for post_manually lookup).
        grade_data_by_aid: ``{assignment_id: {user_id: grade_string}}``.

    Returns:
        List of result dicts with ``ok``, ``canvas_assignment_id``, ``count``,
        and optionally ``error`` or ``action`` keys.
    """
    results: list[dict[str, object]] = []
    if not grade_data_by_aid:
        return results

    # Look up post_manually status
    manual_rows = conn.execute(
        "SELECT canvas_id, post_manually FROM canvas_assignments"
    ).fetchall()
    post_manually_map = {r[0]: r[1] for r in manual_rows}

    pushed_aids: list[int] = []
    for aid, grade_data in grade_data_by_aid.items():
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


def push_assignments(
    client: CanvasClient,
    updates_by_id: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    """Push assignment field updates to Canvas.

    Args:
        client: Authenticated Canvas API client.
        updates_by_id: ``{canvas_assignment_id: {field: new_value}}``.

    Returns:
        List of result dicts with ``ok``, ``canvas_id``, and optionally ``error``.
    """
    results: list[dict[str, object]] = []
    for canvas_id, kwargs in updates_by_id.items():
        try:
            client.update_assignment(canvas_id, **kwargs)
            results.append({"canvas_id": canvas_id, "ok": True})
        except Exception as e:
            results.append({"canvas_id": canvas_id, "ok": False, "error": str(e)})
    return results
