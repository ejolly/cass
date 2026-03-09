"""Canvas sync state and shared preview/apply workflows."""

from __future__ import annotations

__docformat__ = "google"

import json
from typing import TYPE_CHECKING

import sqlite_utils

from ..apis.canvas.sync import (
    is_valid_grade,
    push_assignments,
    push_grades,
    resolve_row_name,
    values_equal,
)
from .catalog import PULL_GUARDED_TABLES
from .core import _connection, get_db

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient

_ChangeFields = dict[str, object]
_RowChanges = dict[str, _ChangeFields]
_TableChanges = dict[str, _RowChanges]
_PendingChanges = dict[str, _TableChanges]


def snapshot_canvas_synced(sdb: sqlite_utils.Database | None = None) -> None:
    """Copy current canvas tables into synced shadow tables.

    Called after a successful pull to record what Canvas has.
    """
    c = sdb or get_db()
    c.execute("""
        INSERT OR REPLACE INTO _canvas_assignments_synced
            (canvas_id, name, points_possible, due_at, published)
        SELECT canvas_id, name, points_possible, due_at, published
        FROM canvas_assignments
    """)
    c.execute("""
        INSERT OR REPLACE INTO _canvas_grades_synced
            (canvas_user_id, canvas_assignment_id, posted_grade)
        SELECT canvas_user_id, canvas_assignment_id, posted_grade
        FROM canvas_grades
    """)
    _connection(c).commit()


def mark_synced_assignments(
    sdb: sqlite_utils.Database,
    canvas_ids: list[int],
) -> None:
    """Update synced shadow for specific assignments after push."""
    for cid in canvas_ids:
        sdb.execute(
            """
            INSERT OR REPLACE INTO _canvas_assignments_synced
                (canvas_id, name, points_possible, due_at, published)
            SELECT canvas_id, name, points_possible, due_at, published
            FROM canvas_assignments WHERE canvas_id = ?
            """,
            [cid],
        )
    if canvas_ids:
        _connection(sdb).commit()


def mark_synced_grades(
    sdb: sqlite_utils.Database,
    keys: list[tuple[int, int]],
) -> None:
    """Update synced shadow for specific grade rows after push."""
    for uid, aid in keys:
        sdb.execute(
            """
            INSERT OR REPLACE INTO _canvas_grades_synced
                (canvas_user_id, canvas_assignment_id, posted_grade)
            SELECT canvas_user_id, canvas_assignment_id, posted_grade
            FROM canvas_grades
            WHERE canvas_user_id = ? AND canvas_assignment_id = ?
            """,
            [uid, aid],
        )
    if keys:
        _connection(sdb).commit()


def get_pending_changes(
    sdb: sqlite_utils.Database | None = None,
) -> dict[str, dict[str, dict[str, dict[str, object]]]]:
    """Compute pending changes by diffing main tables against synced shadows.

    Returns the same ``PendingChanges`` structure used by the viewer:
    ``{table: {pk_key: {column: {"baseline": ..., "current": ...}}}}``.
    """
    c = sdb or get_db()
    pending: dict[str, dict[str, dict[str, dict[str, object]]]] = {}

    # Synced tables may not exist yet (pre-v10 DB or no pull)
    existing = {t.name for t in c.tables}

    # --- Assignments ---
    if "_canvas_assignments_synced" in existing:
        rows = c.execute("""
            SELECT m.canvas_id, m.name, s.name,
                   m.points_possible, s.points_possible,
                   m.due_at, s.due_at,
                   m.published, s.published
            FROM canvas_assignments m
            JOIN _canvas_assignments_synced s
              ON m.canvas_id = s.canvas_id
            WHERE m.name != s.name
               OR m.points_possible != s.points_possible
               OR IFNULL(m.due_at, '') != IFNULL(s.due_at, '')
               OR m.published != s.published
        """).fetchall()

        for row in rows:
            (cid, m_name, s_name, m_pts, s_pts, m_due, s_due, m_pub, s_pub) = row
            pk_key = str(cid)
            cols: dict[str, dict[str, object]] = {}
            if m_name != s_name:
                cols["name"] = {"baseline": s_name, "current": m_name}
            if m_pts != s_pts:
                cols["points_possible"] = {"baseline": s_pts, "current": m_pts}
            if m_due != s_due:
                cols["due_at"] = {"baseline": s_due, "current": m_due}
            if m_pub != s_pub:
                cols["published"] = {"baseline": s_pub, "current": m_pub}
            if cols:
                pending.setdefault("canvas_assignments", {})[pk_key] = cols

    # --- Grades ---
    if "_canvas_grades_synced" in existing:
        rows = c.execute("""
            SELECT m.canvas_user_id, m.canvas_assignment_id,
                   m.posted_grade, s.posted_grade
            FROM canvas_grades m
            JOIN _canvas_grades_synced s
              ON m.canvas_user_id = s.canvas_user_id
             AND m.canvas_assignment_id = s.canvas_assignment_id
            WHERE m.posted_grade != s.posted_grade
        """).fetchall()

        for uid, aid, m_grade, s_grade in rows:
            pk = {"canvas_assignment_id": aid, "canvas_user_id": uid}
            pk_key = json.dumps(pk, sort_keys=True)
            pending.setdefault("canvas_grades", {})[pk_key] = {
                "posted_grade": {
                    "baseline": s_grade,
                    "current": m_grade,
                },
            }

    return pending


def get_pull_blocking_tables(
    sdb: sqlite_utils.Database | None = None,
) -> list[str]:
    """Return Canvas-managed working tables with pending local edits."""
    pending = get_pending_changes(sdb)
    return sorted(table for table in PULL_GUARDED_TABLES if pending.get(table))


def pull_block_reason(sdb: sqlite_utils.Database | None = None) -> str | None:
    """Describe why pull is blocked, or return ``None`` when pull is allowed."""
    blocking = get_pull_blocking_tables(sdb)
    if not blocking:
        return None
    tables = ", ".join(blocking)
    return (
        "Pull blocked: local Canvas-managed changes would be overwritten in "
        f"{tables}. Run `cass push` or `cass revert` first."
    )


def preview_assignments(
    conn: sqlite_utils.Database,
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending assignment changes against live Canvas state."""
    results: list[dict[str, object]] = []
    for pk_key, columns in table_changes.items():
        canvas_id = int(pk_key)
        assignment_name = resolve_row_name(conn, "canvas_assignments", pk_key)
        try:
            live = client.get_assignment(canvas_id)
            for col, vals in columns.items():
                live_val = getattr(live, col, None)
                results.append(
                    {
                        "table": "canvas_assignments",
                        "canvas_id": canvas_id,
                        "name": assignment_name,
                        "column": col,
                        "baseline": vals["baseline"],
                        "current": vals["current"],
                        "live": live_val,
                        "conflict": not values_equal(live_val, vals["baseline"]),
                    }
                )
        except Exception as exc:
            results.append(
                {
                    "table": "canvas_assignments",
                    "canvas_id": canvas_id,
                    "name": assignment_name,
                    "error": str(exc),
                }
            )
    return results


def preview_grades(
    conn: sqlite_utils.Database,
    table_changes: _TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending grade changes against live Canvas submissions."""
    results: list[dict[str, object]] = []
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
            live_by_user = {submission.user_id: submission for submission in live_subs}
            for uid, columns in student_changes:
                student_row = conn.execute(
                    "SELECT name FROM canvas_students WHERE canvas_id = ?",
                    [uid],
                ).fetchone()
                student_name = str(student_row[0]) if student_row else f"User {uid}"
                live_sub = live_by_user.get(uid)
                for col, vals in columns.items():
                    live_val = None
                    if live_sub is not None:
                        if col == "posted_grade":
                            live_val = live_sub.grade
                        elif col == "score":
                            live_val = live_sub.score
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
                            "conflict": not values_equal(live_val, vals["baseline"]),
                        }
                    )
        except Exception as exc:
            results.append(
                {
                    "table": "canvas_grades",
                    "canvas_assignment_id": aid,
                    "name": assignment_name,
                    "error": str(exc),
                }
            )
    return results


def canvas_preview(
    conn: sqlite_utils.Database,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Compare pending changes against live Canvas state."""
    from ..apis.canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "changes": []}

    results: list[dict[str, object]] = []
    with CanvasClient() as client:
        if assignment_changes:
            results.extend(preview_assignments(conn, assignment_changes, client))
        if grade_changes:
            results.extend(preview_grades(conn, grade_changes, client))

    return {
        "ok": True,
        "changes": results,
        "has_conflicts": any(result.get("conflict") for result in results),
        "has_errors": any("error" in result for result in results),
    }


def _extract_assignment_updates(
    table_changes: _TableChanges,
) -> dict[int, dict[str, object]]:
    updates: dict[int, dict[str, object]] = {}
    for pk_key, columns in table_changes.items():
        updates[int(pk_key)] = {col: vals["current"] for col, vals in columns.items()}
    return updates


def _extract_grade_data(
    table_changes: _TableChanges,
) -> tuple[dict[int, dict[int, str]], dict[int, list[str]]]:
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
    conn: sqlite_utils.Database,
    pending: _PendingChanges,
) -> dict[str, object]:
    """Push pending changes to Canvas and clear synced rows on success."""
    from ..apis.canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "results": []}

    results: list[dict[str, object]] = []
    overall_ok = True
    synced_assignment_ids: list[int] = []
    synced_grade_keys: list[tuple[int, int]] = []
    with CanvasClient() as client:
        if assignment_changes:
            assignment_results = push_assignments(
                client, _extract_assignment_updates(assignment_changes)
            )
            results.extend(assignment_results)
            for result in assignment_results:
                if not result.get("ok"):
                    overall_ok = False
                if result.get("ok"):
                    canvas_id = int(result["canvas_id"])  # type: ignore[arg-type]
                    assignment_changes.pop(str(canvas_id), None)
                    synced_assignment_ids.append(canvas_id)

        if grade_changes:
            grade_data, pk_keys = _extract_grade_data(grade_changes)
            grade_results = push_grades(client, conn, grade_data)
            results.extend(grade_results)
            for result in grade_results:
                if not result.get("ok"):
                    overall_ok = False
                if result.get("ok") and "action" not in result:
                    aid: int = result["canvas_assignment_id"]  # type: ignore[assignment]
                    for pk_key in pk_keys.get(aid, []):
                        grade_changes.pop(pk_key, None)
                        pk = json.loads(pk_key)
                        synced_grade_keys.append(
                            (pk["canvas_user_id"], pk["canvas_assignment_id"])
                        )

    if not assignment_changes:
        pending.pop("canvas_assignments", None)
    if not grade_changes:
        pending.pop("canvas_grades", None)
    if synced_assignment_ids:
        mark_synced_assignments(conn, synced_assignment_ids)
    if synced_grade_keys:
        mark_synced_grades(conn, synced_grade_keys)
    return {"ok": overall_ok, "results": results}
