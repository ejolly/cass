"""Course file operations — uploads with duplicate policies, folder subtrees."""

from __future__ import annotations

__docformat__ = "google"

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

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
    on_duplicate: OnDuplicate = OnDuplicate.RENAME,
    unpublished: bool = False,
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
        unpublished: Lock the uploaded file so students cannot see it.

    Returns:
        The Canvas file and whether the upload was skipped.
    """
    target_name = name or os.path.basename(local_path)
    policy = on_duplicate.value
    if on_duplicate is OnDuplicate.SKIP:
        policy = "rename"
        found = client.find_folder(folder)
        if found is not None:
            local_size = os.path.getsize(local_path)
            for existing in client.list_files(found.id):
                if existing.display_name != target_name:
                    continue
                if existing.size == local_size:
                    return FileUpload(existing, skipped=True)
                policy = "overwrite"
                break

    uploaded = client.upload_file(
        local_path,
        folder=folder,
        name=name,
        on_duplicate=policy,  # ty: ignore[invalid-argument-type]
        locked=unpublished,
    )
    return FileUpload(uploaded, skipped=False)


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
