"""cass data models — domain types, API response types, and grading logic."""

from .canvas_api import (
    CanvasAssignment,
    CanvasStudent,
    CanvasSubmission,
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
    "CanvasAssignment",
    "CanvasStudent",
    "CanvasSubmission",
    "MatchResult",
    # Grading
    "_format_lateness",
    "compute_grade",
    "numeric_grade",
]
