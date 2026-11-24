"""Assignment sync: reconcile declared assignments and groups with the live course."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from ..apis.canvas.attempts import (
    QuizAttemptsUnknownError,
    QuizHasAttemptsError,
    refuse_if_assignment_attempted,
)
from ..apis.canvas.errors import CanvasAPIError
from ..apis.canvas.sync import push_assignments, resolve_group_ids
from ..apis.canvas.times import parse_when, same_instant
from ..db.assignments import (
    delete_local_assignment,
    get_local_assignment,
    replace_local_id,
)
from ..db.sync import mark_synced_assignments

if TYPE_CHECKING:
    import sqlite_utils

    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasAssignmentGroup, CanvasAssignmentResponse
    from .config import CanvasAssignmentSpec


class MissingAssignmentGroupsError(RuntimeError):
    """Assignment groups are missing on Canvas and creating them wasn't asked for."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"Assignment groups not found on Canvas: {', '.join(missing)}")
        self.missing = missing


def sync_assignment_groups(
    client: CanvasClient, wanted: list[str], *, create: bool
) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    """Resolve assignment groups by name and create the missing ones when asked.

    Groups match by name, case-insensitively. Writes always go through
    ``client``; dry runs pass a dry-run client.

    Raises:
        MissingAssignmentGroupsError: Some groups are missing and ``create``
            is false. Nothing has been written.

    Returns:
        ``("create", "group", name)`` rows for the groups this call creates,
        and the Canvas id of every wanted group by lower-cased name (a dry-run
        placeholder for a group this call creates).
    """
    if not wanted:
        return [], {}
    group_ids, missing = resolve_group_ids(client, wanted)
    if missing and not create:
        raise MissingAssignmentGroupsError(missing)
    rows: list[tuple[str, str, str]] = []
    for name in missing:
        rows.append(("create", "group", name))
        group_ids[name.lower()] = client.create_assignment_group(name).id
    return rows, group_ids


def sync_assignments(
    client: CanvasClient,
    specs: list[CanvasAssignmentSpec],
    group_ids: dict[str, int],
    tz: str,
    *,
    created: list[CanvasAssignmentResponse] | None = None,
) -> list[tuple[str, str, str]]:
    """Reconcile assignment specs against live assignments, matched by name.

    Names match case-insensitively. An existing assignment gets its points,
    due date and published state updated where the spec sets them and they
    differ; its group and submission types are left alone. A spec without
    ``published`` leaves the live assignment as it is, and a new assignment
    stays unpublished. Writes always go through ``client``; dry runs pass a
    dry-run client.

    Args:
        group_ids: Canvas group ids by lower-cased name, from
            `sync_assignment_groups`; used only for new assignments.
        tz: Course time zone, for due dates written without an offset.
        created: When given, each assignment this call creates is appended to it.

    Returns:
        ``(action, "assignment", name)`` rows: create, update (with the
        changed fields), skip, refuse, or fail (with the error). A quiz with
        finished student attempts, or whose attempts cannot be checked, gets a
        ``refuse`` row for a points change, which is not sent; its other
        changes still are (commitment C2).
    """
    live_by_name = {a.name.lower(): a for a in client.list_assignments()}
    rows: list[tuple[str, str, str]] = []
    for spec in specs:
        wanted_due = parse_when(spec.due_at, tz)
        live = live_by_name.get(spec.name.lower())
        if live is None:
            rows.append(("create", "assignment", spec.name))
            group_id = group_ids.get(spec.group.lower()) if spec.group else None
            new_assignment = client.create_assignment(
                spec.name,
                points_possible=spec.points,
                due_at=wanted_due or None,
                submission_types=spec.submission_types,
                published=bool(spec.published),
                assignment_group_id=group_id,
            )
            if created is not None:
                created.append(new_assignment)
            continue
        changes: dict[str, object] = {}
        if spec.points and (live.points_possible or 0.0) != spec.points:
            changes["points_possible"] = spec.points
        if wanted_due and not same_instant(live.due_at, wanted_due):
            changes["due_at"] = wanted_due
        if spec.published is not None and live.published != spec.published:
            changes["published"] = spec.published
        refusal = None
        if "points_possible" in changes:
            refusal = _points_refusal(client, live)
        if refusal is not None:
            detail = f"points_possible: {refusal}; change it in the Canvas web app"
            rows.append(("refuse", "assignment", f"{spec.name} ({detail})"))
            del changes["points_possible"]
        if not changes:
            if refusal is None:
                rows.append(("skip", "assignment", spec.name))
            continue
        (result,) = push_assignments(client, {live.id: changes})
        if not result["ok"]:
            rows.append(("fail", "assignment", f"{spec.name} ({result['error']})"))
            continue
        detail = ", ".join(f"{k}: {v}" for k, v in changes.items())
        rows.append(("update", "assignment", f"{spec.name} ({detail})"))
    return rows


def _points_refusal(
    client: CanvasClient, assignment: CanvasAssignmentResponse
) -> str | None:
    """Return why the assignment's points must not change, or None."""
    try:
        refuse_if_assignment_attempted(client, assignment, "change points_possible")
    except QuizHasAttemptsError as exc:
        return f"{exc.attempts} finished attempt(s)"
    except QuizAttemptsUnknownError:
        return "attempts could not be checked"
    return None


def refuse_group_delete(client: CanvasClient, group: CanvasAssignmentGroup) -> None:
    """Raise if deleting the group would delete a quiz students have finished.

    Fetches the group's assignments afresh on every call.

    Raises:
        QuizHasAttemptsError: A quiz in the group has finished student attempts.
        QuizAttemptsUnknownError: A quiz's attempts could not be checked.
    """
    for assignment in client.list_assignments():
        if assignment.assignment_group_id == group.id:
            refuse_if_assignment_attempted(
                client, assignment, "delete its assignment group"
            )


def validate_assignment_fields(*, name: str, points: float | None) -> list[str]:
    """Validate assignment creation fields.

    Args:
        name: Assignment name.
        points: Points possible.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    if not name.strip():
        errors.append("Name is required.")
    if points is not None and points < 0:
        errors.append("Points must be ≥ 0.")
    return errors


def push_new_assignment(
    conn: sqlite_utils.Database,
    local_id: int,
    client: CanvasClient,
) -> dict[str, object]:
    """Push a locally-created assignment to Canvas and update the local DB.

    Args:
        conn: SQLite database connection.
        local_id: The negative local canvas_id.
        client: Authenticated Canvas API client.

    Returns:
        Result dict with ``ok``, ``canvas_id``, and optionally ``error``.
    """
    row = get_local_assignment(conn, local_id)
    if row is None:
        return {"ok": False, "error": "Assignment not found"}

    name, points, due_at, published, group_name = row

    # Resolve group name -> Canvas group ID (create if new)
    group_id: int | None = None
    if group_name:
        groups = client.list_assignment_groups()
        for g in groups:
            if g.name == group_name:
                group_id = g.id
                break
        if group_id is None:
            try:
                new_group = client.create_assignment_group(group_name)
                group_id = new_group.id
            except Exception as e:
                return {
                    "ok": False,
                    "error": f"Failed to create group '{group_name}': {e}",
                }

    try:
        created = client.create_assignment(
            name,
            points_possible=float(points),
            due_at=str(due_at) if due_at else None,
            published=bool(published),
            assignment_group_id=group_id,
        )
        replace_local_id(conn, local_id, created.id)
        mark_synced_assignments(conn, [created.id])
        return {"ok": True, "canvas_id": created.id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_assignment_from_canvas(
    conn: sqlite_utils.Database,
    canvas_id: int,
    client: CanvasClient,
) -> dict[str, object]:
    """Delete an assignment from Canvas (if remote) and locally.

    Local-only assignments (negative IDs) skip the Canvas API call. Local rows
    are kept when the delete is refused, because students have finished the
    assignment's quiz (commitment C2), or fails. An assignment Canvas reports
    as not found is already deleted there, so its local rows are removed.

    Returns:
        Result dict with ``ok`` and optionally ``error``.
    """
    if canvas_id > 0:
        try:
            assignment = client.get_assignment(canvas_id)
            refuse_if_assignment_attempted(client, assignment, "delete it")
            client.delete_assignment(canvas_id)
        except Exception as e:
            already_deleted = isinstance(e, CanvasAPIError) and e.status_code == 404
            if not already_deleted:
                return {"ok": False, "error": str(e)}

    delete_local_assignment(conn, canvas_id)
    return {"ok": True}
