"""Tests for module item content lookup, planning and applying."""

from __future__ import annotations

__docformat__ = "google"

import re
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qsl

import httpx
import pytest

from cass.actions.config import CanvasModuleSpec, ModuleItemSpec
from cass.actions.module_items import (
    ContentIndex,
    ModuleItemApplyError,
    apply_module_item_plan,
    fetch_content_index,
    item_plan_rows,
    plan_module_items,
    plan_module_spec_items,
    resolve_content,
)
from cass.apis.canvas.client import CanvasClient
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


# --- applying -----------------------------------------------------------------

ITEMS = "/api/v1/courses/1/modules/5/items"
UPLOADED = CanvasFile(id=77, display_name="w1.pdf", folder_id=3, size=12)


def make_client(handler, log: list, monkeypatch) -> CanvasClient:
    """A real CanvasClient whose requests go to *handler* and into *log*.

    ``upload_file`` is replaced by a stub that logs its arguments and returns
    file 77 in the readings folder.
    """

    def logged(request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        log.append((request.method, request.url.path, form))
        return handler(request)

    client = CanvasClient(
        "https://canvas.example.com",
        token="test-token",
        course_id=1,
        transport=httpx.MockTransport(logged),
        time_zone="America/Los_Angeles",
    )

    def fake_upload(local_path, *, folder="", name=None, on_duplicate, locked):
        log.append(("UPLOAD", folder, name, on_duplicate, locked))
        return CanvasFile(id=77, display_name=name or "", folder_id=3, size=12)

    monkeypatch.setattr(client, "upload_file", fake_upload)
    return client


def apply_index() -> ContentIndex:
    """Course content for the apply tests: HW1 and an empty readings folder."""
    return ContentIndex(
        assignments=[CanvasAssignmentResponse(id=7, name="HW1")],
        quizzes=[],
        pages=[],
        folders=[
            CanvasFolder(id=2, name="course files", full_name="course files"),
            CanvasFolder(
                id=3,
                name="readings",
                full_name="course files/readings",
                parent_folder_id=2,
            ),
        ],
        files=[],
    )


SEQUENCE_LIVE = [
    CanvasModuleItem(id=31, title="Week 1", type="SubHeader"),
    CanvasModuleItem(id=32, title="HW1", type="Assignment", content_id=7),
    CanvasModuleItem(
        id=33, title="Old", type="ExternalUrl", external_url="https://old.org"
    ),
]


def sequence_declared(source: Path) -> list[ModuleItemSpec]:
    return [
        ModuleItemSpec(type="SubHeader", title="Week 1 readings"),
        ModuleItemSpec(type="File", file="readings/w1.pdf", source=source, indent=1),
        ModuleItemSpec(type="Assignment", title="HW1"),
        ModuleItemSpec(type="ExternalUrl", title="Syllabus", url="https://s.org"),
    ]


def item_json(item: CanvasModuleItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "type": item.type,
        "content_id": item.content_id,
        "published": item.published,
        "indent": item.indent,
        "external_url": item.external_url,
        "page_url": item.page_url,
    }


class ScriptedCanvas:
    """Answers item creates with ids 900, 901, … and the item list unchanged.

    ``fail_on_post=n`` fails the n-th item create; ``fail_put`` fails every
    PUT to that path. Failures are 500s.
    """

    def __init__(
        self,
        live: list[CanvasModuleItem],
        fail_on_post: int = 0,
        fail_put: str = "",
    ):
        self.live = live
        self.posts = 0
        self.fail_on_post = fail_on_post
        self.fail_put = fail_put

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        form = dict(parse_qsl(request.content.decode()))
        is_item_list = re.fullmatch(r"/api/v1/courses/1/modules/\d+/items", path)
        if request.method == "PUT" and path == self.fail_put:
            return httpx.Response(500, json={"errors": [{"message": "boom"}]})
        if request.method == "GET" and is_item_list:
            return httpx.Response(200, json=[item_json(i) for i in self.live])
        if request.method == "POST" and is_item_list:
            self.posts += 1
            if self.posts == self.fail_on_post:
                return httpx.Response(500, json={"errors": [{"message": "boom"}]})
            return httpx.Response(
                200,
                json={
                    "id": 899 + self.posts,
                    "title": form.get("module_item[title]", ""),
                    "type": form["module_item[type]"],
                    "published": False,
                },
            )
        if request.method == "PUT" and re.fullmatch(
            r"/api/v1/courses/1/modules/\d+/items/\d+", path
        ):
            item_id = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"id": item_id, "title": "x"})
        if request.method == "PUT" and path.startswith("/api/v1/files/"):
            return httpx.Response(
                200, json={"id": 77, "display_name": "w1.pdf", "locked": False}
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"errors": [{"message": "unexpected"}]})


def sequence_plan(tmp_path: Path, index: ContentIndex):
    source = tmp_path / "w1.pdf"
    source.write_bytes(b"twelve bytes")
    index.local_sizes[source] = 12
    return plan_module_items(
        sequence_declared(source), SEQUENCE_LIVE, index, prune=True
    )


def test_apply_request_sequence(tmp_path, monkeypatch):
    index = apply_index()
    plan = sequence_plan(tmp_path, index)
    log: list = []
    client = make_client(ScriptedCanvas(SEQUENCE_LIVE), log, monkeypatch)

    applied = apply_module_item_plan(client, 5, plan, index)

    assert log == [
        ("UPLOAD", "readings", "w1.pdf", "overwrite", True),
        (
            "POST",
            ITEMS,
            {
                "module_item[type]": "File",
                "module_item[content_id]": "77",
                "module_item[indent]": "1",
            },
        ),
        (
            "POST",
            ITEMS,
            {
                "module_item[type]": "ExternalUrl",
                "module_item[title]": "Syllabus",
                "module_item[external_url]": "https://s.org",
            },
        ),
        ("PUT", f"{ITEMS}/31", {"module_item[title]": "Week 1 readings"}),
        ("DELETE", f"{ITEMS}/33", {}),
        ("PUT", f"{ITEMS}/31", {"module_item[position]": "1"}),
        ("PUT", f"{ITEMS}/900", {"module_item[position]": "2"}),
        ("PUT", f"{ITEMS}/32", {"module_item[position]": "3"}),
        ("PUT", f"{ITEMS}/901", {"module_item[position]": "4"}),
    ]
    assert applied == [
        "upload readings/w1.pdf",
        "create File readings/w1.pdf",
        "create ExternalUrl 'Syllabus'",
        "update SubHeader 'Week 1 readings' (title)",
        "remove ExternalUrl 'Old'",
        "move SubHeader 'Week 1 readings' to 1",
        "move File readings/w1.pdf to 2",
        "move Assignment 'HW1' to 3",
        "move ExternalUrl 'Syllabus' to 4",
    ]
    assert index.uploaded["readings/w1.pdf"].id == 77


def test_apply_failure_stops_and_lists_completed_steps(tmp_path, monkeypatch):
    index = apply_index()
    plan = sequence_plan(tmp_path, index)
    log: list = []
    client = make_client(
        ScriptedCanvas(SEQUENCE_LIVE, fail_on_post=2), log, monkeypatch
    )

    with pytest.raises(ModuleItemApplyError) as raised:
        apply_module_item_plan(client, 5, plan, index)

    assert raised.value.applied == [
        "upload readings/w1.pdf",
        "create File readings/w1.pdf",
    ]
    assert "Stopped; applied before the failure:" in str(raised.value)
    assert "  create File readings/w1.pdf" in str(raised.value)
    assert raised.value.__cause__ is not None
    assert log[-1][:2] == ("POST", ITEMS)
    assert len(log) == 3


def test_apply_failure_before_any_change_says_so(monkeypatch):
    index = apply_index()
    live = [CanvasModuleItem(id=31, title="Week 1", type="SubHeader")]
    declared = [ModuleItemSpec(type="SubHeader", title="Week 2")]
    plan = plan_module_items(declared, live, index, prune=False)
    log: list = []
    client = make_client(lambda request: httpx.Response(500, json={}), log, monkeypatch)

    with pytest.raises(ModuleItemApplyError) as raised:
        apply_module_item_plan(client, 5, plan, index)

    assert raised.value.applied == []
    assert "Stopped before any change was applied." in str(raised.value)


def test_apply_all_keep_sends_nothing(monkeypatch):
    index = apply_index()
    live = [CanvasModuleItem(id=31, title="Week 1", type="SubHeader")]
    declared = [ModuleItemSpec(type="SubHeader", title="Week 1")]
    plan = plan_module_items(declared, live, index, prune=False)
    log: list = []
    client = make_client(ScriptedCanvas(live), log, monkeypatch)

    assert apply_module_item_plan(client, 5, plan, index) == []
    assert log == []


def test_apply_only_title_update_skips_positions(monkeypatch):
    index = apply_index()
    live = [CanvasModuleItem(id=31, title="Week 1", type="SubHeader")]
    declared = [ModuleItemSpec(type="SubHeader", title="Week 2")]
    plan = plan_module_items(declared, live, index, prune=False)
    log: list = []
    client = make_client(ScriptedCanvas(live), log, monkeypatch)

    apply_module_item_plan(client, 5, plan, index)

    assert log == [("PUT", f"{ITEMS}/31", {"module_item[title]": "Week 2"})]


def test_apply_uploads_each_path_once(tmp_path, monkeypatch):
    index = apply_index()
    source = tmp_path / "w1.pdf"
    source.write_bytes(b"twelve bytes")
    index.local_sizes[source] = 12
    declared = [ModuleItemSpec(type="File", file="readings/w1.pdf", source=source)]
    plan_5 = plan_module_items(declared, [], index, prune=False)
    plan_6 = plan_module_items(declared, [], index, prune=False)
    log: list = []
    client = make_client(ScriptedCanvas([]), log, monkeypatch)

    apply_module_item_plan(client, 5, plan_5, index)
    apply_module_item_plan(client, 6, plan_6, index)

    uploads = [entry for entry in log if entry[0] == "UPLOAD"]
    creates = [entry for entry in log if entry[0] == "POST"]
    assert len(uploads) == 1
    assert [c[2]["module_item[content_id]"] for c in creates] == ["77", "77"]
    assert [c[1] for c in creates] == [ITEMS, "/api/v1/courses/1/modules/6/items"]


def overwrite_plan(tmp_path: Path, *, locked: bool, published: bool | None):
    """Plan a File item whose Canvas copy (id 77) is 10 bytes, the source 12."""
    index = apply_index()
    index.files = [
        CanvasFile(id=77, display_name="w1.pdf", folder_id=3, size=10, locked=locked)
    ]
    source = tmp_path / "w1.pdf"
    source.write_bytes(b"twelve bytes")
    index.local_sizes[source] = 12
    spec = ModuleItemSpec(
        type="File", file="readings/w1.pdf", source=source, published=published
    )
    live = [CanvasModuleItem(id=40, title="w1.pdf", type="File", content_id=77)]
    return plan_module_items([spec], live, index, prune=False), index, live


def test_overwrite_keeps_existing_lock_when_published_omitted(tmp_path, monkeypatch):
    plan, index, live = overwrite_plan(tmp_path, locked=False, published=None)
    log: list = []
    client = make_client(ScriptedCanvas(live), log, monkeypatch)

    apply_module_item_plan(client, 5, plan, index)

    assert log == [("UPLOAD", "readings", "w1.pdf", "overwrite", False)]


def test_overwrite_with_published_true_unlocks_explicitly(tmp_path, monkeypatch):
    plan, index, live = overwrite_plan(tmp_path, locked=True, published=True)
    log: list = []
    client = make_client(ScriptedCanvas(live), log, monkeypatch)

    applied = apply_module_item_plan(client, 5, plan, index)

    assert log == [
        ("UPLOAD", "readings", "w1.pdf", "overwrite", False),
        ("PUT", "/api/v1/files/77", {"locked": "false"}),
    ]
    assert applied == ["upload readings/w1.pdf", "unlock readings/w1.pdf"]


def test_failed_unlock_still_lists_the_upload(tmp_path, monkeypatch):
    plan, index, live = overwrite_plan(tmp_path, locked=True, published=True)
    log: list = []
    canvas = ScriptedCanvas(live, fail_put="/api/v1/files/77")
    client = make_client(canvas, log, monkeypatch)

    with pytest.raises(ModuleItemApplyError) as raised:
        apply_module_item_plan(client, 5, plan, index)

    assert raised.value.applied == ["upload readings/w1.pdf"]
    assert index.uploaded["readings/w1.pdf"].id == 77


def test_two_request_update_lists_the_first_request(monkeypatch):
    index = apply_index()
    index.files = [
        CanvasFile(id=77, display_name="w1.pdf", folder_id=3, size=12, locked=True)
    ]
    spec = ModuleItemSpec(
        type="File", file="readings/w1.pdf", title="Reading 1", published=True
    )
    live = [CanvasModuleItem(id=40, title="w1.pdf", type="File", content_id=77)]
    plan = plan_module_items([spec], live, index, prune=False)
    assert plan.items[0].changed == ["title", "published"]
    log: list = []
    canvas = ScriptedCanvas(live, fail_put="/api/v1/files/77")
    client = make_client(canvas, log, monkeypatch)

    with pytest.raises(ModuleItemApplyError) as raised:
        apply_module_item_plan(client, 5, plan, index)

    assert log[0] == ("PUT", f"{ITEMS}/40", {"module_item[title]": "Reading 1"})
    assert log[1][:2] == ("PUT", "/api/v1/files/77")
    assert raised.value.applied == ["update File readings/w1.pdf (title)"]


def test_created_subheader_published_is_set_after_create(monkeypatch):
    index = apply_index()
    declared = [ModuleItemSpec(type="SubHeader", title="Week 1", published=True)]
    plan = plan_module_items(declared, [], index, prune=False)
    log: list = []
    client = make_client(ScriptedCanvas([]), log, monkeypatch)

    applied = apply_module_item_plan(client, 5, plan, index)

    assert log[0][:2] == ("POST", ITEMS)
    assert log[1] == ("PUT", f"{ITEMS}/900", {"module_item[published]": "true"})
    assert applied[:2] == [
        "create SubHeader 'Week 1'",
        "update SubHeader 'Week 1' (published)",
    ]


class FakeModuleCanvas:
    """A small stateful Canvas: one module's items plus the course content.

    What it assumes about Canvas (live test A10 is the authority):

    - Each item has a ``position`` value; ``GET …/items`` lists items sorted
      by it. Positions need not be dense: the constructor can start them with
      gaps, and DELETE leaves a gap (nothing is renumbered).
    - ``PUT position=p`` works like Canvas's ``insert_at``: every other item
      at ``p`` or above moves up by one, then the item takes ``p``.
    - A create is appended after the highest position, unpublished, and is
      titled after its content unless a title is sent.
    - Uploads (through the test's stub) add a file to the course files.
    """

    def __init__(
        self,
        live: list[CanvasModuleItem],
        index: ContentIndex,
        positions: list[int] | None = None,
    ):
        self.items = [item_json(item) for item in live]
        for item, position in zip(
            self.items, positions or range(1, len(live) + 1), strict=True
        ):
            item["position"] = position
        self.index = index
        self.next_id = 900

    def ordered(self) -> list[dict]:
        """Items in list order: sorted by position."""
        return sorted(self.items, key=lambda item: item["position"])

    def add_uploaded(self, file: CanvasFile) -> None:
        self.index.files = [f for f in self.index.files if f.id != file.id] + [file]

    def _content_title(self, item_type: str, content_id: int) -> str:
        if item_type == "Assignment":
            return next(a.name for a in self.index.assignments if a.id == content_id)
        if item_type == "File":
            files = self.index.files
            return next(f.display_name for f in files if f.id == content_id)
        return ""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        form = dict(parse_qsl(request.content.decode()))
        content = {
            "/api/v1/courses/1/assignments": [
                {"id": a.id, "name": a.name} for a in self.index.assignments
            ],
            "/api/v1/courses/1/quizzes": [],
            "/api/v1/courses/1/pages": [],
            "/api/v1/courses/1/folders": [
                {
                    "id": f.id,
                    "name": f.name,
                    "full_name": f.full_name,
                    "parent_folder_id": f.parent_folder_id,
                }
                for f in self.index.folders
            ],
            "/api/v1/courses/1/files": [
                {
                    "id": f.id,
                    "display_name": f.display_name,
                    "folder_id": f.folder_id,
                    "size": f.size,
                    "locked": f.locked,
                }
                for f in self.index.files
            ],
        }
        if request.method == "GET" and path in content:
            return httpx.Response(200, json=content[path])
        if request.method == "GET" and path == ITEMS:
            return httpx.Response(200, json=self.ordered())
        if request.method == "POST" and path == ITEMS:
            return httpx.Response(200, json=self._create(form))
        if path.startswith(ITEMS + "/"):
            item_id = int(path.rsplit("/", 1)[1])
            [item] = [i for i in self.items if i["id"] == item_id]
            if request.method == "DELETE":
                self.items.remove(item)
                return httpx.Response(200, json=item)
            return httpx.Response(200, json=self._update(item, form))
        return httpx.Response(404, json={"errors": [{"message": "unexpected"}]})

    def _create(self, form: dict[str, str]) -> dict:
        item_type = form["module_item[type]"]
        content_id = int(form.get("module_item[content_id]", 0))
        item = {
            "id": self.next_id,
            "title": form.get("module_item[title]")
            or self._content_title(item_type, content_id),
            "type": item_type,
            "content_id": content_id,
            "published": False,
            "indent": int(form.get("module_item[indent]", 0)),
            "external_url": form.get("module_item[external_url]", ""),
            "page_url": form.get("module_item[page_url]", ""),
            "position": max((i["position"] for i in self.items), default=0) + 1,
        }
        self.next_id += 1
        self.items.append(item)
        return item

    def _update(self, item: dict, form: dict[str, str]) -> dict:
        if "module_item[title]" in form:
            item["title"] = form["module_item[title]"]
        if "module_item[indent]" in form:
            item["indent"] = int(form["module_item[indent]"])
        if "module_item[published]" in form:
            item["published"] = form["module_item[published]"] == "true"
        if "module_item[position]" in form:
            position = int(form["module_item[position]"])
            for other in self.items:
                if other is not item and other["position"] >= position:
                    other["position"] += 1
            item["position"] = position
        return item


def test_replan_after_apply_is_all_keep(tmp_path, monkeypatch):
    source = tmp_path / "w1.pdf"
    source.write_bytes(b"twelve bytes")
    assert len(source.read_bytes()) == 12  # the upload stub reports size=12
    declared = sequence_declared(source)
    fake = FakeModuleCanvas(SEQUENCE_LIVE, apply_index())
    log: list = []
    client = make_client(fake, log, monkeypatch)
    stub_upload = client.upload_file

    def upload_into_fake(local_path, **kwargs) -> CanvasFile:
        file = stub_upload(local_path, **kwargs)
        fake.add_uploaded(file)
        return file

    monkeypatch.setattr(client, "upload_file", upload_into_fake)

    index = fetch_content_index(client, sources=[source])
    live = client.list_module_items(5)
    plan = plan_module_items(declared, live, index, prune=True)
    apply_module_item_plan(client, 5, plan, index)

    index = fetch_content_index(client, sources=[source])
    live = client.list_module_items(5)
    replan = plan_module_items(declared, live, index, prune=True)

    assert actions(replan) == ["keep"] * 4
    assert replan.has_changes is False
    assert [item["title"] for item in fake.ordered()] == [
        "Week 1 readings",
        "w1.pdf",
        "HW1",
        "Syllabus",
    ]


def test_reorder_with_gapped_positions_ends_in_declared_order(monkeypatch):
    index = apply_index()
    live = [
        CanvasModuleItem(
            id=30 + n, title=title, type="ExternalUrl", external_url=f"https://{title}"
        )
        for n, title in enumerate("ABC", start=1)
    ]
    fake = FakeModuleCanvas(live, index, positions=[1, 3, 7])
    log: list = []
    client = make_client(fake, log, monkeypatch)
    declared = [
        ModuleItemSpec(type="ExternalUrl", title=title, url=f"https://{title}")
        for title in "ACB"
    ]
    plan = plan_module_items(declared, client.list_module_items(5), index, prune=False)
    assert plan.order_changed is True
    log.clear()

    apply_module_item_plan(client, 5, plan, index)

    assert [item["title"] for item in fake.ordered()] == ["A", "C", "B"]
    assert [entry[1] for entry in log] == [f"{ITEMS}/{i}" for i in (31, 33, 32)]
