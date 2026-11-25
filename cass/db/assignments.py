"""Local assignment rows: list, create, re-key, and delete in ``cass.db``."""

from __future__ import annotations

__docformat__ = "google"

import sqlite_utils

from .core import write_transaction


def commit_if_open(conn: sqlite_utils.Database) -> None:
    """Commit the connection's open transaction, if it has one."""
    if conn.conn is not None:
        conn.conn.commit()


def list_assignments_for_select(
    conn: sqlite_utils.Database,
) -> dict[int, str]:
    """Return {canvas_id: name} for all assignments, sorted by name."""
    if "canvas_assignments" not in conn.table_names():
        return {}
    rows = conn.execute(
        "SELECT canvas_id, name FROM canvas_assignments ORDER BY name"
    ).fetchall()
    return {int(r[0]): r[1] for r in rows}


def get_local_assignment(
    conn: sqlite_utils.Database,
    canvas_id: int,
) -> tuple[str, float, str | None, bool, str] | None:
    """Return an assignment's (name, points, due_at, published, group), or None."""
    return conn.execute(
        "SELECT name, points_possible, due_at, published, assignment_group "
        "FROM canvas_assignments WHERE canvas_id = ?",
        [canvas_id],
    ).fetchone()


def create_local_assignment(
    conn: sqlite_utils.Database,
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
    commit_if_open(conn)
    return new_id


def replace_local_id(
    conn: sqlite_utils.Database,
    local_id: int,
    real_id: int,
) -> None:
    """Replace a local (negative) canvas_id with the real Canvas-assigned ID.

    Grades typed under the local ID move with it. Every student on the roster
    gets a blank grade baseline, because Canvas has no grades on an assignment
    it just created; existing baselines are kept.
    """
    with write_transaction(conn) as transaction:
        row = transaction.execute(
            "SELECT name, points_possible, due_at, published, assignment_group, "
            "post_manually FROM canvas_assignments WHERE canvas_id = ?",
            [local_id],
        ).fetchone()
        if row is None:
            return
        transaction.execute(
            "DELETE FROM canvas_assignments WHERE canvas_id = ?", [local_id]
        )
        transaction.execute(
            "INSERT INTO canvas_assignments "
            "(canvas_id, name, points_possible, due_at, published, "
            "assignment_group, post_manually) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [real_id, *row],
        )
        # A grade already stored under the real ID is never overwritten.
        transaction.execute(
            "UPDATE OR IGNORE canvas_grades SET canvas_assignment_id = ? "
            "WHERE canvas_assignment_id = ?",
            [real_id, local_id],
        )
        transaction.execute(
            "INSERT OR IGNORE INTO _canvas_grades_synced "
            "(canvas_user_id, canvas_assignment_id, posted_grade) "
            "SELECT canvas_id, ?, '' FROM canvas_students",
            [real_id],
        )


def delete_local_assignment(
    conn: sqlite_utils.Database,
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
    commit_if_open(conn)
