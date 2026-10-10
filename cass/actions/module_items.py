"""Module item rules: command-line arguments and content lookup."""

from __future__ import annotations

__docformat__ = "google"

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from ..apis.canvas.client.files import folder_paths, normalize_folder_path
from .config import MODULE_ITEM_TYPES, ModuleItemSpec, canonical_item_type

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import (
        CanvasAssignmentResponse,
        CanvasFile,
        CanvasFolder,
        CanvasPage,
        CanvasQuiz,
    )

# Which reference flag each item type takes; --title and --indent are always allowed.
_CONTENT_TYPES = ("Assignment", "Quiz", "File")


def check_item_add_args(
    item_type: str,
    *,
    content_id: int | None,
    page_url: str | None,
    url: str | None,
    title: str | None,
) -> str:
    """Check the reference flags given for *item_type*.

    Returns:
        The canonical item type.

    Raises:
        ValueError: If the type is unknown, a required flag is missing, or a
            flag does not belong to the type.
    """
    canonical = canonical_item_type(item_type)
    if canonical is None:
        raise ValueError(
            f"unknown --type {item_type!r} (expected one of: "
            f"{', '.join(MODULE_ITEM_TYPES)})"
        )

    allowed = {
        "--content-id": canonical in _CONTENT_TYPES,
        "--page-url": canonical == "Page",
        "--url": canonical == "ExternalUrl",
    }
    given = {
        "--content-id": content_id is not None,
        "--page-url": bool(page_url),
        "--url": bool(url),
    }
    for flag, is_given in given.items():
        if is_given and not allowed[flag]:
            raise ValueError(f"--type {canonical} does not take {flag}")

    if canonical in _CONTENT_TYPES and content_id is None:
        raise ValueError(f"--type {canonical} needs --content-id")
    if canonical == "Page" and not page_url:
        raise ValueError("--type Page needs --page-url")
    if canonical == "ExternalUrl" and not (url and title):
        raise ValueError("--type ExternalUrl needs --url and --title")
    if canonical == "SubHeader" and not title:
        raise ValueError("--type SubHeader needs --title")
    return canonical


@dataclass
class ContentIndex:
    """Course content a module item can point at, fetched once per run."""

    assignments: list[CanvasAssignmentResponse]
    quizzes: list[CanvasQuiz]
    pages: list[CanvasPage]
    folders: list[CanvasFolder]
    files: list[CanvasFile]
    local_sizes: dict[Path, int] = field(default_factory=dict)
    # Keys are lower-cased paths (e.g. "readings/w1.pdf"); normalize every
    # lookup key the same way so matching is case-insensitive.
    uploaded: dict[str, CanvasFile] = field(default_factory=dict)

    def file_path(self, file: CanvasFile) -> str:
        """Path of *file* below the course files root (root files: just the name)."""
        folder = folder_paths(self.folders).get(file.folder_id, "")
        return f"{folder}/{file.display_name}" if folder else file.display_name

    def add_created(self, item_type: str, content_id: int, title: str) -> None:
        """Make an Assignment or Quiz created this run resolvable by title.

        Does nothing when *content_id* is already in the index.
        """
        from ..apis.canvas.schema import CanvasAssignmentResponse, CanvasQuiz

        if item_type == "Assignment":
            if all(a.id != content_id for a in self.assignments):
                self.assignments.append(
                    CanvasAssignmentResponse(id=content_id, name=title)
                )
        elif item_type == "Quiz" and all(q.id != content_id for q in self.quizzes):
            self.quizzes.append(CanvasQuiz(id=content_id, title=title))


@dataclass
class ContentRef:
    """The Canvas content a declared module item points at."""

    item_type: str
    content_id: int | None  # None: a File that will be uploaded first
    page_url: str = ""
    external_url: str = ""
    title: str = ""  # desired item title; "" = not compared
    file: CanvasFile | None = None
    file_path: str = ""


def fetch_content_index(
    client: CanvasClient, *, sources: Iterable[Path] = ()
) -> ContentIndex:
    """Fetch the course content once and read the sizes of local *sources*.

    Raises:
        RuntimeError: If a source file does not exist.
    """
    index = ContentIndex(
        assignments=client.list_assignments(),
        quizzes=client.list_quizzes(),
        pages=client.list_pages(),
        folders=client.list_folders(),
        files=client.list_files(),
    )
    for path in sources:
        try:
            index.local_sizes[path] = os.path.getsize(path)
        except OSError as exc:
            raise RuntimeError(f"Source file not found: {path}") from exc
    return index


_T = TypeVar("_T")
_NON_PLAIN_ASSIGNMENT_TYPES = {"online_quiz", "discussion_topic"}


def _single_match(matches: list[_T], kind: str, ids: list[int]) -> _T:
    """Return the only match, or raise ValueError for none or several."""
    if not matches:
        raise ValueError(f"no {kind} with that title")
    if len(matches) > 1:
        id_list = ", ".join(str(i) for i in ids)
        raise ValueError(f"{len(matches)} {kind}s have that title (IDs: {id_list})")
    return matches[0]


def _resolve_file(spec: ModuleItemSpec, index: ContentIndex) -> ContentRef:
    wanted = normalize_folder_path(spec.file)
    key = wanted.lower()

    root = next((f for f in index.folders if f.parent_folder_id is None), None)
    if root and key.split("/")[0] == root.name.lower():
        raise ValueError(
            f"drop the '{root.name}/' prefix; paths start below the course files root"
        )

    known = {f.id: f for f in index.files}
    known.update({f.id: f for f in index.uploaded.values()})
    matches = [f for f in known.values() if index.file_path(f).lower() == key]
    if matches:
        file = _single_match(matches, "file", [f.id for f in matches])
        return ContentRef(
            "File", file.id, title=spec.title, file=file, file_path=wanted
        )

    if spec.source is not None:
        return ContentRef("File", None, title=spec.title, file_path=wanted)

    name = wanted.rsplit("/", 1)[-1].lower()
    paths = folder_paths(index.folders)
    elsewhere = [
        paths.get(f.folder_id, "")
        for f in index.files
        if f.display_name.lower() == name
    ]
    if elsewhere:
        folders = ", ".join(
            f"'{p}'" if p else "the course files root" for p in elsewhere
        )
        raise ValueError(f"not found; a file with that name is in {folders}")
    raise ValueError("not found in course files")


def resolve_content(spec: ModuleItemSpec, index: ContentIndex) -> ContentRef:
    """Find the Canvas content a declared item points at.

    Titles match case-insensitively; Files match by path.

    Raises:
        ValueError: With the problem, if the content is missing or ambiguous.
    """
    item_type = canonical_item_type(spec.type)
    title = spec.title.strip().lower()

    if item_type == "Assignment":
        plain = [
            a
            for a in index.assignments
            if not _NON_PLAIN_ASSIGNMENT_TYPES & set(a.submission_types)
            and a.name.lower() == title
        ]
        found = _single_match(plain, "assignment", [a.id for a in plain])
        return ContentRef(item_type, found.id, title=found.name)
    if item_type == "Quiz":
        quizzes = [q for q in index.quizzes if q.title.lower() == title]
        quiz = _single_match(quizzes, "quiz", [q.id for q in quizzes])
        return ContentRef(item_type, quiz.id, title=quiz.title)
    if item_type == "Page":
        pages = [p for p in index.pages if p.title.lower() == title]
        page = _single_match(pages, "page", [p.page_id for p in pages])
        return ContentRef(item_type, page.page_id, page_url=page.url, title=page.title)
    if item_type == "File":
        return _resolve_file(spec, index)
    if item_type == "ExternalUrl":
        return ContentRef(
            item_type, None, external_url=spec.url.strip(), title=spec.title
        )
    if item_type == "SubHeader":
        return ContentRef(item_type, None, title=spec.title)
    raise ValueError(f"unknown item type {spec.type!r}")
