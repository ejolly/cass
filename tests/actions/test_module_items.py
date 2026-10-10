"""Tests for module item content lookup."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cass.actions.config import ModuleItemSpec
from cass.actions.module_items import (
    ContentIndex,
    fetch_content_index,
    resolve_content,
)
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasFile,
    CanvasFolder,
    CanvasPage,
    CanvasQuiz,
)


@pytest.fixture
def index() -> ContentIndex:
    return ContentIndex(
        assignments=[
            CanvasAssignmentResponse(id=7, name="HW1"),
            CanvasAssignmentResponse(
                id=8, name="Quiz 1", submission_types=["online_quiz"]
            ),
            CanvasAssignmentResponse(id=9, name="Dup"),
            CanvasAssignmentResponse(id=10, name="dup"),
        ],
        quizzes=[CanvasQuiz(id=20, title="Quiz 1")],
        pages=[CanvasPage(page_id=3, url="syllabus", title="Syllabus")],
        folders=[
            CanvasFolder(id=2, name="course files", full_name="course files"),
            CanvasFolder(
                id=3,
                name="readings",
                full_name="course files/readings",
                parent_folder_id=2,
            ),
            CanvasFolder(
                id=4, name="old", full_name="course files/old", parent_folder_id=2
            ),
        ],
        files=[
            CanvasFile(id=70, display_name="w1.pdf", folder_id=3, size=10),
            CanvasFile(id=71, display_name="w2.pdf", folder_id=4),
        ],
    )


def test_resolves_assignment_by_title_case_insensitive(index):
    ref = resolve_content(ModuleItemSpec(type="Assignment", title="hw1"), index)
    assert ref.content_id == 7
    assert ref.title == "HW1"


def test_assignment_lookup_skips_quiz_assignments(index):
    with pytest.raises(ValueError, match="no assignment"):
        resolve_content(ModuleItemSpec(type="Assignment", title="Quiz 1"), index)
    ref = resolve_content(ModuleItemSpec(type="Quiz", title="Quiz 1"), index)
    assert ref.content_id == 20


def test_ambiguous_title_names_ids(index):
    with pytest.raises(
        ValueError, match=r"2 assignments have that title \(IDs: 9, 10\)"
    ):
        resolve_content(ModuleItemSpec(type="Assignment", title="DUP"), index)


def test_page_resolves_to_page_url(index):
    ref = resolve_content(ModuleItemSpec(type="Page", title="syllabus"), index)
    assert ref.page_url == "syllabus"


def test_file_by_path(index):
    ref = resolve_content(ModuleItemSpec(type="File", file="readings/w1.pdf"), index)
    assert ref.content_id == 70
    assert ref.file_path == "readings/w1.pdf"


def test_file_in_wrong_folder_names_folder(index):
    with pytest.raises(ValueError, match="'old'"):
        resolve_content(ModuleItemSpec(type="File", file="readings/w2.pdf"), index)


def test_missing_file_with_source_is_upload(index):
    spec = ModuleItemSpec(type="File", file="readings/new.pdf", source=Path("new.pdf"))
    assert resolve_content(spec, index).content_id is None


def test_missing_file_without_match_is_not_found(index):
    with pytest.raises(ValueError, match="not found in course files"):
        resolve_content(ModuleItemSpec(type="File", file="readings/zzz.pdf"), index)


def test_file_path_with_root_prefix_errors(index):
    spec = ModuleItemSpec(type="File", file="course files/readings/w1.pdf")
    with pytest.raises(ValueError, match="drop the 'course files/' prefix"):
        resolve_content(spec, index)


def test_external_url_and_subheader(index):
    link = resolve_content(
        ModuleItemSpec(type="ExternalUrl", title="Site", url=" https://x.org "), index
    )
    assert (link.external_url, link.title) == ("https://x.org", "Site")
    header = resolve_content(ModuleItemSpec(type="SubHeader", title="Week 1"), index)
    assert (header.content_id, header.title) == (None, "Week 1")


def test_add_created_skips_known_ids(index):
    index.add_created("Assignment", -3, "HW9")
    assert (
        resolve_content(
            ModuleItemSpec(type="Assignment", title="HW9"), index
        ).content_id
        == -3
    )
    index.add_created("Assignment", 7, "HW1")
    assert sum(a.name == "HW1" for a in index.assignments) == 1


def test_fetch_content_index_reads_each_list_once(tmp_path):
    client = MagicMock()
    source = tmp_path / "a.pdf"
    source.write_bytes(b"12345")

    index = fetch_content_index(client, sources=[source])

    for method in (
        client.list_assignments,
        client.list_quizzes,
        client.list_pages,
        client.list_folders,
        client.list_files,
    ):
        method.assert_called_once_with()
    assert index.local_sizes[source] == 5

    missing = tmp_path / "gone.pdf"
    with pytest.raises(RuntimeError, match=r"gone\.pdf"):
        fetch_content_index(client, sources=[missing])
