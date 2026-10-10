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
        resp = self.request("GET", self._course(f"/modules/{module_id}"))
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
        resp = self.request("POST", self._course("/modules"), data=params)
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
        resp = self.request("PUT", self._course(f"/modules/{module_id}"), data=params)
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def delete_module(self, module_id: int) -> None:
        """Delete a module."""
        self.request("DELETE", self._course(f"/modules/{module_id}"))

    def create_module_item(
        self,
        module_id: int,
        *,
        item_type: str,
        content_id: int | None = None,
        title: str | None = None,
        indent: int | None = None,
        page_url: str | None = None,
        external_url: str | None = None,
    ) -> CanvasModuleItem:
        """Add an item to a module.

        Only the fields given are sent.

        Args:
            module_id: Canvas module ID.
            item_type: Item type (Assignment, Quiz, File, Page, SubHeader,
                ExternalUrl, etc.).
            content_id: ID of the linked content (Assignment, Quiz, File).
            title: Item title; Canvas uses the content's name when omitted.
            indent: Indent level.
            page_url: Slug of the linked wiki page (Page items).
            external_url: Target URL (ExternalUrl items).

        Returns:
            The created module item.
        """
        params: dict[str, object] = {"module_item[type]": item_type}
        if content_id is not None:
            params["module_item[content_id]"] = content_id
        if title:
            params["module_item[title]"] = title
        if indent is not None:
            params["module_item[indent]"] = indent
        if page_url:
            params["module_item[page_url]"] = page_url
        if external_url:
            params["module_item[external_url]"] = external_url
        resp = self.request(
            "POST", self._course(f"/modules/{module_id}/items"), data=params
        )
        return msgspec.convert(resp.json(), CanvasModuleItem, strict=False)

    def update_module_item(
        self,
        module_id: int,
        item_id: int,
        *,
        title: str | None = None,
        indent: int | None = None,
        position: int | None = None,
        published: bool | None = None,
        current: CanvasModuleItem | None = None,
    ) -> CanvasModuleItem:
        """Update a module item; only the fields given are sent.

        Args:
            module_id: Canvas module ID.
            item_id: Module item ID.
            title: New title.
            indent: New indent level.
            position: New position within the module.
            published: New published state.
            current: The item as it is now. ``published`` is not sent when it
                equals ``current.published``, and when nothing else is left
                to send, ``current`` is returned without a request.

        Returns:
            The updated item.

        Raises:
            ValueError: If no field is given.
        """
        given = {
            "title": title,
            "indent": indent,
            "position": position,
            "published": published,
        }
        if all(value is None for value in given.values()):
            raise ValueError("update_module_item needs at least one field")
        if current is not None and published == current.published:
            given["published"] = None
            if all(value is None for value in given.values()):
                return current  # only an unchanged published was given
        params = {
            f"module_item[{name}]": value
            for name, value in given.items()
            if value is not None
        }
        resp = self.request(
            "PUT", self._course(f"/modules/{module_id}/items/{item_id}"), data=params
        )
        return msgspec.convert(resp.json(), CanvasModuleItem, strict=False)

    def delete_module_item(self, module_id: int, item_id: int) -> None:
        """Remove an item from a module (the linked content is untouched)."""
        self.request("DELETE", self._course(f"/modules/{module_id}/items/{item_id}"))

    def resolve_module_item(self, module_id: int, id_or_title: str) -> CanvasModuleItem:
        """Resolve a module item by ID or title (case-insensitive).

        Raises:
            RuntimeError: If no item matches or several share the title.
        """
        return self._resolve(
            self.list_module_items(module_id),
            id_or_title,
            "Module item",
            lambda item: item.title,
        )

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
