"""Course wiki pages."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from ..schema import CanvasPage
from .base import BaseClient


class PagesMixin(BaseClient):
    """Course wiki pages."""

    def list_pages(self) -> list[CanvasPage]:
        """List the course's wiki pages.

        Returns:
            Pages with their URL slugs and published state.
        """
        data = self._get_paginated(self._course("/pages"))
        return msgspec.convert(data, list[CanvasPage], strict=False)
