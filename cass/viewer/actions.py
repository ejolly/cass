"""Push preview rendering for the viewer.

The data comes from the core (``cass.db.canvas_preview``); this module only
turns it into HTML.
"""

from __future__ import annotations

__docformat__ = "google"

from html import escape

# ---------------------------------------------------------------------------
# Push preview HTML
# ---------------------------------------------------------------------------


def build_preview_html(
    assignment_changes: list[dict[str, object]],
    grade_changes: list[dict[str, object]],
    has_conflicts: bool,
) -> str:
    """Build HTML for the push preview tables."""
    parts: list[str] = []

    if assignment_changes:
        parts.append("<h4 class='v-preview-header'>Assignment changes</h4>")
        parts.append('<table class="push-table"><thead><tr>')
        for h in ("Assignment", "Field", "On Canvas", "New value"):
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for ch in assignment_changes:
            cls = (
                "error-row"
                if "error" in ch
                else "conflict-row"
                if ch.get("conflict")
                else ""
            )
            parts.append(f'<tr class="{cls}">')
            if "error" in ch:
                name = escape(str(ch.get("name", "")))
                err = escape(str(ch.get("error", "")))
                parts.append(f'<td colspan="4" class="v-text-error">{name}: {err}</td>')
            else:
                name = escape(str(ch.get("name", "")))
                col = escape(str(ch.get("column", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}</td>")
                parts.append(f"<td>{col}{warn}</td>")
                parts.append(f'<td class="opacity-50">{live}</td>')
                parts.append(f'<td class="font-semibold">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if grade_changes:
        parts.append("<h4 class='v-preview-header-spaced'>Grade changes</h4>")
        parts.append('<table class="push-table"><thead><tr>')
        for h in ("Student \u2014 Assignment", "On Canvas", "New grade"):
            parts.append(f"<th>{h}</th>")
        parts.append("</tr></thead><tbody>")
        for ch in grade_changes:
            cls = (
                "error-row"
                if "error" in ch
                else "conflict-row"
                if ch.get("conflict")
                else ""
            )
            parts.append(f'<tr class="{cls}">')
            if "error" in ch:
                name = escape(str(ch.get("name", "")))
                err = escape(str(ch.get("error", "")))
                parts.append(f'<td colspan="3" class="v-text-error">{name}: {err}</td>')
            else:
                name = escape(str(ch.get("name", "")))
                warn = " \u26a0" if ch.get("conflict") else ""
                live = escape(str(ch.get("live", "null")))
                cur = escape(str(ch.get("current", "null")))
                parts.append(f"<td>{name}{warn}</td>")
                parts.append(f'<td class="opacity-50">{live}</td>')
                parts.append(f'<td class="font-semibold">{cur}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    if has_conflicts:
        parts.append(
            '<div class="v-conflict-warning">'
            "\u26a0 Some Canvas values differ from when you "
            "last pulled. They are held back unless you approve them below.</div>"
        )

    return "".join(parts)
