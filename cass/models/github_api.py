"""GitHub Classroom API response types."""

from __future__ import annotations

import msgspec


class GHStudentInfo(msgspec.Struct):
    """GitHub student info aggregated from accepted assignments + profiles."""

    login: str
    id: str = ""
    name: str = ""
    email: str = ""


class GHAssignment(msgspec.Struct):
    id: int
    slug: str
    title: str
    deadline: str | None = None
    accepted: int = 0
    submissions: int = 0
    passing: int = 0


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


class GHProfile(msgspec.Struct):
    login: str
    name: str | None = None
    email: str | None = None


class GHCommitter(msgspec.Struct):
    date: str = ""


class GHCommitInfo(msgspec.Struct):
    committer: GHCommitter = msgspec.field(default_factory=GHCommitter)


class GHCommit(msgspec.Struct):
    commit: GHCommitInfo = msgspec.field(default_factory=GHCommitInfo)


class GHContentItem(msgspec.Struct):
    type: str = ""
    name: str = ""
    download_url: str | None = None
