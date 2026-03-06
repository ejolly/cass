"""Canvas LMS integration — roster matching, grade sync, and domain conversion.

Business logic for matching GitHub and Canvas students, converting Canvas API
responses to domain types, and pushing grades. All raw API calls are delegated
to ``CanvasClient`` in ``canvas_api.py``.
"""

from __future__ import annotations

__docformat__ = "google"

import re
from datetime import datetime

from ..models import (
    CanvasAssignment,
    CanvasStudent,
    CanvasSubmission,
    GHStudentInfo,
    MatchResult,
)
from .client import CanvasClient, get_token, save_token

# Re-export for backwards compatibility (used by cli.py init)
__all__ = [
    "fetch_canvas_assignments",
    "fetch_canvas_submissions",
    "fetch_students",
    "fetch_students_with_sections",
    "find_candidates",
    "get_token",
    "match_students",
    "push_grade",
    "save_token",
]


# --- API functions (delegate to CanvasClient) ---


def fetch_students(course_id: int) -> list[CanvasStudent]:
    """Fetch all students enrolled in a Canvas course."""
    with CanvasClient(course_id=course_id) as c:
        return c.list_students()


def fetch_students_with_sections(
    course_id: int,
) -> tuple[list[CanvasStudent], dict[int, str]]:
    """Fetch students and build a canvas_id → sis_section_id mapping.

    Uses the users endpoint (with enrollments) and sections endpoint
    to resolve each student's SIS section ID.

    Returns:
        Tuple of (students, sis_section_map) where sis_section_map maps
        canvas_id to sis_section_id.
    """
    with CanvasClient(course_id=course_id) as c:
        students = c.list_students()

        # Fetch users with enrollment data to get course_section_id
        users = c.list_users(enrollment_type="student")
        user_section: dict[int, int] = {}
        for u in users:
            for e in u.enrollments:
                if e.course_section_id and e.type == "StudentEnrollment":
                    user_section[u.id] = e.course_section_id
                    break

        # Fetch sections to get sis_section_id
        sections = c.list_sections()
        section_sis: dict[int, str] = {
            s.id: s.sis_section_id for s in sections if s.sis_section_id
        }

        # Map: student canvas_id → sis_section_id
        sis_section_map: dict[int, str] = {}
        for student in students:
            sec_id = user_section.get(student.id)
            if sec_id and sec_id in section_sis:
                sis_section_map[student.id] = section_sis[sec_id]

    return students, sis_section_map


def fetch_canvas_assignments(
    course_id: int,
) -> tuple[list[CanvasAssignment], dict[int, str]]:
    """Fetch all assignments and assignment group names from Canvas.

    Returns:
        Tuple of (assignments, group_names) where group_names maps
        assignment_group_id to group name.
    """
    with CanvasClient(course_id=course_id) as c:
        assignments = c.list_assignments()
        groups = c.list_assignment_groups()
        group_names = {g.id: g.name for g in groups}
        return assignments, group_names


def fetch_canvas_submissions(
    course_id: int,
    canvas_assignment_id: int,
    known_canvas_ids: set[int],
) -> list[CanvasSubmission]:
    """Fetch submissions for a Canvas assignment, filtered to known students.

    Args:
        course_id: Canvas course ID.
        canvas_assignment_id: Canvas assignment ID.
        known_canvas_ids: Set of canvas_ids from the students table.

    Returns:
        CanvasSubmission domain objects for known students.
    """
    with CanvasClient(course_id=course_id) as c:
        raw = c.list_submissions(canvas_assignment_id)

    submissions: list[CanvasSubmission] = []
    for r in raw:
        if r.user_id not in known_canvas_ids:
            continue

        submitted_at = None
        if r.submitted_at:
            try:
                submitted_at = datetime.fromisoformat(r.submitted_at)
            except ValueError:
                pass

        submissions.append(
            CanvasSubmission(
                canvas_user_id=r.user_id,
                canvas_assignment_id=canvas_assignment_id,
                submitted=r.workflow_state in ("submitted", "graded", "pending_review"),
                submitted_at=submitted_at,
                late=r.late,
                lateness_seconds=int(r.seconds_late),
                score=r.score,
                workflow_state=r.workflow_state,
            )
        )

    return submissions


def push_grade(
    course_id: int, assignment_id: int, student_canvas_id: int, grade: str
) -> bool:
    """Push a single grade to Canvas. Returns True on success, False on failure."""
    with CanvasClient(course_id=course_id) as c:
        return c.push_grade(assignment_id, student_canvas_id, grade)


# --- Name matching ---
_NON_ALPHA_RE = re.compile(r"[^a-z\s]")


def normalize(name: str) -> str:
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
    """Match GitHub students to Canvas students by normalized name."""
    canvas_by_name: dict[str, CanvasStudent] = {}
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
    canvas_pool: list[CanvasStudent],
) -> list[CanvasStudent]:
    """Rank Canvas students by name similarity to a GitHub student."""
    gh_name = gh_student.name or gh_student.login
    gh_tokens = set(normalize(gh_name).split())
    if not gh_tokens:
        return canvas_pool[:5]

    scored: list[tuple[int, CanvasStudent]] = []
    for c in canvas_pool:
        c_tokens = set(normalize(c.name).split())
        overlap = len(gh_tokens & c_tokens)
        if overlap > 0:
            scored.append((overlap, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


# --- Helpers ---


def slugify(name: str) -> str:
    """Convert a Canvas assignment name to a URL-safe identifier."""
    name = name.lower().strip()
    for sep in (" ", "_", "/", "(", ")"):
        name = name.replace(sep, "-")
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip("-")
