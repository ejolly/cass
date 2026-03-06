"""cass data models — domain types, API response types, and grading logic."""

__docformat__ = "google"

from .canvas_api import (
    CanvasAnnouncement,
    CanvasAssignment,
    CanvasAssignmentGroup,
    CanvasCourse,
    CanvasEnrollment,
    CanvasFile,
    CanvasFolder,
    CanvasModule,
    CanvasModuleItem,
    CanvasQuiz,
    CanvasStudent,
    CanvasSubmission,
    CanvasTab,
    CanvasUser,
    MatchResult,
)
from .domain import (
    Assignment,
    DataSource,
    Grade,
    GradeSource,
    Student,
    Submission,
)
from .github_api import (
    GHAcceptedAssignment,
    GHAssignment,
    GHCommit,
    GHCommitInfo,
    GHCommitter,
    GHContentItem,
    GHProfile,
    GHRepository,
    GHStudent,
    GHStudentInfo,
)
from .grading import (
    _format_lateness,
    compute_grade,
    numeric_grade,
)

__all__ = [
    # Domain
    "Assignment",
    "DataSource",
    "Grade",
    "GradeSource",
    "Student",
    "Submission",
    # GitHub API
    "GHAcceptedAssignment",
    "GHAssignment",
    "GHCommit",
    "GHCommitInfo",
    "GHCommitter",
    "GHContentItem",
    "GHProfile",
    "GHRepository",
    "GHStudent",
    "GHStudentInfo",
    # Canvas API
    "CanvasAnnouncement",
    "CanvasAssignment",
    "CanvasAssignmentGroup",
    "CanvasCourse",
    "CanvasEnrollment",
    "CanvasFile",
    "CanvasFolder",
    "CanvasModule",
    "CanvasModuleItem",
    "CanvasQuiz",
    "CanvasStudent",
    "CanvasSubmission",
    "CanvasTab",
    "CanvasUser",
    "MatchResult",
    # Grading
    "_format_lateness",
    "compute_grade",
    "numeric_grade",
]
