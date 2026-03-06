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
    CanvasGradingSchemeEntry,
    CanvasGradingStandard,
    CanvasModule,
    CanvasModuleItem,
    CanvasQuiz,
    CanvasSection,
    CanvasStudent,
    CanvasSubmissionResponse,
    CanvasTab,
    CanvasUser,
    MatchResult,
)
from .domain import (
    Assignment,
    CanvasGrade,
    CanvasSubmission,
    GHGrade,
    GHSubmission,
    GradeSource,
    Student,
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
    GHRosterEntry,
    GHStudent,
    GHStudentInfo,
)
from .grading import (
    _format_lateness,
    compute_canvas_grade,
    compute_gh_grade,
    numeric_grade,
)

__all__ = [
    # Domain
    "Assignment",
    "CanvasGrade",
    "CanvasSubmission",
    "GHGrade",
    "GHSubmission",
    "GradeSource",
    "Student",
    # GitHub API
    "GHAcceptedAssignment",
    "GHAssignment",
    "GHCommit",
    "GHCommitInfo",
    "GHCommitter",
    "GHContentItem",
    "GHProfile",
    "GHRepository",
    "GHRosterEntry",
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
    "CanvasGradingSchemeEntry",
    "CanvasGradingStandard",
    "CanvasModule",
    "CanvasModuleItem",
    "CanvasQuiz",
    "CanvasSection",
    "CanvasStudent",
    "CanvasSubmissionResponse",
    "CanvasTab",
    "CanvasUser",
    "MatchResult",
    # Grading
    "_format_lateness",
    "compute_canvas_grade",
    "compute_gh_grade",
    "numeric_grade",
]
