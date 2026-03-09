"""Cross-service student matching and slug utilities.

Matches GitHub Classroom students to Canvas LMS students by normalized
name, and provides slug-based assignment matching helpers.
"""

from __future__ import annotations

__docformat__ = "google"

import re

import msgspec

from ..apis.canvas.schema import CanvasStudentResponse
from ..apis.github.schema import GHStudentInfo

# --- Matching result ---


class MatchResult(msgspec.Struct):
    """Result of matching GitHub students to Canvas students."""

    matched: dict[str, int]  # gh_login -> canvas_id
    unmatched_gh: list[GHStudentInfo]
    unmatched_canvas: list[CanvasStudentResponse]


# --- Name matching ---

_NON_ALPHA_RE = re.compile(r"[^a-z\s]")


def normalize(name: str) -> str:
    """Normalize a name for matching (lowercase, handle 'Last, First', sort tokens)."""
    name = name.lower().strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    name = _NON_ALPHA_RE.sub("", name)
    return " ".join(sorted(name.split()))


def match_students(
    gh_students: list[GHStudentInfo],
    canvas_students: list[CanvasStudentResponse],
) -> MatchResult:
    """Match GitHub students to Canvas students by normalized name."""
    canvas_by_name: dict[str, CanvasStudentResponse] = {}
    for cs in canvas_students:
        for field in (cs.name, cs.sortable_name):
            key = normalize(field)
            if key:
                canvas_by_name[key] = cs

    matched: dict[str, int] = {}
    used_canvas_ids: set[int] = set()
    unmatched_gh: list[GHStudentInfo] = []

    for gh in gh_students:
        if gh.name:
            key = normalize(gh.name)
            if key in canvas_by_name:
                cs = canvas_by_name[key]
                matched[gh.login] = cs.id
                used_canvas_ids.add(cs.id)
                continue

            gh_tokens = set(key.split())
            if len(gh_tokens) >= 2:
                found = False
                for cname, cs in canvas_by_name.items():
                    if cs.id in used_canvas_ids:
                        continue
                    if gh_tokens.issubset(set(cname.split())):
                        matched[gh.login] = cs.id
                        used_canvas_ids.add(cs.id)
                        found = True
                        break
                if found:
                    continue

        unmatched_gh.append(gh)

    unmatched_canvas = [cs for cs in canvas_students if cs.id not in used_canvas_ids]
    return MatchResult(
        matched=matched,
        unmatched_gh=unmatched_gh,
        unmatched_canvas=unmatched_canvas,
    )


def find_candidates(
    gh_student: GHStudentInfo,
    canvas_pool: list[CanvasStudentResponse],
) -> list[CanvasStudentResponse]:
    """Rank Canvas students by name similarity to a GitHub student."""
    gh_name = gh_student.name or gh_student.login
    gh_tokens = set(normalize(gh_name).split())
    if not gh_tokens:
        return canvas_pool[:5]

    scored: list[tuple[int, CanvasStudentResponse]] = []
    for c in canvas_pool:
        c_tokens = set(normalize(c.name).split())
        overlap = len(gh_tokens & c_tokens)
        if overlap > 0:
            scored.append((overlap, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


# --- Slug utilities ---


def slugify(name: str) -> str:
    """Convert a Canvas assignment name to a URL-safe identifier."""
    name = name.lower().strip()
    for sep in (" ", "_", "/", "(", ")"):
        name = name.replace(sep, "-")
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip("-")


def slug_match(gh_slug: str, canvas_slug: str) -> bool:
    """Check if a GH slug matches a Canvas slug by token overlap."""
    gh_tokens = set(gh_slug.replace("-", " ").split())
    cv_tokens = set(canvas_slug.replace("-", " ").split())
    overlap = len(gh_tokens & cv_tokens)
    return overlap > 0 and overlap >= min(len(gh_tokens), len(cv_tokens))
