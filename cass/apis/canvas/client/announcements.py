"""Announcements (discussion topics flagged as announcements)."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from ..schema import CanvasAnnouncement
from .base import BaseClient


class AnnouncementsMixin(BaseClient):
    """Announcements (discussion topics flagged as announcements)."""

    def list_announcements(self) -> list[CanvasAnnouncement]:
        """List course announcements.

        Returns:
            Announcements sorted by posted_at descending.
        """
        data = self._get_paginated(
            f"/courses/{self.course_id}/discussion_topics"
            "?only_announcements=true&order_by=recent_activity"
        )
        return msgspec.convert(data, list[CanvasAnnouncement], strict=False)

    def create_announcement(self, title: str, message: str) -> CanvasAnnouncement:
        """Create an announcement.

        Args:
            title: Announcement title.
            message: HTML body.

        Returns:
            The created announcement.
        """
        resp = self._client.post(
            self._course("/discussion_topics"),
            data={
                "title": title,
                "message": message,
                "is_announcement": True,
                "published": True,
            },
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAnnouncement, strict=False)

    def update_announcement(
        self, topic_id: int, **kwargs: object
    ) -> CanvasAnnouncement:
        """Update an announcement.

        Args:
            topic_id: Discussion topic ID.
            **kwargs: Fields to update (title, message).

        Returns:
            The updated announcement.
        """
        resp = self._client.put(
            self._course(f"/discussion_topics/{topic_id}"), data=kwargs
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAnnouncement, strict=False)

    def delete_announcement(self, topic_id: int) -> None:
        """Delete an announcement."""
        resp = self._client.delete(self._course(f"/discussion_topics/{topic_id}"))
        resp.raise_for_status()
