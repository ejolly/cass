"""Tests for file upload policies and folder subtree selection."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

import pytest

from cass.actions.files import (
    FileUpload,
    OnDuplicate,
    folder_subtree,
    upload_course_file,
)
from cass.apis.canvas.schema import CanvasFile, CanvasFolder


@pytest.fixture
def local_file(tmp_path):
    path = tmp_path / "w1.pdf"
    path.write_bytes(b"12345")
    return str(path)


@pytest.fixture
def client():
    fake = MagicMock()
    fake.upload_file.return_value = CanvasFile(id=9, display_name="w1.pdf", size=5)
    return fake


def test_skip_same_name_and_size_uploads_nothing(client, local_file):
    existing = CanvasFile(id=7, display_name="w1.pdf", size=5)
    client.find_folder.return_value = CanvasFolder(id=2, name="readings")
    client.list_files.return_value = [existing]

    result = upload_course_file(
        client, local_file, folder="readings", on_duplicate=OnDuplicate.SKIP
    )

    assert result == FileUpload(file=existing, skipped=True)
    client.upload_file.assert_not_called()


def test_skip_same_name_different_size_overwrites(client, local_file):
    client.find_folder.return_value = CanvasFolder(id=2, name="readings")
    client.list_files.return_value = [CanvasFile(id=7, display_name="w1.pdf", size=99)]

    result = upload_course_file(
        client, local_file, folder="readings", on_duplicate=OnDuplicate.SKIP
    )

    assert result.skipped is False
    assert client.upload_file.call_args.kwargs["on_duplicate"] == "overwrite"


def test_skip_with_missing_folder_uploads(client, local_file):
    client.find_folder.return_value = None

    result = upload_course_file(
        client, local_file, folder="readings", on_duplicate=OnDuplicate.SKIP
    )

    assert result.skipped is False
    client.list_files.assert_not_called()
    kwargs = client.upload_file.call_args.kwargs
    assert kwargs["on_duplicate"] == "rename"
    assert kwargs["folder"] == "readings"


def test_new_upload_is_locked_by_default(client, local_file):
    client.find_folder.return_value = None

    upload_course_file(client, local_file)

    assert client.upload_file.call_args.kwargs["locked"] is True
    client.update_file.assert_not_called()


def test_publish_leaves_new_upload_unlocked(client, local_file):
    upload_course_file(
        client, local_file, on_duplicate=OnDuplicate.RENAME, published=True
    )

    assert client.upload_file.call_args.kwargs["locked"] is False
    client.find_folder.assert_not_called()


@pytest.mark.parametrize("was_locked", [True, False])
def test_overwrite_keeps_existing_lock(client, local_file, was_locked):
    client.find_folder.return_value = CanvasFolder(id=2, name="readings")
    client.list_files.return_value = [
        CanvasFile(id=7, display_name="w1.pdf", size=99, locked=was_locked)
    ]

    upload_course_file(client, local_file, folder="readings")

    kwargs = client.upload_file.call_args.kwargs
    assert kwargs["on_duplicate"] == "overwrite"
    assert kwargs["locked"] is was_locked
    client.update_file.assert_not_called()


def test_publish_over_locked_file_unlocks_it(client, local_file):
    client.find_folder.return_value = CanvasFolder(id=2, name="readings")
    client.list_files.return_value = [
        CanvasFile(id=7, display_name="w1.pdf", size=99, locked=True)
    ]

    upload_course_file(client, local_file, folder="readings", published=True)

    assert client.upload_file.call_args.kwargs["locked"] is False
    client.update_file.assert_called_once_with(9, locked=False)


def test_rename_upload_is_a_new_locked_file(client, local_file):
    upload_course_file(client, local_file, on_duplicate=OnDuplicate.RENAME)

    assert client.upload_file.call_args.kwargs["locked"] is True


def test_folder_subtree():
    root = CanvasFolder(id=1, name="course files", full_name="course files")
    readings = CanvasFolder(id=2, name="readings", full_name="course files/readings")
    week1 = CanvasFolder(id=3, name="week1", full_name="course files/readings/week1")
    other = CanvasFolder(id=4, name="readingsX", full_name="course files/readingsX")
    files = [
        CanvasFile(id=10, display_name="a", folder_id=1),
        CanvasFile(id=11, display_name="b", folder_id=3),
        CanvasFile(id=12, display_name="c", folder_id=4),
    ]

    folders, kept = folder_subtree([root, readings, week1, other], files, readings)

    assert [f.id for f in folders] == [2, 3]
    assert [f.id for f in kept] == [11]


def test_default_policy_overwrites(client, local_file):
    upload_course_file(client, local_file)

    assert client.upload_file.call_args.kwargs["on_duplicate"] == "overwrite"
