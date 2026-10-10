"""Files and folders."""

from __future__ import annotations

__docformat__ = "google"

from typing import Literal

import msgspec

from ..errors import CanvasNotFoundError
from ..schema import CanvasFile, CanvasFolder
from .base import BaseClient


def normalize_folder_path(path: str) -> str:
    """Strip whitespace and slashes and drop empty segments.

    Example: ``"/a//b/"`` becomes ``"a/b"``; ``""`` stays ``""``.
    """
    segments = [segment for segment in path.strip().split("/") if segment]
    return "/".join(segments)


def folder_paths(folders: list[CanvasFolder]) -> dict[int, str]:
    """Map each folder ID to its path relative to the course files root.

    The root folder (the one without a parent) maps to ``""``. Canvas names the
    root ``course files``; that prefix is removed from every path.
    """
    root = next((f for f in folders if f.parent_folder_id is None), None)
    prefix = f"{root.full_name}/" if root else ""
    paths: dict[int, str] = {}
    for folder in folders:
        if root and folder.id == root.id:
            paths[folder.id] = ""
        else:
            paths[folder.id] = folder.full_name.removeprefix(prefix)
    return paths


def _reject_root_prefix(segments: list[str], folders: list[CanvasFolder], path: str):
    """Raise if *path* starts with the root folder's name (e.g. ``course files``)."""
    root = next((f for f in folders if f.parent_folder_id is None), None)
    if root and segments and segments[0].lower() == root.name.lower():
        raise RuntimeError(
            "Folder paths are relative to the course files root; "
            f"drop the '{root.name}/' prefix: {path}"
        )


def _find_folder_by_path(folders: list[CanvasFolder], path: str) -> CanvasFolder | None:
    """Case-insensitive path lookup in an already-fetched folder list."""
    wanted = normalize_folder_path(path)
    _reject_root_prefix(wanted.split("/"), folders, path)
    paths = folder_paths(folders)
    for folder in folders:
        if paths[folder.id].lower() == wanted.lower():
            return folder
    return None


class FilesMixin(BaseClient):
    """Files and folders."""

    def list_files(self, folder_id: int | None = None) -> list[CanvasFile]:
        """List files in the course or a specific folder.

        Args:
            folder_id: Optional folder ID to scope the listing.

        Returns:
            File metadata sorted by name.
        """
        if folder_id:
            data = self._get_paginated(f"/folders/{folder_id}/files")
        else:
            data = self._get_paginated(self._course("/files"))
        return msgspec.convert(data, list[CanvasFile], strict=False)

    def resolve_file(self, id_or_name: str) -> CanvasFile:
        """Resolve a file by ID or case-insensitive display name.

        Raises:
            RuntimeError: If no file matches, or the name is ambiguous.
        """
        return self._resolve(
            self.list_files(), id_or_name, "File", lambda f: f.display_name
        )

    def list_folders(self) -> list[CanvasFolder]:
        """List all folders in the course.

        Returns:
            Folders with hierarchy info.
        """
        data = self._get_paginated(self._course("/folders"))
        return msgspec.convert(data, list[CanvasFolder], strict=False)

    def find_folder(self, path: str) -> CanvasFolder | None:
        """Find a folder by path relative to the course files root.

        Matching is case-insensitive.

        Returns:
            The folder, or ``None`` if no folder has that path.

        Raises:
            RuntimeError: If the path starts with the root folder's name.
        """
        return _find_folder_by_path(self.list_folders(), path)

    def resolve_folder(self, id_or_path: str) -> CanvasFolder:
        """Resolve a folder by exact ID, else by path.

        Raises:
            CanvasNotFoundError: If nothing matches.
        """
        folders = self.list_folders()
        for folder in folders:
            if str(folder.id) == id_or_path:
                return folder
        folder = _find_folder_by_path(folders, id_or_path)
        if folder is None:
            raise CanvasNotFoundError(f"Folder not found: {id_or_path}")
        return folder

    def create_folder(self, path: str, *, parents: bool = True) -> CanvasFolder:
        """Create a folder by path, creating missing parents by default.

        Existing folders are returned unchanged. ``""`` returns the root folder.

        Args:
            path: Folder path relative to the course files root.
            parents: Create missing intermediate folders. When ``False``, a
                missing intermediate folder raises.

        Raises:
            RuntimeError: If the path starts with the root folder's name, or
                ``parents`` is ``False`` and an intermediate folder is missing.
        """
        folders = self.list_folders()
        segments = [s for s in normalize_folder_path(path).split("/") if s]
        _reject_root_prefix(segments, folders, path)

        paths = folder_paths(folders)
        paths_to_folders = {paths[folder.id].lower(): folder for folder in folders}
        current = paths_to_folders[""]
        walked = ""
        for index, segment in enumerate(segments):
            walked = f"{walked}/{segment}" if walked else segment
            existing = paths_to_folders.get(walked.lower())
            if existing:
                current = existing
                continue
            if not parents and index < len(segments) - 1:
                raise RuntimeError(f"Parent folder not found: {walked}")
            response = self.request(
                "POST", f"/folders/{current.id}/folders", data={"name": segment}
            )
            current = msgspec.convert(response.json(), CanvasFolder, strict=False)
        return current

    def delete_folder(self, folder_id: int, *, force: bool = False) -> None:
        """Delete a folder; ``force`` also deletes a non-empty folder."""
        self.request(
            "DELETE",
            f"/folders/{folder_id}",
            params={"force": "true"} if force else None,
        )

    def update_file(
        self,
        file_id: int,
        *,
        name: str | None = None,
        folder_id: int | None = None,
        locked: bool | None = None,
        on_duplicate: Literal["rename", "overwrite"] | None = None,
    ) -> CanvasFile:
        """Rename, move or lock a file; only the given fields are sent.

        Args:
            file_id: Canvas file ID.
            name: New display name.
            folder_id: ID of the folder to move the file into.
            locked: Lock (``True``) or unlock (``False``) the file.
            on_duplicate: What to do if the destination already has a file with
                the same name.

        Raises:
            RuntimeError: If no field is given.
        """
        fields: dict[str, object] = {
            "name": name,
            "parent_folder_id": folder_id,
            "locked": locked,
            "on_duplicate": on_duplicate,
        }
        data = {key: value for key, value in fields.items() if value is not None}
        if not data:
            raise RuntimeError("update_file needs at least one field")
        response = self.request("PUT", f"/files/{file_id}", data=data)
        return msgspec.convert(response.json(), CanvasFile, strict=False)

    def upload_file(
        self,
        local_path: str,
        *,
        folder: str = "",
        name: str | None = None,
        on_duplicate: Literal["rename", "overwrite"] = "overwrite",
        locked: bool = False,
    ) -> CanvasFile:
        """Upload a file to the course.

        Uses Canvas's 3-step file upload flow:
        1. Notify Canvas to get an upload URL
        2. POST the file to the upload URL
        3. Confirm the upload

        Args:
            local_path: Path to the local file.
            folder: Destination folder path relative to the course files root
                (e.g. ``slides``); created if missing. ``""`` is the root.
            name: Name in Canvas; defaults to the local file name.
            on_duplicate: ``"overwrite"`` (default) replaces the file of that
                exact name: Canvas stores the upload as a new file (new id),
                deletes the old one and re-points its module items and
                links to the new one. ``"rename"`` keeps both files.
            locked: Lock the file after uploading.

        Returns:
            The uploaded file metadata.
        """
        import os as _os

        filename = name or _os.path.basename(local_path)
        size = _os.path.getsize(local_path)

        # Step 1: notify Canvas
        params: dict[str, object] = {
            "name": filename,
            "size": size,
            "on_duplicate": on_duplicate,
        }
        if folder:
            params["parent_folder_id"] = self.create_folder(folder).id
        else:
            params["parent_folder_path"] = "/"
        resp = self._client.post(self._course("/files"), data=params)
        upload_info = resp.json()

        # Step 2: POST to upload URL
        upload_url = upload_info["upload_url"]
        upload_params = upload_info.get("upload_params", {})
        with open(local_path, "rb") as f:
            resp2 = self._post_upload(
                upload_url, data=upload_params, filename=filename, file=f
            )

        # Step 3: Canvas may return the file directly or a redirect
        if resp2.status_code != 201 and resp2.headers.get("Location"):
            resp2 = self._client.get(resp2.headers["Location"])
        uploaded = msgspec.convert(resp2.json(), CanvasFile, strict=False)

        if locked:
            return self.update_file(uploaded.id, locked=True)
        return uploaded

    def delete_file(self, file_id: int) -> None:
        """Delete a file."""
        self._client.delete(f"/files/{file_id}")
