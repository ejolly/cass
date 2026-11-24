"""Module sync: reconcile declared modules with the live course."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from .config import CanvasModuleSpec


def sync_modules(
    client: CanvasClient,
    specs: list[CanvasModuleSpec],
    *,
    rows: list[tuple[str, str, str]] | None = None,
) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    """Create missing modules and set each module's published state.

    Modules match by name, case-insensitively. A spec without ``published``
    leaves the live module as it is; a module it creates stays unpublished.
    Writes always go through ``client``; dry runs pass a dry-run client.

    Args:
        rows: When given, each row is appended to it as soon as its change is
            made, so it is complete up to an error; it is also the list returned.

    Returns:
        ``(action, "module", name)`` rows (create, update or skip), and the
        Canvas id of each declared module by its declared name (a dry-run
        placeholder for a module this call creates).
    """
    rows = [] if rows is None else rows
    module_ids: dict[str, int] = {}
    live_by_name = {m.name.lower(): m for m in client.list_modules()}
    for spec in specs:
        live = live_by_name.get(spec.name.lower())
        if live is None:
            module = client.create_module(spec.name)
            module_ids[spec.name] = module.id
            if spec.published:
                try:
                    client.publish("modules", module.id)
                except BaseException:
                    detail = "publishing it failed; check Canvas"
                    rows.append(("create", "module", f"{spec.name} ({detail})"))
                    raise
            rows.append(("create", "module", spec.name))
            continue
        module_ids[spec.name] = live.id
        if spec.published is None or live.published == spec.published:
            rows.append(("skip", "module", spec.name))
            continue
        if spec.published:
            client.publish("modules", live.id)
        else:
            client.unpublish("modules", live.id)
        rows.append(("update", "module", f"{spec.name} (published: {spec.published})"))
    return rows, module_ids
