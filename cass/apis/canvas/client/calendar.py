"""Course calendar events."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from ..schema import CanvasCalendarEvent
from .base import BaseClient


class CalendarMixin(BaseClient):
    """Course calendar events."""

    @property
    def _context_code(self) -> str:
        """Canvas context code for this course (used by calendar endpoints)."""
        return f"course_{self.course_id}"

    def list_calendar_events(
        self, *, start_date: str | None = None, end_date: str | None = None
    ) -> list[CanvasCalendarEvent]:
        """List calendar events on this course's calendar.

        Canvas defaults to today's events only, so without a date range this
        requests every event on the course calendar.

        Args:
            start_date: Inclusive lower bound (YYYY-MM-DD or ISO 8601).
            end_date: Inclusive upper bound (YYYY-MM-DD or ISO 8601).

        Returns:
            Calendar events (assignment due dates are not included).
        """
        params = [f"context_codes[]={self._context_code}", "type=event"]
        if start_date or end_date:
            if start_date:
                params.append(f"start_date={start_date}")
            if end_date:
                params.append(f"end_date={end_date}")
        else:
            params.append("all_events=true")
        data = self._get_paginated(f"/calendar_events?{'&'.join(params)}")
        return msgspec.convert(data, list[CanvasCalendarEvent], strict=False)

    def create_calendar_event(
        self,
        title: str,
        *,
        start_at: str,
        end_at: str | None = None,
        description: str | None = None,
        location_name: str | None = None,
        all_day: bool = False,
    ) -> CanvasCalendarEvent:
        """Create a calendar event on this course's calendar.

        Args:
            title: Event title.
            start_at: Start date/time (ISO 8601).
            end_at: End date/time (ISO 8601).
            description: HTML description.
            location_name: Location name.
            all_day: Ignore times and span the whole day.

        Returns:
            The created event.
        """
        fields: dict[str, object] = {
            "context_code": self._context_code,
            "title": title,
            "start_at": start_at,
            "all_day": all_day,
        }
        if end_at:
            fields["end_at"] = end_at
        if description:
            fields["description"] = description
        if location_name:
            fields["location_name"] = location_name
        resp = self._client.post("/calendar_events", data=_calendar_event_form(fields))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasCalendarEvent, strict=False)

    def update_calendar_event(
        self, event_id: int, **kwargs: object
    ) -> CanvasCalendarEvent:
        """Update a calendar event.

        Args:
            event_id: Calendar event ID.
            **kwargs: Fields to update (title, start_at, end_at, description,
                location_name, all_day).

        Returns:
            The updated event.
        """
        resp = self._client.put(
            f"/calendar_events/{event_id}", data=_calendar_event_form(kwargs)
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasCalendarEvent, strict=False)

    def delete_calendar_event(self, event_id: int) -> None:
        """Delete a calendar event."""
        resp = self._client.delete(f"/calendar_events/{event_id}")
        resp.raise_for_status()


def _calendar_event_form(fields: dict[str, object]) -> dict[str, object]:
    """Wrap fields as ``calendar_event[<key>]`` form params."""
    return {f"calendar_event[{k}]": v for k, v in fields.items()}
