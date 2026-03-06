"""Canvas LMS integration — roster matching, grade sync, and domain conversion.

Business logic for matching GitHub ↔ Canvas students, converting Canvas API
responses to domain types, and pushing grades. All raw API calls are delegated
to ``CanvasClient`` in ``canvas_api.py``.
"""

from __future__ import annotations

__docformat__ = "google"

import re
from datetime import datetime

from .canvas_api import CanvasClient, get_token, save_token
from .models import (
    Assignment,
    CanvasStudent,
    GHStudentInfo,
    MatchResult,
    Student,
    Submission,
)

# Re-export for backwards compatibility (used by cli.py init)
__all__ = [
    "get_token",
    "save_token",
    "fetch_students",
    "fetch_assignments",
    "fetch_submissions",
    "push_grade",
    "match_students",
    "find_candidates",
    "mapping_from_roster",
]


# --- API functions (delegate to CanvasClient) ---


def fetch_students(course_id: int) -> list[CanvasStudent]:
    """Fetch all students enrolled in a Canvas course.

    Args:
        course_id: Canvas course ID.

    Returns:
        Students sorted by Canvas enrollment order.
    """
    with CanvasClient(course_id=course_id) as c:
        return c.list_students()


def fetch_assignments(course_id: int) -> list[Assignment]:
    """Fetch all assignments from a Canvas course.

    Converts Canvas API responses to domain ``Assignment`` objects with
    slugified IDs and parsed deadlines.

    Args:
        course_id: Canvas course ID.

    Returns:
        Assignments sorted by slug ID.
    """
    with CanvasClient(course_id=course_id) as c:
        raw = c.list_assignments()

    assignments = []
    for a in raw:
        deadline = None
        if a.due_at:
            try:
                deadline = datetime.fromisoformat(a.due_at.replace("Z", "+00:00"))
            except ValueError:
                pass
        assignments.append(
            Assignment(
                id=_slugify(a.name),
                source="canvas",
                title=a.name,
                canvas_id=a.id,
                deadline=deadline,
                points_possible=a.points_possible,
            )
        )
    return sorted(assignments, key=lambda a: a.id)


def fetch_submissions(
    course_id: int,
    assignment_id: int,
    students: list[Student],
) -> list[Submission]:
    """Fetch submission data for a Canvas assignment.

    Retrieves all submissions via paginated Canvas API calls and maps
    them to known students by ``canvas_id``.

    Args:
        course_id: Canvas course ID.
        assignment_id: Canvas assignment ID.
        students: Roster to match submissions against.

    Returns:
        Submissions sorted by student_id. Students not in the roster
        are silently skipped.
    """
    with CanvasClient(course_id=course_id) as c:
        raw = c.list_submissions(assignment_id)

    # canvas_id -> student identifier
    canvas_to_student: dict[int, str] = {}
    for s in students:
        if s.canvas_id:
            try:
                canvas_to_student[int(s.canvas_id)] = s.display_name
            except ValueError:
                pass

    assignment_id_str = _slugify_canvas_id(assignment_id)
    submissions = []
    for r in raw:
        student_id = canvas_to_student.get(r.user_id)
        if not student_id:
            continue

        submitted_at = None
        if r.submitted_at:
            try:
                submitted_at = datetime.fromisoformat(
                    r.submitted_at.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        sub = Submission(
            student_id=student_id,
            assignment_id=assignment_id_str,
            source="canvas",
            submitted=r.workflow_state in ("submitted", "graded", "pending_review"),
            submitted_at=submitted_at,
            late=r.late,
            lateness_seconds=int(r.seconds_late),
            score=r.score,
            workflow_state=r.workflow_state,
        )
        submissions.append(sub)

    return sorted(submissions, key=lambda s: s.student_id)


def push_grade(
    course_id: int, assignment_id: int, student_canvas_id: int, grade: str
) -> bool:
    """Push a single grade to Canvas. Returns True on success, False on failure."""
    with CanvasClient(course_id=course_id) as c:
        return c.push_grade(assignment_id, student_canvas_id, grade)


# --- Name matching ---
_NON_ALPHA_RE = re.compile(r"[^a-z\s]")


def _normalize(name: str) -> str:
    name = name.lower().strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    name = _NON_ALPHA_RE.sub("", name)
    return " ".join(sorted(name.split()))


def match_students(
    gh_students: list[GHStudentInfo],
    canvas_students: list[CanvasStudent],
) -> MatchResult:
    """Match GitHub students to Canvas students by normalized name.

    Uses exact normalized-name matching first, then falls back to
    token-subset matching for partial name overlaps.

    Args:
        gh_students: Students discovered from GitHub Classroom.
        canvas_students: Students enrolled in the Canvas course.

    Returns:
        A ``MatchResult`` with matched pairs, unmatched GitHub students,
        and unmatched Canvas students.
    """
    canvas_by_name: dict[str, CanvasStudent] = {}
    for cs in canvas_students:
        for field in (cs.name, cs.sortable_name):
            key = _normalize(field)
            if key:
                canvas_by_name[key] = cs

    matched: dict[str, int] = {}
    used_canvas_ids: set[int] = set()
    unmatched_gh: list[GHStudentInfo] = []

    for gh in gh_students:
        if gh.name:
            key = _normalize(gh.name)
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
    canvas_pool: list[CanvasStudent],
) -> list[CanvasStudent]:
    """Rank Canvas students by name similarity to a GitHub student.

    Used during interactive resolution of unmatched students.

    Args:
        gh_student: The unmatched GitHub student.
        canvas_pool: Remaining unmatched Canvas students to search.

    Returns:
        Canvas students sorted by descending name-token overlap.
    """
    gh_name = gh_student.name or gh_student.login
    gh_tokens = set(_normalize(gh_name).split())
    if not gh_tokens:
        return canvas_pool[:5]

    scored = []
    for c in canvas_pool:
        c_tokens = set(_normalize(c.name).split())
        overlap = len(gh_tokens & c_tokens)
        if overlap > 0:
            scored.append((overlap, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def mapping_from_roster(students: list[Student]) -> dict[str, int]:
    """Build a GitHub-username-to-Canvas-ID mapping from the roster.

    Args:
        students: The full student roster.

    Returns:
        Dict mapping ``github_username`` to ``canvas_id`` for students
        that have both fields populated.
    """
    mapping: dict[str, int] = {}
    for s in students:
        if s.canvas_id and s.github_username:
            try:
                mapping[s.github_username] = int(s.canvas_id)
            except ValueError:
                pass
    return mapping


# --- Helpers ---


def _slugify(name: str) -> str:
    """Convert a Canvas assignment name to a URL-safe identifier."""
    name = name.lower().strip()
    for sep in (" ", "_", "/", "(", ")"):
        name = name.replace(sep, "-")
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip("-")


def _slugify_canvas_id(assignment_id: int) -> str:
    return f"canvas-{assignment_id}"
