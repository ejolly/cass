"""Canvas sync state and shared preview/apply workflows."""

from __future__ import annotations

__docformat__ = "google"

import json
import sqlite3
import time
from typing import TYPE_CHECKING, cast

import msgspec
import sqlite_utils

from ..apis.canvas.attempts import QuizAttemptsUnknownError, count_finished_attempts
from ..apis.canvas.sync import (
    PostingPreview,
    accepts_grade,
    get_post_manually,
    get_scheme_letters,
    is_valid_grade,
    pass_fail_change_ignored,
    push_assignments,
    push_grades,
    resolve_row_name,
    values_equal,
)
from .catalog import CANVAS_PUSHABLE, PULL_GUARDED_TABLES
from .core import (
    GRADE_BASELINES_KEY,
    _connection,
    get_db,
    get_meta,
    load_canvas_grades,
    write_transaction,
)
from .schema import CanvasAssignment, CanvasGrade

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasAssignmentResponse

ChangeFields = dict[str, object]
RowChanges = dict[str, ChangeFields]
TableChanges = dict[str, RowChanges]
PendingChanges = dict[str, TableChanges]


def snapshot_canvas_synced(sdb: sqlite_utils.Database | None = None) -> None:
    """Copy current canvas tables into synced shadow tables.

    This makes every local value its own baseline, so pull must not call it: an
    unpushed edit would stop being pending.
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
    """Update synced shadow for whole assignments after push."""
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


def mark_synced_assignment_columns(
    sdb: sqlite_utils.Database, canvas_id: int, columns: Iterable[str]
) -> None:
    """Update synced shadow for the pushed columns of one assignment.

    Edits to its other columns stay pending.
    """
    for column in sorted(CANVAS_PUSHABLE["canvas_assignments"].intersection(columns)):
        sdb.execute(
            f"""
            UPDATE _canvas_assignments_synced
            SET {column} = (
                SELECT {column} FROM canvas_assignments WHERE canvas_id = ?
            )
            WHERE canvas_id = ?
            """,
            [canvas_id, canvas_id],
        )
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
    A grade whose value on Canvas was never recorded has baseline ``None``; a
    blank one is not pending.
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
            LEFT JOIN _canvas_grades_synced s
              ON m.canvas_user_id = s.canvas_user_id
             AND m.canvas_assignment_id = s.canvas_assignment_id
            WHERE m.posted_grade != IFNULL(s.posted_grade, '')
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


def refresh_pending(pending: PendingChanges, sdb: sqlite_utils.Database) -> None:
    """Replace the contents of ``pending`` in place with the current changes."""
    pending.clear()
    pending.update(get_pending_changes(sdb))


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


def _refuse_if_pull_blocked(sdb: sqlite_utils.Database) -> None:
    """Raise when a pull would overwrite a pending change."""
    if (reason := pull_block_reason(sdb)) is not None:
        raise RuntimeError(reason)


def save_pulled_assignments(assignments: list[CanvasAssignment]) -> int:
    """Store assignments pulled from Canvas as working values and as baselines.

    Raises:
        RuntimeError: when a pending change would be overwritten.
    """
    sdb = get_db()
    with write_transaction(sdb) as transaction:
        _refuse_if_pull_blocked(sdb)
        transaction.executemany(
            """
            INSERT OR REPLACE INTO canvas_assignments
                (canvas_id, name, points_possible, due_at, published,
                 assignment_group, post_manually)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    a.canvas_id,
                    a.name,
                    a.points_possible,
                    a.due_at,
                    a.published,
                    a.assignment_group,
                    a.post_manually,
                )
                for a in assignments
            ],
        )
        transaction.executemany(
            """
            INSERT OR REPLACE INTO _canvas_assignments_synced
                (canvas_id, name, points_possible, due_at, published)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (a.canvas_id, a.name, a.points_possible, a.due_at, a.published)
                for a in assignments
            ],
        )
    return len(assignments)


def save_pulled_grades(
    grades: list[CanvasGrade], *, full_pull: bool = False
) -> list[tuple[int, int]]:
    """Store grades pulled from Canvas as working values and as baselines.

    Baselines written before pull stored grades may hold grades Canvas never
    had. Until a full pull sets the ``grade_baselines`` meta key, a local grade
    that differs from Canvas is therefore kept and loses its baseline, which
    makes it a pending conflict. Otherwise the Canvas value wins. In a full
    pull, a non-blank local grade Canvas sent no value for is kept the same way.

    Args:
        grades: Grades pulled from Canvas.
        full_pull: ``grades`` holds every grade Canvas has for the course.

    Returns:
        ``(canvas_user_id, canvas_assignment_id)`` of each local grade kept.

    Raises:
        RuntimeError: when a pending change would be overwritten.
    """
    sdb = get_db()
    now = time.time()
    kept: list[tuple[int, int]] = []
    to_store: list[CanvasGrade] = []
    with write_transaction(sdb) as transaction:
        _refuse_if_pull_blocked(sdb)
        local_grades: dict[tuple[int, int], str] = {}
        if get_meta(GRADE_BASELINES_KEY, sdb) is None:
            local_grades = {
                (g.canvas_user_id, g.canvas_assignment_id): g.posted_grade
                for g in load_canvas_grades()
            }
        for grade in grades:
            key = (grade.canvas_user_id, grade.canvas_assignment_id)
            local_grade = local_grades.get(key, "")
            if local_grade and local_grade != grade.posted_grade:
                kept.append(key)
            else:
                to_store.append(grade)
        if full_pull:
            sent = {(g.canvas_user_id, g.canvas_assignment_id) for g in grades}
            kept.extend(
                key
                for key in _possibly_unpushed_grades(transaction, sdb)
                if key not in sent
            )
        transaction.executemany(
            """
            INSERT OR REPLACE INTO canvas_grades
                (canvas_user_id, canvas_assignment_id, score, posted_grade, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    g.canvas_user_id,
                    g.canvas_assignment_id,
                    g.score,
                    g.posted_grade,
                    now,
                )
                for g in to_store
            ],
        )
        transaction.executemany(
            """
            INSERT OR REPLACE INTO _canvas_grades_synced
                (canvas_user_id, canvas_assignment_id, posted_grade)
            VALUES (?, ?, ?)
            """,
            [
                (g.canvas_user_id, g.canvas_assignment_id, g.posted_grade)
                for g in to_store
            ],
        )
        transaction.executemany(
            "DELETE FROM _canvas_grades_synced "
            "WHERE canvas_user_id = ? AND canvas_assignment_id = ?",
            kept,
        )
    return kept


def _possibly_unpushed_grades(
    transaction: sqlite3.Connection,
    sdb: sqlite_utils.Database,
) -> list[tuple[int, int]]:
    """Return local grades that may be unpushed although they are not pending.

    Until a full pull sets the ``grade_baselines`` meta key, a baseline may hold
    a grade Canvas never had, so this is every non-blank grade.

    Returns:
        ``(canvas_user_id, canvas_assignment_id)`` of each such grade.
    """
    if get_meta(GRADE_BASELINES_KEY, sdb) is not None:
        return []
    return transaction.execute(
        "SELECT canvas_user_id, canvas_assignment_id FROM canvas_grades "
        "WHERE posted_grade != '' ORDER BY canvas_assignment_id, canvas_user_id"
    ).fetchall()


def remove_departed_students(
    current: set[int], stored: set[int]
) -> tuple[list[str], list[tuple[int, int]]]:
    """Delete students Canvas no longer lists, with everything stored for them.

    A student with a grade that may be unpushed is kept.

    Args:
        current: IDs of the students Canvas lists. When empty, nothing is
            removed, because a concluded course can list none.
        stored: IDs stored before Canvas was asked for its list. Other students
            are kept.

    Returns:
        The names of the removed students, and ``(canvas_user_id,
        canvas_assignment_id)`` of each grade whose student was kept for it.

    Raises:
        RuntimeError: when there is a pending change.
    """
    if not current:
        return [], []
    sdb = get_db()
    with write_transaction(sdb) as transaction:
        _refuse_if_pull_blocked(sdb)
        departed = stored - current
        kept_grades = [
            (user_id, assignment_id)
            for user_id, assignment_id in _possibly_unpushed_grades(transaction, sdb)
            if user_id in departed
        ]
        departed -= {user_id for user_id, _ in kept_grades}
        removed = [
            (canvas_id, name)
            for canvas_id, name in transaction.execute(
                "SELECT canvas_id, name FROM canvas_students ORDER BY sortable_name"
            ).fetchall()
            if canvas_id in departed
        ]
        ids = [(canvas_id,) for canvas_id, _ in removed]
        for statement in (
            "DELETE FROM canvas_submissions WHERE canvas_user_id = ?",
            "DELETE FROM canvas_grades WHERE canvas_user_id = ?",
            "DELETE FROM _canvas_grades_synced WHERE canvas_user_id = ?",
            "DELETE FROM canvas_students WHERE canvas_id = ?",
        ):
            transaction.executemany(statement, ids)
    return [name for _, name in removed], kept_grades


def remove_deleted_assignments(
    current: set[int], stored: set[int]
) -> tuple[list[str], list[tuple[int, int]]]:
    """Delete assignments Canvas no longer lists, with everything stored for them.

    Assignments that were never pushed (negative IDs), and those with a grade
    that may be unpushed, are kept.

    Args:
        current: IDs of the assignments Canvas lists. When empty, nothing is
            removed.
        stored: IDs stored before Canvas was asked for its list. Other
            assignments are kept.

    Returns:
        The names of the removed assignments, and ``(canvas_user_id,
        canvas_assignment_id)`` of each grade whose assignment was kept for it.

    Raises:
        RuntimeError: when there is a pending change.
    """
    if not current:
        return [], []
    sdb = get_db()
    with write_transaction(sdb) as transaction:
        _refuse_if_pull_blocked(sdb)
        deleted = {canvas_id for canvas_id in stored - current if canvas_id > 0}
        kept_grades = [
            (user_id, assignment_id)
            for user_id, assignment_id in _possibly_unpushed_grades(transaction, sdb)
            if assignment_id in deleted
        ]
        deleted -= {assignment_id for _, assignment_id in kept_grades}
        removed = [
            (canvas_id, name)
            for canvas_id, name in transaction.execute(
                "SELECT canvas_id, name FROM canvas_assignments ORDER BY name"
            ).fetchall()
            if canvas_id in deleted
        ]
        ids = [(canvas_id,) for canvas_id, _ in removed]
        for statement in (
            "DELETE FROM canvas_submissions WHERE canvas_assignment_id = ?",
            "DELETE FROM canvas_grades WHERE canvas_assignment_id = ?",
            "DELETE FROM _canvas_grades_synced WHERE canvas_assignment_id = ?",
            "DELETE FROM _canvas_assignments_synced WHERE canvas_id = ?",
            "DELETE FROM canvas_assignments WHERE canvas_id = ?",
        ):
            transaction.executemany(statement, ids)
    return [name for _, name in removed], kept_grades


def preview_assignments(
    conn: sqlite_utils.Database,
    table_changes: TableChanges,
    client: CanvasClient,
) -> list[dict[str, object]]:
    """Preview pending assignment changes against live Canvas state.

    A points change on a quiz is marked ``quiz_attempted`` when students have
    finished it, or ``quiz_attempts_unknown`` when that could not be checked.
    """
    results: list[dict[str, object]] = []
    for pk_key, columns in table_changes.items():
        canvas_id = int(pk_key)
        assignment_name = resolve_row_name(conn, "canvas_assignments", pk_key)
        try:
            live = client.get_assignment(canvas_id)
            attempt_flags: dict[str, object] = {}
            if "points_possible" in columns:
                attempt_flags = _quiz_attempt_flags(client, live)
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
                        **(attempt_flags if col == "points_possible" else {}),
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


def _quiz_attempt_flags(
    client: CanvasClient, assignment: CanvasAssignmentResponse
) -> dict[str, object]:
    """Return the preview flags that hold back a change to the points of a quiz."""
    if assignment.quiz_id is None:
        return {}
    try:
        attempts = count_finished_attempts(client, assignment.quiz_id)
    except QuizAttemptsUnknownError:
        return {"quiz_attempts_unknown": True}
    return {"quiz_attempted": attempts > 0}


def grade_conflicts(live: object, baseline: object) -> bool:
    """Return whether a live Canvas grade may differ from the last pulled one.

    An unknown baseline (None) always conflicts. Canvas reports an ungraded
    submission as None, which equals a blank baseline.
    """
    return baseline is None or not values_equal("" if live is None else live, baseline)


def exceeds_points(grade: object, points_possible: float | None) -> bool:
    """Return whether a grade is above the assignment's points possible.

    Plain numbers compare with ``points_possible``; percentages compare with
    100%. Letter grades and complete/incomplete never exceed.
    """
    text = str(grade).strip() if grade is not None else ""
    is_percent = text.endswith("%")
    try:
        value = float(text.removesuffix("%"))
    except ValueError:
        return False
    if is_percent:
        return value > 100
    if points_possible is None:
        return False
    return value > float(points_possible)


def preview_grades(
    conn: sqlite_utils.Database,
    table_changes: TableChanges,
    client: CanvasClient,
    *,
    assignment_changes: TableChanges | None = None,
) -> list[dict[str, object]]:
    """Preview pending grade changes against live Canvas submissions.

    Args:
        conn: Local database.
        table_changes: Pending grade changes.
        client: Canvas client.
        assignment_changes: Assignment changes pushed along with the grades.
    """
    results: list[dict[str, object]] = []
    by_assignment: dict[int, list[tuple[int, RowChanges]]] = {}
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        by_assignment.setdefault(aid, []).append((uid, columns))

    for aid, student_changes in by_assignment.items():
        assignment_name = resolve_row_name(conn, "canvas_assignments", str(aid))
        try:
            assignment = client.get_assignment(aid)
            post_manually = get_post_manually(assignment)
            letters = get_scheme_letters(client, assignment)
            # A points edit is pushed before the grades but may be held back, so
            # a grade must fit both the live points and the edited ones.
            points_in_effect = [assignment.points_possible or 0.0]
            assignment_edits = (assignment_changes or {}).get(str(aid), {})
            points_edit = assignment_edits.get("points_possible")
            if points_edit is not None:
                edited_points = cast(float | str | None, points_edit["current"])
                points_in_effect.append(float(edited_points or 0.0))
            live_subs = client.list_submissions(aid)
            live_by_user = {submission.user_id: submission for submission in live_subs}
            for uid, columns in student_changes:
                student_row = conn.execute(
                    "SELECT name FROM canvas_students WHERE canvas_id = ?",
                    [uid],
                ).fetchone()
                student_name = str(student_row[0]) if student_row else f"User {uid}"
                live_sub = live_by_user.get(uid)
                if live_sub is None:
                    results.append(
                        {
                            "table": "canvas_grades",
                            "canvas_assignment_id": aid,
                            "canvas_user_id": uid,
                            "name": f"{student_name} — {assignment_name}",
                            "post_manually": post_manually,
                            "error": "Canvas lists no submission for this student",
                        }
                    )
                    continue
                # Left out when Canvas did not say, so nothing is claimed about it.
                posted = (
                    {}
                    if live_sub.posted_at is msgspec.UNSET
                    else {"posted_at": live_sub.posted_at}
                )
                for col, vals in columns.items():
                    live_val = None
                    if col == "posted_grade":
                        live_val = live_sub.entered_grade
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
                            "conflict": grade_conflicts(live_val, vals["baseline"]),
                            "post_manually": post_manually,
                            **posted,
                            "points_possible": min(points_in_effect),
                            "over_points": col == "posted_grade"
                            and any(
                                exceeds_points(vals["current"], points)
                                for points in points_in_effect
                            ),
                            "clears": col == "posted_grade"
                            and clears_grade(vals["baseline"], vals["current"]),
                            "not_accepted": col == "posted_grade"
                            and has_grade(vals["current"])
                            and any(
                                not accepts_grade(
                                    str(vals["current"]),
                                    assignment.grading_type,
                                    letters,
                                    points,
                                )
                                or pass_fail_change_ignored(
                                    str(vals["current"]),
                                    live_sub.entered_grade,
                                    assignment.grading_type,
                                    points,
                                )
                                for points in points_in_effect
                            ),
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
    pending: PendingChanges,
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
            results.extend(
                preview_grades(
                    conn,
                    grade_changes,
                    client,
                    assignment_changes=assignment_changes,
                )
            )

    return {
        "ok": True,
        "changes": results,
        "has_conflicts": any(result.get("conflict") for result in results),
        "has_errors": any("error" in result for result in results),
    }


def _extract_assignment_updates(
    table_changes: TableChanges,
) -> dict[int, dict[str, object]]:
    updates: dict[int, dict[str, object]] = {}
    for pk_key, columns in table_changes.items():
        updates[int(pk_key)] = {col: vals["current"] for col, vals in columns.items()}
    return updates


def has_grade(value: object) -> bool:
    """Return whether a stored grade value holds a grade (not blank, ``-`` or ``?``)."""
    return value is not None and is_valid_grade(str(value))


def clears_grade(baseline: object, current: object) -> bool:
    """Return whether a grade change removes a grade Canvas had."""
    return has_grade(baseline) and not has_grade(current)


def _extract_grade_data(
    table_changes: TableChanges,
) -> tuple[dict[int, dict[int, str]], dict[int, list[str]], list[str]]:
    """Split grade changes into what to send and blank-to-blank no-ops.

    A cleared grade is sent as ``""``, which removes it on Canvas. Callers must
    hold back clears the user has not approved (``hold_back_unapproved``).

    Returns:
        Grades to send by assignment, the pending keys each assignment's push
        settles, and keys of changes between two blank values, which need no
        request.
    """
    grade_data_by_aid: dict[int, dict[int, str]] = {}
    pk_keys_by_aid: dict[int, list[str]] = {}
    noop_keys: list[str] = []
    for pk_key, columns in table_changes.items():
        pk = json.loads(pk_key)
        aid = pk["canvas_assignment_id"]
        uid = pk["canvas_user_id"]
        change = columns.get("posted_grade", {})
        current = change.get("current")
        if has_grade(current):
            grade = str(current).strip()
        elif has_grade(change.get("baseline")):
            grade = ""
        else:
            noop_keys.append(pk_key)
            continue
        grade_data_by_aid.setdefault(aid, {})[uid] = grade
        pk_keys_by_aid.setdefault(aid, []).append(pk_key)
    return grade_data_by_aid, pk_keys_by_aid, noop_keys


def canvas_apply(
    conn: sqlite_utils.Database,
    pending: PendingChanges,
    *,
    post_grades: bool = False,
    cover_policy_changes: bool = False,
    preview: dict[str, object] | None = None,
) -> dict[str, object]:
    """Push pending changes to Canvas and clear synced rows on success.

    ``push_assignments`` checks quiz attempts again just before each points
    change, and a refusal fails that assignment only. ``push_grades`` reads each
    posting policy again and compares it with the preview. Grades that were
    pushed but could not be released to students still count as synced.

    Args:
        conn: Local database.
        pending: Pending changes the user approved; synced ones are removed.
        post_grades: The user approved releasing the grades ``count_postable``
            counted in the preview.
        cover_policy_changes: With ``post_grades``, the approval covers every
            pushed grade, whatever the preview showed, as ``--post`` does.
        preview: Result of ``canvas_preview`` that the user's approvals were
            based on. Without it, posting policies are compared with the last
            pull's, and ``post_grades`` covers every pushed grade.

    Returns:
        ``ok`` (False if anything failed) and the ``results`` rows.
    """
    from ..apis.canvas.client import CanvasClient

    assignment_changes = pending.get("canvas_assignments", {})
    grade_changes = pending.get("canvas_grades", {})
    if not assignment_changes and not grade_changes:
        return {"ok": True, "results": []}

    results: list[dict[str, object]] = []
    overall_ok = True
    synced_assignment_columns: dict[int, set[str]] = {}
    synced_grade_keys: list[tuple[int, int]] = []
    with CanvasClient() as client:
        if assignment_changes:
            updates = _extract_assignment_updates(assignment_changes)
            assignment_results = push_assignments(client, updates)
            results.extend(assignment_results)
            for result in assignment_results:
                if not result.get("ok"):
                    overall_ok = False
                if result.get("ok"):
                    canvas_id = int(result["canvas_id"])  # type: ignore[arg-type]
                    assignment_changes.pop(str(canvas_id), None)
                    synced_assignment_columns[canvas_id] = set(updates[canvas_id])

        if grade_changes:
            grade_data, pk_keys, noop_keys = _extract_grade_data(grade_changes)
            for pk_key in noop_keys:
                grade_changes.pop(pk_key, None)
                pk = json.loads(pk_key)
                synced_grade_keys.append(
                    (pk["canvas_user_id"], pk["canvas_assignment_id"])
                )
            grade_results = push_grades(
                client,
                conn,
                grade_data,
                post_grades=post_grades,
                cover_policy_changes=cover_policy_changes,
                previewed=None if preview is None else _posting_previews(preview),
            )
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
    for canvas_id, columns in synced_assignment_columns.items():
        mark_synced_assignment_columns(conn, canvas_id, columns)
    if synced_grade_keys:
        mark_synced_grades(conn, synced_grade_keys)
    return {"ok": overall_ok, "results": results}


def track_change(
    pending: PendingChanges,
    table: str,
    pk: dict[str, object],
    column: str,
    old_value: object,
    new_value: object,
) -> None:
    """Record a cell edit as a pending Canvas change."""
    pushable = CANVAS_PUSHABLE.get(table)
    if not pushable or column not in pushable:
        return

    pk_key = (
        str(next(iter(pk.values()))) if len(pk) == 1 else json.dumps(pk, sort_keys=True)
    )

    table_changes = pending.setdefault(table, {})
    row_changes = table_changes.setdefault(pk_key, {})

    if column in row_changes:
        row_changes[column]["current"] = new_value
        if values_equal(row_changes[column]["baseline"], new_value):
            del row_changes[column]
            if not row_changes:
                del table_changes[pk_key]
            if not table_changes:
                del pending[table]
    else:
        row_changes[column] = {
            "baseline": old_value,
            "current": new_value,
        }


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


def count_pending(pending: PendingChanges) -> int:
    """Count pending column changes across all tables and rows."""
    return sum(len(cols) for rows in pending.values() for cols in rows.values())


HELD_CONFLICT = "changed on Canvas since your last pull"
HELD_OVER_POINTS = "above the assignment's points possible"
HELD_CLEAR = "would remove the grade on Canvas"
HELD_NOT_COMPARED = "could not be compared with Canvas"
HELD_NOT_ACCEPTED = "not a grade Canvas accepts for this assignment's grading type"
HELD_QUIZ_ATTEMPTS = (
    "students have finished this quiz; change its points in the Canvas web app"
)
HELD_QUIZ_ATTEMPTS_UNKNOWN = (
    "attempts at this quiz could not be checked; "
    "change its points in the Canvas web app"
)


def hold_back_unapproved(
    pending: PendingChanges,
    preview: dict[str, object],
    *,
    overwrite_conflicts: bool = False,
    allow_over_points: bool = False,
    allow_clears: bool = False,
) -> tuple[PendingChanges, list[dict[str, object]]]:
    """Split pending changes into those safe to push and those held back.

    A change is held back when its Canvas value changed since the last pull
    (unless ``overwrite_conflicts``), when a grade is above the assignment's
    points possible (unless ``allow_over_points``), or when it removes a grade
    from Canvas (unless ``allow_clears``). A change the preview could not
    compare with Canvas, a grade Canvas would not record as entered, or a
    points change on a quiz that has or may have finished attempts, is always
    held back. Held-back changes stay pending locally.

    Args:
        pending: Pending changes from ``get_pending_changes``.
        preview: Result of ``canvas_preview`` for the same pending changes.
        overwrite_conflicts: The user approved overwriting conflicting values.
        allow_over_points: The user approved grades above points possible.
        allow_clears: The user approved removing grades from Canvas.

    Returns:
        A copy of ``pending`` without held-back changes, and the preview rows
        that were held back, each with a ``held`` reason.
    """
    to_push: PendingChanges = json.loads(json.dumps(pending))
    held: list[dict[str, object]] = []
    changes = cast(list[dict[str, object]], preview.get("changes", []))
    for change in changes:
        reason = held_reason(
            change,
            overwrite_conflicts=overwrite_conflicts,
            allow_over_points=allow_over_points,
            allow_clears=allow_clears,
        )
        if reason is None:
            continue
        held.append({**change, "held": reason})
        remove_previewed_change(to_push, change)
    return to_push, held


def _posting_previews(preview: dict[str, object]) -> dict[int, PostingPreview]:
    """Return what the preview showed about each assignment's posting."""
    rows: dict[int, list[dict[str, object]]] = {}
    for change in cast(list[dict[str, object]], preview.get("changes", [])):
        if "post_manually" in change:
            aid = cast(int, change["canvas_assignment_id"])
            rows.setdefault(aid, []).append(change)
    return {
        aid: PostingPreview(
            post_manually=bool(changes[0]["post_manually"]),
            unposted_ids=frozenset(
                cast(int, c["canvas_user_id"])
                for c in changes
                if "posted_at" in c and c["posted_at"] is None
            ),
            released_ids=frozenset(
                cast(int, c["canvas_user_id"])
                for c in changes
                if c.get("posted_at") is not None
            ),
        )
        for aid, changes in rows.items()
    }


def count_postable(to_push: PendingChanges, preview: dict[str, object]) -> int:
    """Count the grades a push would leave for a separate release to students.

    Args:
        to_push: Pending changes without those held back.
        preview: Result of ``canvas_preview`` for them.

    Returns:
        The number of grades, not counting clears, on manual-post assignments
        for students whose grade is not already released.
    """
    previews = _posting_previews(preview)
    grade_data, _, _ = _extract_grade_data(to_push.get("canvas_grades", {}))
    return sum(
        1
        for aid, grades in grade_data.items()
        if aid in previews and previews[aid].post_manually
        for uid, grade in grades.items()
        if has_grade(grade) and uid in previews[aid].unposted_ids
    )


def release_notices(to_push: PendingChanges, preview: dict[str, object]) -> list[str]:
    """Return what to tell the user, before pushing, about released grades.

    Covers changes on manual-post assignments that students see without a
    release, clears included, and those cass cannot tell about.

    Args:
        to_push: Pending changes without those held back.
        preview: Result of ``canvas_preview`` for them.
    """
    grade_data, _, _ = _extract_grade_data(to_push.get("canvas_grades", {}))
    released = 0
    unknown = 0
    seen: set[tuple[object, object]] = set()
    for change in cast(list[dict[str, object]], preview.get("changes", [])):
        aid, uid = change.get("canvas_assignment_id"), change.get("canvas_user_id")
        pushed = uid in grade_data.get(cast(int, aid), {})
        if not change.get("post_manually") or not pushed or (aid, uid) in seen:
            continue
        seen.add((aid, uid))
        if "posted_at" not in change:
            unknown += 1
        elif change["posted_at"] is not None:
            released += 1
    notices = []
    if released:
        notices.append(
            f"{released} changed grade(s) are already released; "
            "students will see them when pushed."
        )
    if unknown:
        notices.append(
            f"cass could not tell whether {unknown} changed grade(s) are already "
            "released; students may see them when pushed."
        )
    return notices


def count_unreleased(result: dict[str, object]) -> int:
    """Count grades ``canvas_apply`` pushed that students cannot see yet.

    Leaves out grades whose release was tried, which have their own results.
    """
    rows = cast(list[dict[str, object]], result.get("results", []))
    return sum(cast(int, row.get("unreleased", 0)) for row in rows)


def push_notices(result: dict[str, object]) -> list[str]:
    """Return what to tell the user, after pushing, about unreleased grades.

    Args:
        result: Result of ``canvas_apply``.
    """
    notices = []
    if n_unreleased := count_unreleased(result):
        notices.append(
            f"{n_unreleased} grade(s) pushed but not released to students; "
            "they can now only be released in Canvas."
        )
    rows = cast(list[dict[str, object]], result.get("results", []))
    if n_unknown := sum(cast(int, row.get("release_unknown", 0)) for row in rows):
        notices.append(
            f"{n_unknown} grade(s) pushed, but cass could not tell whether they are "
            "released to students; check the Canvas gradebook."
        )
    return notices


def can_be_approved(change: dict[str, object]) -> bool:
    """Return whether the user's approval could let a previewed change through."""
    always_held = ("not_accepted", "quiz_attempted", "quiz_attempts_unknown")
    return "error" not in change and not any(change.get(flag) for flag in always_held)


def held_reason(
    change: dict[str, object],
    *,
    overwrite_conflicts: bool,
    allow_over_points: bool,
    allow_clears: bool = False,
) -> str | None:
    """Return why a previewed change must not be pushed yet, or None."""
    if "error" in change:
        return HELD_NOT_COMPARED
    if change.get("not_accepted"):
        return HELD_NOT_ACCEPTED
    if change.get("quiz_attempted"):
        return HELD_QUIZ_ATTEMPTS
    if change.get("quiz_attempts_unknown"):
        return HELD_QUIZ_ATTEMPTS_UNKNOWN
    if change.get("conflict") and not overwrite_conflicts:
        return HELD_CONFLICT
    if change.get("over_points") and not allow_over_points:
        return HELD_OVER_POINTS
    if change.get("clears") and not allow_clears:
        return HELD_CLEAR
    return None


def remove_previewed_change(pending: PendingChanges, change: dict[str, object]) -> None:
    """Remove the pending change(s) a preview row describes."""
    table = str(change.get("table", ""))
    table_changes = pending.get(table)
    if not table_changes:
        return
    column = change.get("column")
    if table == "canvas_assignments":
        keys = [str(change.get("canvas_id"))]
    else:
        aid = change.get("canvas_assignment_id")
        uid = change.get("canvas_user_id")
        keys = [
            key
            for key in table_changes
            if json.loads(key).get("canvas_assignment_id") == aid
            and (uid is None or json.loads(key).get("canvas_user_id") == uid)
        ]
    for key in keys:
        row = table_changes.get(key)
        if row is None:
            continue
        if column is None or "error" in change:
            row.clear()
        else:
            row.pop(str(column), None)
        if not row:
            del table_changes[key]
    if not table_changes:
        del pending[table]
