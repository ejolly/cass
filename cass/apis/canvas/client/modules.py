"""Modules and module items."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from ..schema import CanvasModule, CanvasModuleItem
from .base import BaseClient


class ModulesMixin(BaseClient):
    """Modules and module items."""

    def list_modules(self) -> list[CanvasModule]:
        """List all course modules.

        Returns:
            Modules sorted by position.
        """
        data = self._get_paginated(self._course("/modules"))
        return msgspec.convert(data, list[CanvasModule], strict=False)

    def get_module(self, module_id: int) -> CanvasModule:
        """Get a single module by ID."""
        resp = self._client.get(self._course(f"/modules/{module_id}"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def list_module_items(self, module_id: int) -> list[CanvasModuleItem]:
        """List items in a module.

        Args:
            module_id: Canvas module ID.

        Returns:
            Module items sorted by position.
        """
        data = self._get_paginated(self._course(f"/modules/{module_id}/items"))
        return msgspec.convert(data, list[CanvasModuleItem], strict=False)

    def create_module(self, name: str, position: int | None = None) -> CanvasModule:
        """Create a new module.

        Args:
            name: Module name.
            position: Optional position in the module list.

        Returns:
            The created module.
        """
        params: dict[str, object] = {"module[name]": name}
        if position is not None:
            params["module[position]"] = position
        resp = self._client.post(self._course("/modules"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def update_module(self, module_id: int, **kwargs: object) -> CanvasModule:
        """Update a module.

        Args:
            module_id: Canvas module ID.
            **kwargs: Fields to update (name, position, published).

        Returns:
            The updated module.
        """
        params = {f"module[{k}]": v for k, v in kwargs.items()}
        resp = self._client.put(self._course(f"/modules/{module_id}"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def delete_module(self, module_id: int) -> None:
        """Delete a module."""
        resp = self._client.delete(self._course(f"/modules/{module_id}"))
        resp.raise_for_status()

    def create_module_item(
        self,
        module_id: int,
        *,
        item_type: str,
        content_id: int,
        title: str | None = None,
    ) -> CanvasModuleItem:
        """Add an item to a module.

        Args:
            module_id: Canvas module ID.
            item_type: Item type (Assignment, Quiz, File, etc.).
            content_id: ID of the linked content.
            title: Item title; Canvas uses the content's name when omitted.

        Returns:
            The created module item.
        """
        params: dict[str, object] = {
            "module_item[type]": item_type,
            "module_item[content_id]": content_id,
        }
        if title:
            params["module_item[title]"] = title
        resp = self._client.post(
            self._course(f"/modules/{module_id}/items"), data=params
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModuleItem, strict=False)

    def resolve_module(self, id_or_name: str) -> CanvasModule:
        """Resolve a module by numeric ID or name (case-insensitive).

        Raises:
            RuntimeError: If no module matches.
        """
        if id_or_name.isdigit():
            return self.get_module(int(id_or_name))
        return self._resolve(
            self.list_modules(), id_or_name, "Module", lambda m: m.name
        )
