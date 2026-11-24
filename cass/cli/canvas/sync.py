"""``cass canvas sync`` — reconcile cass.toml declarations with Canvas."""

from __future__ import annotations

__docformat__ = "google"

from collections.abc import Iterator
from contextlib import contextmanager
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
    "refuse": "red",
    "fail": "red",
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

    from ...actions.assignments import (
        MissingAssignmentGroupsError,
        sync_assignment_groups,
        sync_assignments,
    )
    from ...actions.config import get_config
    from ...actions.module_items import (
        ModuleItemLookupError,
        apply_sync_items,
        plan_sync_items,
    )
    from ...actions.modules import sync_modules
    from ...actions.quizzes import (
        QuizAttemptsUnknownError,
        load_quiz_file,
        sync_quizzes,
    )

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

    actions: list[tuple[str, str, str]] = []  # (action, type, name)
    with _list_actions_on_error(actions, dry_run), _common.client(dry_run=dry_run) as c:
        tz = c.time_zone
        module_ids: dict[str, int] = {}
        created_assignments: list[CanvasAssignmentResponse] = []
        created_quizzes: list[CanvasQuiz] = []

        # --- Assignment groups ---
        try:
            _, group_ids = sync_assignment_groups(
                c, wanted_groups, create=create_groups, rows=actions
            )
        except MissingAssignmentGroupsError as exc:
            err_console.print(
                f"[red]{escape(str(exc))}[/red] (pass --create-groups to create them)"
            )
            raise typer.Exit(code=1) from None

        # --- Modules ---
        if cfg.canvas_modules:
            _, module_ids = sync_modules(c, cfg.canvas_modules, rows=actions)

        # --- Assignments ---
        if cfg.canvas_assignments:
            sync_assignments(
                c,
                cfg.canvas_assignments,
                group_ids,
                tz,
                created=created_assignments,
                rows=actions,
            )

        # --- Quizzes ---
        if quiz_specs:
            try:
                sync_quizzes(
                    c,
                    quiz_specs,
                    group_ids,
                    tz,
                    created=created_quizzes,
                    rows=actions,
                )
            except QuizAttemptsUnknownError as exc:
                if dry_run:
                    raise
                raise RuntimeError(
                    f"{exc}\nExcept any that failed or were refused, changes before "
                    "this quiz were already applied; nothing after it was sent."
                ) from None

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
                f"{exc}\nExcept any that failed or were refused, module, "
                "assignment and quiz changes were already applied; no module item "
                "changes were sent."
            ) from exc
        if items_plan is not None:
            # A ModuleItemApplyError lists the steps it applied; let it propagate.
            apply_sync_items(c, items_plan)
            actions.extend(items_plan.rows)

        plan_client = c

    # --- Display results ---
    _print_actions(actions, "Canvas Sync" + (" (dry run)" if dry_run else ""))

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

    refused = sum(1 for a, _, _ in actions if a == "refuse")
    failed = sum(1 for a, _, _ in actions if a == "fail")
    item_changes = items_plan is not None and items_plan.has_changes
    if dry_run and (creates or updates or item_changes):
        err_console.print(
            "\n  [yellow]Dry run — no changes made. Use --apply to sync.[/yellow]"
        )
    elif not dry_run and not (refused or failed):
        console.print("\n  [green]Sync complete.[/green]")

    if refused:
        err_console.print(
            f"  [red]Refused {refused} change(s) to quizzes or their assignments, "
            "because students have finished the quiz or their attempts could not "
            "be checked; make them in the Canvas web app.[/red]",
            soft_wrap=True,
        )
    if failed:
        err_console.print(
            f"  [red]{failed} assignment change(s) failed; see above.[/red]"
        )
    if refused or failed:
        raise typer.Exit(code=1)


def _print_actions(actions: list[tuple[str, str, str]], title: str) -> None:
    from rich.markup import escape
    from rich.table import Table

    table = Table(title=title, show_edge=False, pad_edge=False)
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


@contextmanager
def _list_actions_on_error(
    actions: list[tuple[str, str, str]], dry_run: bool
) -> Iterator[None]:
    """Print the actions taken so far when an error stops ``sync --apply``."""
    try:
        yield
    except BaseException:  # also an interrupt
        if actions and not dry_run:
            _print_actions(actions, "Canvas Sync (stopped by an error)")
            err_console.print(
                "  [red]Stopped by an error. The rows above are the results up to "
                "it. If a change failed, it may also have been applied, so check "
                "Canvas.[/red]",
                soft_wrap=True,
            )
        raise
