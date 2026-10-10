"""JSON records that combine several Canvas objects, for ``--json`` output.

Field names are Canvas's own (``msgspec.to_builtins`` honours renames such as
``content-type``)."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING, Any

import msgspec

if TYPE_CHECKING:
    from ..apis.canvas.schema import (
        CanvasFile,
        CanvasFolder,
        CanvasModule,
        CanvasModuleItem,
        CanvasQuiz,
        CanvasQuizQuestion,
    )


def file_tree_records(
    folders: list[CanvasFolder], files: list[CanvasFile]
) -> list[dict[str, Any]]:
    """Every folder, then every file, each tagged with ``kind``."""
    records: list[dict[str, Any]] = []
    for folder in folders:
        records.append({**msgspec.to_builtins(folder), "kind": "folder"})
    for file in files:
        records.append({**msgspec.to_builtins(file), "kind": "file"})
    return records


def folder_records(folders: list[CanvasFolder]) -> list[dict[str, Any]]:
    """Every folder with its path relative to the course files root added."""
    from ..apis.canvas.client.files import folder_paths

    paths = folder_paths(folders)
    return [{**msgspec.to_builtins(f), "path": paths[f.id]} for f in folders]


def quiz_detail_record(
    quiz: CanvasQuiz,
    questions: list[CanvasQuizQuestion],
    *,
    from_statistics: bool,
) -> dict[str, Any]:
    """A quiz with its questions and where the questions were read from."""
    return {
        **msgspec.to_builtins(quiz),
        "questions": msgspec.to_builtins(questions),
        "questions_source": "statistics" if from_statistics else "questions",
    }


def module_detail_record(
    module: CanvasModule, items: list[CanvasModuleItem]
) -> dict[str, Any]:
    """A module with its items."""
    return {**msgspec.to_builtins(module), "items": msgspec.to_builtins(items)}
