"""Canvas LMS integration — roster fetching, submission retrieval, and grade push.

All raw API calls are delegated to ``CanvasClient`` in ``client.py``.
Matching logic (name normalization, student matching, slug utilities) has
been moved to ``cass.actions.matching``.
"""

from __future__ import annotations

__docformat__ = "google"

from datetime import datetime

from ...db.schema import CanvasSubmission
from .client import CanvasClient, get_token, save_token
from .schema import CanvasAssignmentResponse, CanvasStudentResponse

# Re-export for backwards compatibility (used by cli.py init)
__all__ = [
    "fetch_canvas_assignments",
    "fetch_canvas_submissions",
    "fetch_course_name",
    "fetch_students",
    "fetch_students_with_sections",
    "get_token",
    "push_grade",
    "save_token",
]


# --- API functions (delegate to CanvasClient) ---


def fetch_students(course_id: int) -> list[CanvasStudentResponse]:
    """Fetch all students enrolled in a Canvas course."""
    with CanvasClient(course_id=course_id) as c:
        return c.list_students()


def fetch_course_name(course_id: int) -> str:
    """Fetch the course name from the Canvas API."""
    with CanvasClient(course_id=course_id) as c:
        return c.get_course().name


def fetch_students_with_sections(
    course_id: int,
) -> tuple[list[CanvasStudentResponse], dict[int, str]]:
    """Fetch students and build a canvas_id -> sis_section_id mapping.

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

        # Map: student canvas_id -> sis_section_id
        sis_section_map: dict[int, str] = {}
        for student in students:
            sec_id = user_section.get(student.id)
            if sec_id and sec_id in section_sis:
                sis_section_map[student.id] = section_sis[sec_id]

    return students, sis_section_map


def fetch_canvas_assignments(
    course_id: int,
) -> tuple[list[CanvasAssignmentResponse], dict[int, str]]:
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
