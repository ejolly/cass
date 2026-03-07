"""GitHub Classroom API response types."""

from __future__ import annotations

__docformat__ = "google"

import msgspec


class GHStudentInfo(msgspec.Struct):
    """GitHub student info aggregated from accepted assignments + profiles."""

    login: str
    id: str = ""
    name: str = ""
    email: str = ""


class GHStarterCodeRepo(msgspec.Struct):
    """Starter code / template repository for a GitHub Classroom assignment."""

    id: int = 0
    full_name: str = ""


class GHAssignment(msgspec.Struct):
    id: int
    slug: str
    title: str
    deadline: str | None = None
    accepted: int = 0
    submissions: int = 0
    passing: int = 0
    starter_code_repository: GHStarterCodeRepo | None = None


class GHStudent(msgspec.Struct):
    id: int
    login: str


class GHRepository(msgspec.Struct):
    id: int
    full_name: str


class GHAcceptedAssignment(msgspec.Struct):
    id: int
    students: list[GHStudent] = []
    repository: GHRepository | None = None
    commit_count: int = 0
    submitted: bool = False
    passing: bool = False
    grade: str | None = None


class GHCommitter(msgspec.Struct):
    date: str = ""


class GHCommitInfo(msgspec.Struct):
    committer: GHCommitter = msgspec.field(default_factory=GHCommitter)


class GHCommit(msgspec.Struct):
    commit: GHCommitInfo = msgspec.field(default_factory=GHCommitInfo)


class GHRosterEntry(msgspec.Struct):
    """Entry from the /assignments/{id}/grades endpoint (roster name + GH username)."""

    github_username: str
    roster_identifier: str = ""
    student_repository_name: str = ""
    student_repository_url: str = ""
    submission_timestamp: str = ""
    points_awarded: str = ""
    points_available: str = ""


class GHContentItem(msgspec.Struct):
    type: str = ""
    name: str = ""
    download_url: str | None = None
