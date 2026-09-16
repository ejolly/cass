"""Course navigation tabs."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from ..schema import CanvasTab
from .base import BaseClient


class TabsMixin(BaseClient):
    """Course navigation tabs."""

    def list_tabs(self) -> list[CanvasTab]:
        """List course navigation tabs.

        Returns:
            Tabs with visibility and position.
        """
        data = self._get_paginated(self._course("/tabs"))
        return msgspec.convert(data, list[CanvasTab], strict=False)

    def update_tab(self, tab_id: str, *, hidden: bool) -> CanvasTab:
        """Show or hide a navigation tab.

        Args:
            tab_id: Tab ID string.
            hidden: True to hide, False to show.

        Returns:
            The updated tab.
        """
        resp = self._client.put(
            self._course(f"/tabs/{tab_id}"), data={"hidden": hidden}
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasTab, strict=False)

    def resolve_tab(self, id_or_label: str) -> CanvasTab:
        """Resolve a navigation tab by ID (e.g. ``syllabus``) or label.

        Raises:
            RuntimeError: If no tab matches.
        """
        return self._resolve(self.list_tabs(), id_or_label, "Tab", lambda t: t.label)
