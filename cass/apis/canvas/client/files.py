"""Files and folders."""

from __future__ import annotations

__docformat__ = "google"

import httpx
import msgspec

from ..schema import CanvasFile, CanvasFolder
from .base import BaseClient


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

    def list_folders(self) -> list[CanvasFolder]:
        """List all folders in the course.

        Returns:
            Folders with hierarchy info.
        """
        data = self._get_paginated(self._course("/folders"))
        return msgspec.convert(data, list[CanvasFolder], strict=False)

    def upload_file(self, local_path: str, *, folder: str = "") -> CanvasFile:
        """Upload a file to the course.

        Uses Canvas's 3-step file upload flow:
        1. Notify Canvas to get an upload URL
        2. POST the file to the upload URL
        3. Confirm the upload

        Args:
            local_path: Path to the local file.
            folder: Destination folder path in Canvas (e.g. ``course files/slides``).

        Returns:
            The uploaded file metadata.
        """
        import os as _os

        filename = _os.path.basename(local_path)
        size = _os.path.getsize(local_path)

        # Step 1: notify Canvas
        params: dict[str, object] = {
            "name": filename,
            "size": size,
            "parent_folder_path": folder or "/",
        }
        resp = self._client.post(self._course("/files"), data=params)
        resp.raise_for_status()
        upload_info = resp.json()

        # Step 2: POST to upload URL
        upload_url = upload_info["upload_url"]
        upload_params = upload_info.get("upload_params", {})
        with open(local_path, "rb") as f:
            # Upload URL is absolute — use a fresh httpx call
            resp2 = httpx.post(
                upload_url,
                data=upload_params,
                files={"file": (filename, f)},
                timeout=120.0,
            )
        resp2.raise_for_status()

        # Step 3: Canvas may return the file directly or a redirect
        if resp2.status_code == 201:
            return msgspec.convert(resp2.json(), CanvasFile, strict=False)

        # Follow redirect if needed
        location = resp2.headers.get("Location")
        if location:
            resp3 = self._client.get(location)
            resp3.raise_for_status()
            return msgspec.convert(resp3.json(), CanvasFile, strict=False)

        return msgspec.convert(resp2.json(), CanvasFile, strict=False)

    def delete_file(self, file_id: int) -> None:
        """Delete a file."""
        resp = self._client.delete(f"/files/{file_id}")
        resp.raise_for_status()
