"""Course file operations — uploads with duplicate policies, folder subtrees."""

from __future__ import annotations

__docformat__ = "google"

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..apis.canvas.client import CanvasClient
    from ..apis.canvas.schema import CanvasFile, CanvasFolder


class OnDuplicate(StrEnum):
    """What to do when an upload's name already exists in the folder."""

    RENAME = "rename"
    OVERWRITE = "overwrite"
    SKIP = "skip"


class OnConflict(StrEnum):
    """What to do when a moved or renamed file collides with an existing name."""

    RENAME = "rename"
    OVERWRITE = "overwrite"


def lock_for_upload(existing: CanvasFile | None, published: bool | None) -> bool:
    """Return whether an uploaded file should end up locked (hidden from students).

    A new file is locked unless ``published`` is true. An upload over an
    existing file keeps that file's lock when ``published`` is None, so an
    overwrite never makes a hidden file visible by accident.
    """
    if published is not None:
        return not published
    if existing is None:
        return True
    return bool(existing.locked)


@dataclass(frozen=True)
class FileUpload:
    """Result of an upload: the Canvas file, and whether the upload was skipped."""

    file: CanvasFile
    skipped: bool


def upload_course_file(
    client: CanvasClient,
    local_path: str,
    *,
    folder: str = "",
    name: str | None = None,
    on_duplicate: OnDuplicate = OnDuplicate.OVERWRITE,
    published: bool | None = None,
) -> FileUpload:
    """Upload a local file, applying the duplicate policy.

    ``SKIP`` leaves an existing file untouched only when it has the same name
    and size; the same name with a different size is overwritten, and a
    missing folder means the file is uploaded.

    Args:
        client: Canvas client.
        local_path: Path to the local file.
        folder: Destination folder path; ``""`` is the course files root.
        name: Name in Canvas; defaults to the local file name.
        on_duplicate: Duplicate policy.
        published: True unlocks the file for students and False locks it.
            None locks a new file and keeps an overwritten file's lock.

    Returns:
        The Canvas file and whether the upload was skipped.
    """
    target_name = name or os.path.basename(local_path)
    policy: Literal["rename", "overwrite"] = (
        "rename" if on_duplicate is OnDuplicate.RENAME else "overwrite"
    )
    existing = None
    if on_duplicate is not OnDuplicate.RENAME:
        existing = find_existing_file(client, folder, target_name)
    if on_duplicate is OnDuplicate.SKIP:
        if existing is None:
            policy = "rename"
        elif existing.size == os.path.getsize(local_path):
            return FileUpload(existing, skipped=True)
    if policy == "rename":
        existing = None

    locked = lock_for_upload(existing, published)
    uploaded = client.upload_file(
        local_path,
        folder=folder,
        name=name,
        on_duplicate=policy,
        locked=locked,
    )
    if not locked and existing is not None and existing.locked:
        # upload_file(locked=False) sends no unlock; an overwrite of a locked
        # file needs an explicit one.
        uploaded = client.update_file(uploaded.id, locked=False)
    return FileUpload(uploaded, skipped=False)


def find_existing_file(
    client: CanvasClient, folder: str, name: str
) -> CanvasFile | None:
    """Return the file named exactly ``name`` in ``folder``, if there is one."""
    found = client.find_folder(folder)
    if found is None:
        return None
    for existing in client.list_files(found.id):
        if existing.display_name == name:
            return existing
    return None


def folder_subtree(
    folders: list[CanvasFolder], files: list[CanvasFile], folder: CanvasFolder
) -> tuple[list[CanvasFolder], list[CanvasFile]]:
    """Select a folder, its descendants, and the files inside them."""
    prefix = folder.full_name + "/"
    selected = [
        f
        for f in folders
        if f.full_name == folder.full_name or f.full_name.startswith(prefix)
    ]
    ids = {f.id for f in selected}
    return selected, [f for f in files if f.folder_id in ids]
