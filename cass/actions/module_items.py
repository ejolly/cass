"""Module item rules: command-line arguments, content lookup, planning and applying."""

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
        CanvasModuleItem,
        CanvasPage,
        CanvasQuiz,
    )
    from .config import CanvasModuleSpec

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


# --- planning -----------------------------------------------------------------

ITEM_FIELDS = ("title", "indent", "published")


@dataclass
class FileUploadPlan:
    """A local file to upload before its module item is created or kept."""

    source: Path
    path: str  # below the course files root, e.g. "readings/w1.pdf"
    existing: CanvasFile | None  # the file it overwrites; None for a new file
    published: bool | None  # the declared value
    local_size: int = 0  # bytes in *source*


@dataclass
class ItemChange:
    """What sync does to one module item."""

    action: str  # "create" | "update" | "move" | "keep" | "remove" | "extra"
    spec: ModuleItemSpec | None  # None for remove / extra
    live: CanvasModuleItem | None  # None for create
    ref: ContentRef | None  # None for remove / extra
    changed: list[str] = field(default_factory=list)  # in ITEM_FIELDS order
    moved: bool = False  # an update or extra that also changes place
    upload: FileUploadPlan | None = None


@dataclass
class ModuleItemPlan:
    """Planned item changes for one module.

    ``items`` lists declared items in file order, then extras in their
    current order, then removes.
    """

    items: list[ItemChange]
    order_changed: bool

    @property
    def has_changes(self) -> bool:
        """True when applying the plan would send any request."""
        return self.order_changed or any(
            change.upload is not None or change.action not in ("keep", "extra")
            for change in self.items
        )


def _spec_reference(spec: ModuleItemSpec) -> str:
    """The key that names a declared item in error messages."""
    if spec.file:
        return spec.file
    if spec.url:
        return spec.url
    return spec.title


def _resolve_all(
    declared: list[ModuleItemSpec], index: ContentIndex, module_name: str
) -> list[ContentRef]:
    """Resolve every declared item, reporting all lookup problems at once.

    Raises:
        RuntimeError: Listing every item that could not be resolved.
    """
    refs: list[ContentRef] = []
    problems: list[str] = []
    for number, spec in enumerate(declared, start=1):
        try:
            refs.append(resolve_content(spec, index))
        except ValueError as exc:
            item_type = canonical_item_type(spec.type) or spec.type
            problems.append(
                f"item {number} ({item_type} {_spec_reference(spec)!r}): {exc}"
            )
    if problems:
        raise RuntimeError(
            f"Module {module_name!r}: cannot plan items:\n  " + "\n  ".join(problems)
        )
    return refs


def _declared_identity(ref: ContentRef) -> tuple[str, object] | None:
    """What a declared item matches live items by; None when it cannot match."""
    if ref.item_type == "Page":
        return ("Page", ref.page_url)
    if ref.item_type == "ExternalUrl":
        return ("ExternalUrl", ref.external_url)
    if ref.item_type == "SubHeader":
        return ("SubHeader", None)  # SubHeaders pair by their order
    if ref.content_id is None:
        return None  # a File that will be uploaded new
    return (ref.item_type, ref.content_id)


def _live_identity(item: CanvasModuleItem) -> tuple[str, object]:
    """What a live item matches declared items by (see `_declared_identity`)."""
    if item.type == "Page":
        return ("Page", item.page_url)
    if item.type == "ExternalUrl":
        return ("ExternalUrl", item.external_url)
    if item.type == "SubHeader":
        return ("SubHeader", None)
    return (item.type, item.content_id)


def _pair_items(
    refs: list[ContentRef], live_items: list[CanvasModuleItem]
) -> list[CanvasModuleItem | None]:
    """Find the live item each declared item matches, or None.

    Declared and live items with the same identity pair up in their own
    order: the first declared with the first live, and so on.
    """
    unpaired_live: dict[tuple[str, object], list[CanvasModuleItem]] = {}
    for item in live_items:
        unpaired_live.setdefault(_live_identity(item), []).append(item)

    pairs: list[CanvasModuleItem | None] = []
    for ref in refs:
        identity = _declared_identity(ref)
        candidates = unpaired_live.get(identity, []) if identity else []
        pairs.append(candidates.pop(0) if candidates else None)
    return pairs


def _changed_fields(
    spec: ModuleItemSpec,
    ref: ContentRef,
    live: CanvasModuleItem,
    upload: FileUploadPlan | None,
) -> list[str]:
    """The ITEM_FIELDS that differ between a declared item and its live match."""
    changed: list[str] = []
    if ref.title and ref.title != live.title:
        changed.append("title")
    if spec.indent != live.indent:
        changed.append("indent")
    if spec.published is not None:
        if ref.item_type == "File":
            # A File's "published" is its lock state; an upload sets it anyway.
            file_is_published = ref.file is not None and not ref.file.locked
            if upload is None and spec.published != file_is_published:
                changed.append("published")
        elif spec.published != live.published:
            changed.append("published")
    return changed


def _upload_for(
    spec: ModuleItemSpec, ref: ContentRef, index: ContentIndex
) -> FileUploadPlan | None:
    """Plan an upload when a File's source is new or differs in size."""
    if ref.item_type != "File" or spec.source is None:
        return None
    local_size = index.local_sizes.get(spec.source, 0)
    if ref.file is not None and ref.file.size == local_size:
        return None
    return FileUploadPlan(
        source=spec.source,
        path=ref.file_path,
        existing=ref.file,
        published=spec.published,
        local_size=local_size,
    )


def _out_of_place(
    current: list[int], target: list[int], declared_ids: set[int]
) -> set[int]:
    """Live item ids that must move so *current* becomes *target*.

    Both lists hold the same ids. The items that can stay where they are form
    a longest common subsequence (LCS) of the two lists: the longest run of
    ids that appear in the same relative order in both. Every other item must
    move. When several subsequences are equally long, the one with the most
    declared items wins, so extras (which belong at the end anyway) are the
    ones reported as moved.

    ``best[i][j]`` scores the best subsequence of ``current[i:]`` and
    ``target[j:]`` as (length, declared items in it); tuples compare
    element by element, so length decides first.
    """
    rows, cols = len(current), len(target)
    best = [[(0, 0)] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            if current[i] == target[j]:
                length, declared = best[i + 1][j + 1]
                best[i][j] = (length + 1, declared + (current[i] in declared_ids))
            else:
                best[i][j] = max(best[i + 1][j], best[i][j + 1])

    in_place: set[int] = set()
    i = j = 0
    while i < rows and j < cols:
        if current[i] == target[j]:
            in_place.add(current[i])
            i += 1
            j += 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return set(current) - in_place


def plan_module_items(
    declared: list[ModuleItemSpec],
    live_items: list[CanvasModuleItem],
    index: ContentIndex,
    *,
    prune: bool,
    module_name: str = "",
) -> ModuleItemPlan:
    """Compare declared module items with the live ones. No I/O.

    Args:
        declared: Items in the order the config file lists them.
        live_items: Items in the order Canvas lists them (their ``position``
            field is not trusted).
        index: Course content and local source sizes.
        prune: Remove undeclared items instead of keeping them as extras.
        module_name: Names the module in error messages.

    Raises:
        RuntimeError: Listing every declared item whose content is missing or
            ambiguous.
    """
    refs = _resolve_all(declared, index, module_name)
    pairs = _pair_items(refs, live_items)

    changes: list[ItemChange] = []
    for spec, ref, live in zip(declared, refs, pairs, strict=True):
        upload = _upload_for(spec, ref, index)
        if live is None:
            changes.append(ItemChange("create", spec, None, ref, upload=upload))
            continue
        changed = _changed_fields(spec, ref, live, upload)
        action = "update" if changed else "keep"
        changes.append(ItemChange(action, spec, live, ref, changed, upload=upload))

    paired_ids = {live.id for live in pairs if live is not None}
    unpaired = [item for item in live_items if item.id not in paired_ids]
    leftover_action = "remove" if prune else "extra"
    leftovers = [ItemChange(leftover_action, None, item, None) for item in unpaired]

    extras = [c for c in leftovers if c.action == "extra"]
    removes = [c for c in leftovers if c.action == "remove"]
    removed_ids = {c.live.id for c in removes if c.live is not None}
    current = [item.id for item in live_items if item.id not in removed_ids]
    target = [live.id for live in pairs if live is not None] + [
        c.live.id for c in extras if c.live is not None
    ]
    must_move = _out_of_place(current, target, paired_ids)

    for change in changes + extras:
        if change.live is None or change.live.id not in must_move:
            continue
        if change.action == "keep":
            change.action = "move"
        else:
            change.moved = True

    return ModuleItemPlan(
        items=changes + extras + removes, order_changed=bool(must_move)
    )


def plan_module_spec_items(
    module: CanvasModuleSpec,
    live_items: list[CanvasModuleItem],
    index: ContentIndex,
    *,
    prune: bool,
) -> ModuleItemPlan | None:
    """Plan *module*'s items, or return None when it has no ``items`` key.

    A module without ``items`` is never item-reconciled.
    """
    if module.items is None:
        return None
    return plan_module_items(
        module.items, live_items, index, prune=prune, module_name=module.name
    )


def item_label(change: ItemChange) -> str:
    """Name an item for a plan row.

    Declared items use the desired title (a File its path); undeclared live
    items use their current type and title.
    """
    if change.ref is not None:
        if change.ref.item_type == "File":
            return f"File {change.ref.file_path}"
        return f"{change.ref.item_type} {change.ref.title!r}"
    if change.live is not None:
        return f"{change.live.type} {change.live.title!r}"
    return "item"


def _row_detail(change: ItemChange) -> str:
    if change.action == "update":
        moved = ", moved" if change.moved else ""
        return f" ({', '.join(change.changed)}{moved})"
    if change.action == "extra":
        if change.moved:
            return " (moved to end)"
        return " (not declared; --prune removes it)"
    return ""


def item_plan_rows(
    module_name: str, plan: ModuleItemPlan
) -> list[tuple[str, str, str]]:
    """Table rows ``(action, kind, description)`` for a module's item plan.

    One row per upload and per non-keep item, then a count of kept items.
    """
    rows: list[tuple[str, str, str]] = []
    kept = 0
    for change in plan.items:
        upload = change.upload
        if upload is not None:
            if upload.existing is None:
                sizes = "new"
            else:
                sizes = f"{upload.existing.size} → {upload.local_size} bytes"
            rows.append(("upload", "file", f"{module_name}: {upload.path} ({sizes})"))
        if change.action == "keep":
            kept += 1
            continue
        label = f"{module_name}: {item_label(change)}{_row_detail(change)}"
        rows.append((change.action, "item", label))
    if kept:
        rows.append(("keep", "items", f"{module_name}: {kept} kept"))
    return rows


# --- applying -----------------------------------------------------------------


class ModuleItemLookupError(RuntimeError):
    """Declared module items could not be planned; no item request was sent."""


class ModuleItemApplyError(RuntimeError):
    """A request failed while applying a module item plan.

    Attributes:
        applied: Descriptions of the steps completed before the failure.
    """

    def __init__(self, cause: BaseException, applied: list[str]):
        self.applied = list(applied)
        if applied:
            done = "\n".join(f"  {step}" for step in applied)
            message = f"{cause}\nStopped; applied before the failure:\n{done}"
        else:
            message = f"{cause}\nStopped before any change was applied."
        super().__init__(message)


def apply_module_item_plan(
    client: CanvasClient, module_id: int, plan: ModuleItemPlan, index: ContentIndex
) -> list[str]:
    """Apply *plan* to module *module_id*: uploads, creates, updates, removes,
    then positions, in that order.

    Sends nothing at all when the plan has no changes. Uploaded files are
    added to ``index.uploaded``, so a later plan reuses them.

    Returns:
        Descriptions of the applied steps, in order.

    Raises:
        ModuleItemApplyError: When a request fails; it lists the steps
            completed before the failure. Nothing is rolled back.
    """
    applied: list[str] = []
    if not plan.has_changes:
        return applied
    try:
        _upload_files(client, plan, index, applied)
        created = _create_items(client, module_id, plan, index, applied)
        _update_items(client, module_id, plan, created, applied)
        removed_ids = _remove_items(client, module_id, plan, applied)
        needs_positions = plan.order_changed or bool(created) or bool(removed_ids)
        if needs_positions:
            _set_positions(client, module_id, plan, created, applied)
    except Exception as exc:
        raise ModuleItemApplyError(exc, applied) from exc
    return applied


def _upload_lock(upload: FileUploadPlan) -> bool:
    """Whether the uploaded file ends up locked (see the plan's Decisions)."""
    if upload.existing is None:
        return upload.published is not True
    if upload.published is None:
        return upload.existing.locked
    return not upload.published


def _upload_files(
    client: CanvasClient, plan: ModuleItemPlan, index: ContentIndex, applied: list[str]
) -> None:
    """Step 1: upload each planned file once per run."""
    for change in plan.items:
        upload = change.upload
        if upload is None or upload.path.lower() in index.uploaded:
            continue
        folder, _, name = upload.path.rpartition("/")
        file = client.upload_file(
            str(upload.source),
            folder=folder,
            name=name,
            on_duplicate="overwrite",
            locked=_upload_lock(upload),
        )
        index.uploaded[upload.path.lower()] = file
        applied.append(f"upload {upload.path}")
        if upload.published is True and upload.existing is not None:
            # upload_file(locked=False) sends no unlock, so unlock explicitly.
            file = client.update_file(file.id, locked=False)
            index.uploaded[upload.path.lower()] = file
            applied.append(f"unlock {upload.path}")


def _create_items(
    client: CanvasClient,
    module_id: int,
    plan: ModuleItemPlan,
    index: ContentIndex,
    applied: list[str],
) -> list[tuple[ItemChange, CanvasModuleItem]]:
    """Step 2: create the new items.

    Returns:
        Each create change with the item Canvas created for it.
    """
    created: list[tuple[ItemChange, CanvasModuleItem]] = []
    for change in plan.items:
        if change.action != "create" or change.spec is None or change.ref is None:
            continue
        ref, spec = change.ref, change.spec
        content_id = ref.content_id
        if content_id is None and ref.item_type == "File":
            content_id = index.uploaded[ref.file_path.lower()].id
        titled = ref.item_type in ("ExternalUrl", "SubHeader", "File")
        new = client.create_module_item(
            module_id,
            item_type=ref.item_type,
            content_id=content_id,
            title=(ref.title or None) if titled else None,
            indent=spec.indent or None,
            page_url=ref.page_url or None,
            external_url=ref.external_url or None,
        )
        created.append((change, new))
        applied.append(f"create {item_label(change)}")
    return created


def _update_items(
    client: CanvasClient,
    module_id: int,
    plan: ModuleItemPlan,
    created: list[tuple[ItemChange, CanvasModuleItem]],
    applied: list[str],
) -> None:
    """Step 3: update changed fields, then publish state of created items."""
    for change in plan.items:
        if change.action != "update":
            continue
        _update_item(client, module_id, change, applied)

    for change, new in created:
        if change.spec is None or change.ref is None:
            continue
        published = change.spec.published
        if change.ref.item_type == "File" or published is None:
            continue
        if published != new.published:
            client.update_module_item(
                module_id, new.id, published=published, current=new
            )
            applied.append(f"update {item_label(change)} (published)")


def _update_item(
    client: CanvasClient, module_id: int, change: ItemChange, applied: list[str]
) -> None:
    """Send one update change: item fields in one PUT, a File's lock separately.

    Each request records its own step, so a failure lists exactly what was sent.
    """
    spec, ref, live = change.spec, change.ref, change.live
    if spec is None or ref is None or live is None:
        return
    label = item_label(change)
    is_file = ref.item_type == "File"
    item_fields = [
        name for name in change.changed if not (name == "published" and is_file)
    ]
    if item_fields:
        client.update_module_item(
            module_id,
            live.id,
            title=ref.title if "title" in item_fields else None,
            indent=spec.indent if "indent" in item_fields else None,
            published=spec.published if "published" in item_fields else None,
            current=live,
        )
        applied.append(f"update {label} ({', '.join(item_fields)})")
    if is_file and "published" in change.changed and ref.file is not None:
        client.update_file(ref.file.id, locked=not spec.published)
        applied.append(f"update {label} (published)")


def _remove_items(
    client: CanvasClient, module_id: int, plan: ModuleItemPlan, applied: list[str]
) -> set[int]:
    """Step 4: delete the removed items.

    Returns:
        The ids of the deleted items.
    """
    removed_ids: set[int] = set()
    for change in plan.items:
        if change.action != "remove" or change.live is None:
            continue
        client.delete_module_item(module_id, change.live.id)
        removed_ids.add(change.live.id)
        applied.append(f"remove {item_label(change)}")
    return removed_ids


def _set_positions(
    client: CanvasClient,
    module_id: int,
    plan: ModuleItemPlan,
    created: list[tuple[ItemChange, CanvasModuleItem]],
    applied: list[str],
) -> None:
    """Step 5: put every item at its target position.

    Target order is the declared items, then extras. Every slot gets a
    ``position`` PUT, in order, even when the item already looks in place:
    Canvas positions can have gaps (after deletions), and setting slots
    1..n in turn gives the target order whatever the starting positions.
    """
    # ItemChange is a dataclass and cannot be a dict key, so key by identity.
    new_items = {id(change): new for change, new in created}
    for slot, change in enumerate(
        [c for c in plan.items if c.action != "remove"], start=1
    ):
        item = new_items.get(id(change)) or change.live
        if item is None:
            raise RuntimeError(f"no module item for {item_label(change)}")
        client.update_module_item(module_id, item.id, position=slot)
        applied.append(f"move {item_label(change)} to {slot}")


# --- sync ---------------------------------------------------------------------

# Item actions the sync summary line counts beyond create / update / skip.
SYNC_SUMMARY_ACTIONS = ("upload", "move", "remove", "extra")


@dataclass
class ModuleSyncPlan:
    """One module's item plan within a sync."""

    name: str
    module_id: int  # a dry-run placeholder (< 0) for a module this sync creates
    plan: ModuleItemPlan


@dataclass
class SyncItemsPlan:
    """Item plans for every module that declares ``items``, in config order."""

    index: ContentIndex
    modules: list[ModuleSyncPlan]
    rows: list[tuple[str, str, str]]  # from item_plan_rows, module by module
    counts: dict[str, int]  # rows per action in SYNC_SUMMARY_ACTIONS

    @property
    def has_changes(self) -> bool:
        """True when applying would send any request."""
        return any(module.plan.has_changes for module in self.modules)


def plan_sync_items(
    client: CanvasClient,
    modules: list[CanvasModuleSpec],
    module_ids: dict[str, int],
    *,
    created_assignments: list[CanvasAssignmentResponse],
    created_quizzes: list[CanvasQuiz],
    prune: bool,
) -> SyncItemsPlan | None:
    """Plan the items of every module that declares them, before any write.

    Fetches the content index once, makes the assignments and quizzes this
    sync created resolvable by title, then plans each module in config order.

    Args:
        modules: Module specs from cass.toml.
        module_ids: Canvas id for each module name (placeholders in a dry run).
        created_assignments: Assignments this sync created.
        created_quizzes: Quizzes this sync created.
        prune: Remove undeclared items instead of keeping them as extras.

    Returns:
        The plan, or None (with no requests sent) when no module declares
        ``items``.

    Raises:
        ModuleItemLookupError: Listing the lookup problems of every module
            at once.
    """
    declared = [module for module in modules if module.items is not None]
    if not declared:
        return None

    # `or []` only narrows the type: `declared` holds modules with items.
    sources = [
        item.source
        for module in declared
        for item in module.items or []
        if item.source is not None
    ]
    index = fetch_content_index(client, sources=sources)
    for assignment in created_assignments:
        index.add_created("Assignment", assignment.id, assignment.name)
    for quiz in created_quizzes:
        index.add_created("Quiz", quiz.id, quiz.title)

    planned: list[ModuleSyncPlan] = []
    problems: list[str] = []
    for module in declared:
        module_id = module_ids[module.name]
        try:
            plan = plan_module_items(
                module.items or [],  # narrows the type; never None here
                client.list_module_items(module_id),
                index,
                prune=prune,
                module_name=module.name,
            )
        except RuntimeError as exc:
            problems.append(str(exc))
            continue
        planned.append(ModuleSyncPlan(module.name, module_id, plan))
    if problems:
        raise ModuleItemLookupError("\n".join(problems))

    rows = [
        row for module in planned for row in item_plan_rows(module.name, module.plan)
    ]
    counts = {
        action: sum(1 for row in rows if row[0] == action)
        for action in SYNC_SUMMARY_ACTIONS
    }
    return SyncItemsPlan(index=index, modules=planned, rows=rows, counts=counts)


def apply_sync_items(client: CanvasClient, plan: SyncItemsPlan) -> None:
    """Apply each module's item plan in config order; stop at the first failure.

    Raises:
        ModuleItemApplyError: When a request fails.
    """
    for module in plan.modules:
        apply_module_item_plan(client, module.module_id, module.plan, plan.index)
