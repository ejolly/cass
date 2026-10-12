"""Assignment sync: reconcile declared assignments and groups with the live course."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

from ..apis.canvas.sync import push_assignments, resolve_group_ids
from ..apis.canvas.times import parse_when, same_instant

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasAssignmentResponse
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
        changed fields), or skip.
    """
    live_by_name = {a.name.lower(): a for a in client.list_assignments()}
    rows: list[tuple[str, str, str]] = []
    updates_by_id: dict[int, dict[str, object]] = {}
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
        if not changes:
            rows.append(("skip", "assignment", spec.name))
            continue
        detail = ", ".join(f"{k}: {v}" for k, v in changes.items())
        rows.append(("update", "assignment", f"{spec.name} ({detail})"))
        updates_by_id[live.id] = changes
    if updates_by_id:
        push_assignments(client, updates_by_id)
    return rows
