"""``cass canvas sync`` — reconcile cass.toml declarations with Canvas."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

import typer

from . import _common
from ._common import canvas_app, console, err_console

if TYPE_CHECKING:
    from ...apis.canvas.schema import CanvasAssignmentResponse, CanvasQuiz

ACTION_COLORS = {
    "create": "green",
    "upload": "green",
    "update": "yellow",
    "move": "yellow",
    "remove": "red",
    "skip": "dim",
    "keep": "dim",
    "extra": "dim",
}


@canvas_app.command(rich_help_panel="Manage")
def sync(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="Show what would change (default) or apply changes",
    ),
    create_groups: bool = typer.Option(
        False,
        "--create-groups",
        help="Create assignment groups that are missing on Canvas",
    ),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Remove module items not declared in cass.toml (modules with items only)",
    ),
) -> None:
    """Sync cass.toml declarations to Canvas (modules, assignments, quizzes).

    Compares [[canvas.modules]], [[canvas.assignments]], and the quiz files
    named by [[canvas.quizzes]] against the live Canvas course. Shows a diff
    of create/update/skip actions. Use --apply to execute changes.

    Quizzes match by title. Questions on an existing quiz are never compared
    or modified; only settings are updated.

    Modules that declare [[canvas.modules.items]] also get their items
    reconciled: every such module is planned before any item is written.
    Undeclared items are reported as extra; --prune removes them.
    """
    from rich.markup import escape
    from rich.table import Table

    from ...actions.config import get_config
    from ...actions.module_items import (
        ModuleItemLookupError,
        apply_sync_items,
        plan_sync_items,
    )
    from ...actions.modules import sync_modules
    from ...actions.quizzes import load_quiz_file, sync_quizzes
    from ...apis.canvas.sync import push_assignments, resolve_group_ids
    from ...apis.canvas.times import parse_when, same_instant

    _common.require_canvas()
    cfg = get_config()

    if not (cfg.canvas_modules or cfg.canvas_assignments or cfg.canvas_quizzes):
        err_console.print(
            "[yellow]No [[canvas.modules]], [[canvas.assignments]], or "
            "[[canvas.quizzes]] in cass.toml.[/yellow]"
        )
        return

    quiz_specs = [load_quiz_file(ref.file) for ref in cfg.canvas_quizzes]
    wanted_groups = [s.group for s in cfg.canvas_assignments if s.group] + [
        q.group for q in quiz_specs if q.group
    ]

    with _common.client(dry_run=dry_run) as c:
        tz = c.time_zone
        actions: list[tuple[str, str, str]] = []  # (action, type, name)
        module_ids: dict[str, int] = {}
        created_assignments: list[CanvasAssignmentResponse] = []
        created_quizzes: list[CanvasQuiz] = []

        # --- Assignment groups ---
        group_ids: dict[str, int] = {}
        if wanted_groups:
            group_ids, missing = resolve_group_ids(c, wanted_groups)
            if missing and not create_groups:
                err_console.print(
                    "[red]Assignment groups not found on Canvas: "
                    f"{', '.join(missing)}[/red] (pass --create-groups to create them)"
                )
                raise typer.Exit(code=1)
            for name in missing:
                actions.append(("create", "group", name))
                group_ids[name.lower()] = c.create_assignment_group(name).id

        # --- Modules ---
        if cfg.canvas_modules:
            module_rows, module_ids = sync_modules(c, cfg.canvas_modules)
            actions.extend(module_rows)

        # --- Assignments ---
        if cfg.canvas_assignments:
            live_assignments = c.list_assignments()
            live_by_name = {a.name.lower(): a for a in live_assignments}

            updates_by_id: dict[int, dict[str, object]] = {}
            for spec in cfg.canvas_assignments:
                key = spec.name.lower()
                wanted_due = parse_when(spec.due_at, tz)
                if key in live_by_name:
                    live = live_by_name[key]
                    changes: dict[str, object] = {}
                    if spec.points and (live.points_possible or 0.0) != spec.points:
                        changes["points_possible"] = spec.points
                    if wanted_due and not same_instant(live.due_at, wanted_due):
                        changes["due_at"] = wanted_due
                    if spec.published is not None and live.published != spec.published:
                        changes["published"] = spec.published

                    if changes:
                        detail = ", ".join(f"{k}: {v}" for k, v in changes.items())
                        actions.append(
                            ("update", "assignment", f"{spec.name} ({detail})")
                        )
                        updates_by_id[live.id] = changes
                    else:
                        actions.append(("skip", "assignment", spec.name))
                else:
                    actions.append(("create", "assignment", spec.name))
                    group_id = group_ids.get(spec.group.lower()) if spec.group else None
                    new_assignment = c.create_assignment(
                        spec.name,
                        points_possible=spec.points,
                        due_at=wanted_due or None,
                        submission_types=spec.submission_types,
                        published=bool(spec.published),
                        assignment_group_id=group_id,
                    )
                    created_assignments.append(new_assignment)

            if updates_by_id:
                push_assignments(c, updates_by_id)

        # --- Quizzes ---
        if quiz_specs:
            actions.extend(
                sync_quizzes(c, quiz_specs, group_ids, tz, created=created_quizzes)
            )

        # --- Module items ---
        try:
            items_plan = plan_sync_items(
                c,
                cfg.canvas_modules,
                module_ids,
                created_assignments=created_assignments,
                created_quizzes=created_quizzes,
                prune=prune,
            )
        except ModuleItemLookupError as exc:
            if dry_run:
                raise
            raise ModuleItemLookupError(
                f"{exc}\nModules, assignments and quizzes above were already "
                "applied; no module item changes were sent."
            ) from exc
        if items_plan is not None:
            actions.extend(items_plan.rows)
            # A ModuleItemApplyError lists the steps it applied; let it propagate.
            apply_sync_items(c, items_plan)

        plan_client = c

    # --- Display results ---
    table = Table(
        title="Canvas Sync" + (" (dry run)" if dry_run else ""),
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Action")
    table.add_column("Type")
    table.add_column("Name")

    for action, rtype, name in actions:
        color = ACTION_COLORS.get(action, "")
        # Names come from Canvas and cass.toml; escape them so "[...]" prints.
        table.add_row(
            f"[{color}]{escape(action)}[/{color}]", escape(rtype), escape(name)
        )

    console.print()
    console.print(table)
    console.print()

    creates = sum(1 for a, _, _ in actions if a == "create")
    updates = sum(1 for a, _, _ in actions if a == "update")
    skips = sum(1 for a, _, _ in actions if a == "skip")
    summary = f"  {creates} create, {updates} update, {skips} skip"
    if items_plan is not None:
        summary += "".join(
            f", {count} {action}" for action, count in items_plan.counts.items()
        )
    console.print(summary)

    if dry_run:
        _common.print_plan(plan_client)

    item_changes = items_plan is not None and items_plan.has_changes
    if dry_run and (creates or updates or item_changes):
        err_console.print(
            "\n  [yellow]Dry run — no changes made. Use --apply to sync.[/yellow]"
        )
    elif not dry_run:
        console.print("\n  [green]Sync complete.[/green]")
