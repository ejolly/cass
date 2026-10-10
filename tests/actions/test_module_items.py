"""Tests for module item content lookup and planning."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cass.actions.config import CanvasModuleSpec, ModuleItemSpec
from cass.actions.module_items import (
    ContentIndex,
    fetch_content_index,
    item_plan_rows,
    plan_module_items,
    plan_module_spec_items,
    resolve_content,
)
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasFile,
    CanvasFolder,
    CanvasModuleItem,
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


# --- planning -----------------------------------------------------------------

HEADER = ModuleItemSpec(type="SubHeader", title="Week 1")
HW1 = ModuleItemSpec(type="Assignment", title="HW1")
READING = ModuleItemSpec(type="File", file="readings/w1.pdf")
SITE = ModuleItemSpec(type="ExternalUrl", title="Site", url="https://x.org")


def live_header(item_id: int = 1, title: str = "Week 1") -> CanvasModuleItem:
    return CanvasModuleItem(id=item_id, title=title, type="SubHeader")


def live_hw1(item_id: int = 2, title: str = "HW1", indent: int = 0):
    return CanvasModuleItem(
        id=item_id, title=title, type="Assignment", content_id=7, indent=indent
    )


def live_reading(item_id: int = 3) -> CanvasModuleItem:
    return CanvasModuleItem(id=item_id, title="w1.pdf", type="File", content_id=70)


def live_site(item_id: int = 4, title: str = "Site") -> CanvasModuleItem:
    return CanvasModuleItem(
        id=item_id, title=title, type="ExternalUrl", external_url="https://x.org"
    )


def actions(plan) -> list[str]:
    return [change.action for change in plan.items]


def test_all_matching_is_keep(index):
    live = [live_header(), live_hw1(), live_reading(), live_site()]
    plan = plan_module_items([HEADER, HW1, READING, SITE], live, index, prune=False)
    assert actions(plan) == ["keep"] * 4
    assert plan.has_changes is False
    assert plan.order_changed is False


def test_create_when_no_live_match(index):
    plan = plan_module_items([HEADER, HW1, READING, SITE], [], index, prune=False)
    assert actions(plan) == ["create"] * 4
    assert plan.has_changes is True


def test_update_names_changed_fields(index):
    plan = plan_module_items(
        [HW1], [live_hw1(title="hw1 (old)", indent=1)], index, prune=False
    )
    [change] = plan.items
    assert change.action == "update"
    assert change.changed == ["title", "indent"]


def test_unchanged_published_omitted_is_never_compared(index):
    live = CanvasModuleItem(
        id=2, title="HW1", type="Assignment", content_id=7, published=False
    )
    plan = plan_module_items([HW1], [live], index, prune=False)
    assert actions(plan) == ["keep"]


def test_published_declared_is_compared(index):
    live = CanvasModuleItem(
        id=2, title="HW1", type="Assignment", content_id=7, published=False
    )
    spec = ModuleItemSpec(type="Assignment", title="HW1", published=True)
    [change] = plan_module_items([spec], [live], index, prune=False).items
    assert (change.action, change.changed) == ("update", ["published"])


def test_subheader_rename_is_update(index):
    spec = ModuleItemSpec(type="SubHeader", title="Week 1 readings")
    [change] = plan_module_items([spec], [live_header()], index, prune=False).items
    assert change.action == "update"
    assert change.changed == ["title"]


def test_duplicates_pair_in_order(index):
    plan = plan_module_items([HW1, HW1], [live_hw1()], index, prune=False)
    assert actions(plan) == ["keep", "create"]
    assert plan.items[0].live is not None
    assert plan.items[0].live.id == 2


def test_page_matches_by_page_url_not_content_id(index):
    spec = ModuleItemSpec(type="Page", title="Syllabus")
    by_url = CanvasModuleItem(
        id=5, title="Syllabus", type="Page", content_id=999, page_url="syllabus"
    )
    plan = plan_module_items([spec], [by_url], index, prune=False)
    assert actions(plan) == ["keep"]

    by_id_only = CanvasModuleItem(
        id=6, title="Syllabus", type="Page", content_id=3, page_url="other"
    )
    plan = plan_module_items([spec], [by_id_only], index, prune=True)
    assert actions(plan) == ["create", "remove"]


def test_move_marks_only_out_of_place_item(index):
    a, b, c = (
        ModuleItemSpec(type="SubHeader", title="A"),
        ModuleItemSpec(type="ExternalUrl", title="B", url="https://b.org"),
        ModuleItemSpec(type="ExternalUrl", title="C", url="https://c.org"),
    )
    live = [
        CanvasModuleItem(
            id=2, title="B", type="ExternalUrl", external_url="https://b.org"
        ),
        CanvasModuleItem(
            id=3, title="C", type="ExternalUrl", external_url="https://c.org"
        ),
        CanvasModuleItem(id=1, title="A", type="SubHeader"),
    ]
    plan = plan_module_items([a, b, c], live, index, prune=False)
    assert actions(plan) == ["move", "keep", "keep"]
    assert plan.order_changed is True
    assert plan.has_changes is True


def test_updated_item_out_of_place_is_moved_update(index):
    a, b, c = (
        ModuleItemSpec(type="SubHeader", title="A (new)"),
        ModuleItemSpec(type="ExternalUrl", title="B", url="https://b.org"),
        ModuleItemSpec(type="ExternalUrl", title="C", url="https://c.org"),
    )
    live = [
        CanvasModuleItem(
            id=2, title="B", type="ExternalUrl", external_url="https://b.org"
        ),
        CanvasModuleItem(
            id=3, title="C", type="ExternalUrl", external_url="https://c.org"
        ),
        CanvasModuleItem(id=1, title="A", type="SubHeader"),
    ]
    first = plan_module_items([a, b, c], live, index, prune=False).items[0]
    assert first.action == "update"
    assert first.changed == ["title"]
    assert first.moved is True


def test_extras_go_last_and_remove_with_prune(index):
    extra = CanvasModuleItem(id=9, title="Tool", type="ExternalTool")
    live = [live_header(), extra, live_hw1()]

    plan = plan_module_items([HEADER, HW1], live, index, prune=False)
    assert actions(plan) == ["keep", "keep", "extra"]
    assert plan.items[2].live == extra
    assert plan.items[2].moved is True
    assert plan.order_changed is True

    plan = plan_module_items([HEADER, HW1], live, index, prune=True)
    assert actions(plan) == ["keep", "keep", "remove"]
    assert plan.items[2].live == extra
    assert plan.order_changed is False


def test_extra_in_place_is_not_a_change(index):
    extra = CanvasModuleItem(id=9, title="Tool", type="ExternalTool")
    plan = plan_module_items([HW1], [live_hw1(), extra], index, prune=False)
    assert actions(plan) == ["keep", "extra"]
    assert plan.items[1].moved is False
    assert plan.has_changes is False


def test_upload_new_file_then_create(index):
    source = Path("new.pdf")
    index.local_sizes[source] = 5
    spec = ModuleItemSpec(type="File", file="readings/new.pdf", source=source)
    [change] = plan_module_items([spec], [], index, prune=False).items
    assert change.action == "create"
    assert change.upload is not None
    assert change.upload.existing is None
    assert change.upload.path == "readings/new.pdf"
    assert change.upload.source == source


def test_upload_when_size_differs_then_keep(index):
    source = Path("w1.pdf")
    index.local_sizes[source] = 12
    spec = ModuleItemSpec(type="File", file="readings/w1.pdf", source=source)
    plan = plan_module_items([spec], [live_reading()], index, prune=False)
    [change] = plan.items
    assert change.action == "keep"
    assert change.upload is not None
    assert change.upload.existing is not None
    assert change.upload.existing.id == 70
    assert plan.has_changes is True


def test_no_upload_when_size_matches(index):
    source = Path("w1.pdf")
    index.local_sizes[source] = 10
    spec = ModuleItemSpec(type="File", file="readings/w1.pdf", source=source)
    plan = plan_module_items([spec], [live_reading()], index, prune=False)
    assert plan.items[0].upload is None
    assert plan.has_changes is False


def test_file_published_compares_lock(index):
    index.files[0] = CanvasFile(
        id=70, display_name="w1.pdf", folder_id=3, size=10, locked=True
    )
    spec = ModuleItemSpec(type="File", file="readings/w1.pdf", published=True)
    [change] = plan_module_items([spec], [live_reading()], index, prune=False).items
    assert change.action == "update"
    assert change.changed == ["published"]


def test_file_published_skipped_when_uploading(index):
    index.files[0] = CanvasFile(
        id=70, display_name="w1.pdf", folder_id=3, size=10, locked=True
    )
    source = Path("w1.pdf")
    index.local_sizes[source] = 12
    spec = ModuleItemSpec(
        type="File", file="readings/w1.pdf", source=source, published=True
    )
    [change] = plan_module_items([spec], [live_reading()], index, prune=False).items
    assert change.action == "keep"
    assert change.upload is not None
    assert change.upload.published is True


def test_lookup_errors_are_collected(index):
    declared = [
        ModuleItemSpec(type="Assignment", title="Nope"),
        HW1,
        ModuleItemSpec(type="File", file="readings/zzz.pdf"),
    ]
    with pytest.raises(RuntimeError) as excinfo:
        plan_module_items(declared, [], index, prune=False, module_name="Week 1")
    message = str(excinfo.value)
    assert "Module 'Week 1'" in message
    assert "item 1 (Assignment 'Nope')" in message
    assert "item 3 (File 'readings/zzz.pdf')" in message
    assert "item 2" not in message


def test_module_without_items_key_has_no_item_plan(index):
    module = CanvasModuleSpec(name="Week 1")
    assert plan_module_spec_items(module, [live_hw1()], index, prune=True) is None

    empty = CanvasModuleSpec(name="Week 1", items=[])
    plan = plan_module_spec_items(empty, [live_hw1()], index, prune=True)
    assert plan is not None
    assert actions(plan) == ["remove"]


def test_item_plan_rows(index):
    source = Path("new.pdf")
    index.local_sizes[source] = 5
    declared = [
        ModuleItemSpec(type="File", file="readings/new.pdf", source=source),
        ModuleItemSpec(type="SubHeader", title="Week 1 readings"),
        HW1,
        READING,
    ]
    live = [
        live_header(),
        live_hw1(),
        live_reading(),
        live_site(title="Old"),
    ]
    plan = plan_module_items(declared, live, index, prune=True)
    assert item_plan_rows("Week 1", plan) == [
        ("upload", "file", "Week 1: readings/new.pdf (new)"),
        ("create", "item", "Week 1: File readings/new.pdf"),
        ("update", "item", "Week 1: SubHeader 'Week 1 readings' (title)"),
        ("remove", "item", "Week 1: ExternalUrl 'Old'"),
        ("keep", "items", "Week 1: 2 kept"),
    ]


def test_item_plan_rows_details(index):
    source = Path("w1.pdf")
    index.local_sizes[source] = 12
    reading = ModuleItemSpec(type="File", file="readings/w1.pdf", source=source)
    a = ModuleItemSpec(type="SubHeader", title="A (new)")
    b = ModuleItemSpec(type="ExternalUrl", title="B", url="https://b.org")
    tool = CanvasModuleItem(id=9, title="Tool", type="ExternalTool")
    other = CanvasModuleItem(id=8, title="Chat", type="Discussion")
    live = [
        CanvasModuleItem(
            id=2, title="B", type="ExternalUrl", external_url="https://b.org"
        ),
        tool,
        live_reading(),
        CanvasModuleItem(id=1, title="A", type="SubHeader"),
        other,
    ]
    plan = plan_module_items([a, b, reading], live, index, prune=False)
    assert item_plan_rows("W", plan) == [
        ("update", "item", "W: SubHeader 'A (new)' (title, moved)"),
        ("upload", "file", "W: readings/w1.pdf (10 → 12 bytes)"),
        ("extra", "item", "W: ExternalTool 'Tool' (moved to end)"),
        ("extra", "item", "W: Discussion 'Chat' (not declared; --prune removes it)"),
        ("keep", "items", "W: 2 kept"),
    ]
