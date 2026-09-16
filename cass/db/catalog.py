"""Shared catalog metadata for user-facing cass data workflows."""

from __future__ import annotations

__docformat__ = "google"

from dataclasses import dataclass


@dataclass(frozen=True)
class TableCapability:
    """Shared table behavior metadata for CLI and viewer workflows."""

    editable: bool = False
    pushable: bool = False
    pull_guarded: bool = False
    viewer_rank: int = 999
    editable_columns: frozenset[str] | None = None


TABLE_CAPABILITIES: dict[str, TableCapability] = {
    "canvas_grades": TableCapability(
        editable=True,
        pushable=True,
        pull_guarded=True,
        viewer_rank=0,
    ),
    "canvas_assignments": TableCapability(
        editable=True,
        pushable=True,
        pull_guarded=True,
        viewer_rank=1,
    ),
    "canvas_submissions": TableCapability(viewer_rank=2),
}

CANVAS_WORKING_TABLES = {
    name for name, capability in TABLE_CAPABILITIES.items() if capability.editable
}
PULL_GUARDED_TABLES = {
    name for name, capability in TABLE_CAPABILITIES.items() if capability.pull_guarded
}


def get_table_capability(table: str) -> TableCapability:
    """Return shared behavior metadata for a table."""
    return TABLE_CAPABILITIES.get(table, TableCapability())


CANVAS_PUSHABLE: dict[str, set[str]] = {
    "canvas_assignments": {"name", "points_possible", "due_at", "published"},
    "canvas_grades": {"posted_grade"},
}

EXPORTABLE_TABLES = (
    "canvas_students",
    "canvas_assignments",
    "canvas_submissions",
    "canvas_grades",
)

IMPORT_SIGNATURES: dict[str, set[str]] = {
    "canvas_grades": {"canvas_user_id", "canvas_assignment_id"},
    "canvas_submissions": {
        "canvas_user_id",
        "canvas_assignment_id",
        "submitted",
    },
}
