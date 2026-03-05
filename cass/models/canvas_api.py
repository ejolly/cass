"""Canvas LMS API response types."""

from __future__ import annotations

__docformat__ = "google"

import msgspec

from .github_api import GHStudentInfo


# --- Course ---


class CanvasCourse(msgspec.Struct):
    """Canvas course details."""

    id: int
    name: str
    course_code: str = ""
    workflow_state: str = ""
    default_view: str = ""
    enrollment_term_id: int = 0
    total_students: int | None = None
    time_zone: str = ""


# --- Users & Enrollments ---


class CanvasStudent(msgspec.Struct):
    """Canvas student (user enrolled as student)."""

    id: int
    name: str
    sortable_name: str = ""
    email: str = ""
    sis_user_id: str | None = None
    login_id: str = ""


class CanvasEnrollment(msgspec.Struct):
    """Canvas enrollment record."""

    id: int
    user_id: int
    type: str = ""
    enrollment_state: str = ""
    role: str = ""


class CanvasUser(msgspec.Struct):
    """Canvas user with optional enrollments."""

    id: int
    name: str
    sortable_name: str = ""
    email: str = ""
    sis_user_id: str | None = None
    login_id: str = ""
    enrollments: list[CanvasEnrollment] = []


# --- Modules ---


class CanvasModuleItem(msgspec.Struct):
    """Single item within a Canvas module."""

    id: int
    title: str
    type: str = ""
    content_id: int = 0
    position: int = 0
    published: bool | None = None
    html_url: str = ""
    module_id: int = 0


class CanvasModule(msgspec.Struct):
    """Canvas module (content grouping)."""

    id: int
    name: str
    position: int = 0
    published: bool | None = None
    items_count: int = 0
    items_url: str = ""


# --- Assignments & Groups ---


class CanvasAssignment(msgspec.Struct):
    """Canvas assignment."""

    id: int
    name: str
    points_possible: float = 0.0
    due_at: str | None = None
    published: bool = False
    submission_types: list[str] = []
    grading_type: str = ""
    assignment_group_id: int = 0
    position: int | None = None
    html_url: str = ""
    description: str | None = None
    lock_at: str | None = None
    unlock_at: str | None = None
    has_submitted_submissions: bool = False
    workflow_state: str = ""


class CanvasAssignmentGroup(msgspec.Struct):
    """Canvas assignment group (weighted grade category)."""

    id: int
    name: str
    position: int = 0
    group_weight: float = 0.0
    rules: dict = {}  # noqa: RUF012


# --- Quizzes ---


class CanvasQuiz(msgspec.Struct):
    """Canvas quiz."""

    id: int
    title: str
    quiz_type: str = ""
    published: bool = False
    time_limit: int | None = None
    question_count: int = 0
    points_possible: float | None = None
    assignment_id: int | None = None
    html_url: str = ""
    description: str | None = None


# --- Files & Folders ---


class CanvasFile(msgspec.Struct):
    """Canvas file metadata."""

    id: int
    display_name: str
    filename: str = ""
    size: int = 0
    content_type: str = msgspec.field(default="", name="content-type")
    url: str = ""
    folder_id: int = 0
    created_at: str = ""
    updated_at: str = ""


class CanvasFolder(msgspec.Struct):
    """Canvas folder in the file hierarchy."""

    id: int
    name: str
    full_name: str = ""
    parent_folder_id: int | None = None
    files_count: int = 0
    folders_count: int = 0
    position: int | None = None


# --- Announcements (backed by discussion_topics API) ---


class CanvasAnnouncement(msgspec.Struct):
    """Canvas announcement (discussion_topic with is_announcement=true)."""

    id: int
    title: str
    message: str = ""
    posted_at: str | None = None
    user_name: str = ""


# --- Tabs ---


class CanvasTab(msgspec.Struct):
    """Canvas course navigation tab."""

    id: str  # Canvas tab IDs are strings
    label: str
    type: str = ""
    position: int | None = None
    visibility: str = ""
    hidden: bool | None = None


# --- Submissions (used by existing grading flow) ---


class CanvasSubmission(msgspec.Struct):
    """Canvas submission record."""

    user_id: int
    submitted_at: str | None = None
    late: bool = False
    missing: bool = False
    seconds_late: float = 0.0
    grade: str | None = None
    score: float | None = None
    workflow_state: str = ""


# --- Matching ---


class MatchResult(msgspec.Struct):
    """Result of matching GitHub students to Canvas students."""

    matched: dict[str, int]  # gh_login -> canvas_id
    unmatched_gh: list[GHStudentInfo]
    unmatched_canvas: list[CanvasStudent]
