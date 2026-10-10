"""Argument rules for adding a module item from the command line."""

from __future__ import annotations

__docformat__ = "google"

from .config import MODULE_ITEM_TYPES, canonical_item_type

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
