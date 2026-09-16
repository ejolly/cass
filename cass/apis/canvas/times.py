"""Course-local time handling for Canvas timestamps.

Canvas stores instants in UTC. Users type times in the course's own zone.
``parse_when`` turns a user string into an ISO 8601 instant with an offset;
``format_when`` renders a Canvas instant in the course zone.
"""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime
from zoneinfo import ZoneInfo


def parse_when(value: str, tz: str) -> str:
    """Parse a user-entered time into ISO 8601 with an offset.

    Accepts ``YYYY-MM-DD``, ``YYYY-MM-DD HH:MM``, ``YYYY-MM-DDTHH:MM`` and
    full ISO 8601. Naive values are localized to *tz*; a date alone means
    midnight. Values that already carry an offset are returned unchanged.

    Raises:
        RuntimeError: If the value cannot be parsed or *tz* is empty.
    """
    text = value.strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        raise RuntimeError(
            f"Unrecognized time {value!r}; use YYYY-MM-DD, YYYY-MM-DD HH:MM, "
            "or ISO 8601 with an offset"
        ) from None
    if parsed.tzinfo is not None:
        return text
    if not tz:
        raise RuntimeError(
            "Course time zone is unknown; add time_zone to [canvas] in cass.toml "
            "or run 'cass init'."
        )
    return parsed.replace(tzinfo=ZoneInfo(tz)).isoformat()


def format_when(iso: str | None, tz: str, *, date_only: bool = False) -> str:
    """Render an ISO instant in *tz* as ``YYYY-MM-DD HH:MM`` (or the date)."""
    if not iso:
        return ""
    local = datetime.fromisoformat(iso).astimezone(ZoneInfo(tz))
    return local.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M")


def same_instant(a: str | None, b: str | None) -> bool:
    """Compare two ISO timestamps by the moment they name, not their spelling.

    Canvas returns UTC (``...Z``) while cass.toml may use a local offset.
    Unparseable values fall back to plain string comparison.
    """
    if not a and not b:
        return True
    if not a or not b:
        return False
    try:
        return datetime.fromisoformat(a) == datetime.fromisoformat(b)
    except ValueError:
        return a == b
