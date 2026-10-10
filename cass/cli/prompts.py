"""Confirmation prompts shared by every destructive CLI command."""

from __future__ import annotations

__docformat__ = "google"

import sys

import typer

from .canvas._common import err_console


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def confirm(
    message: str, *, yes: bool, dry_run: bool = False, default: bool = False
) -> None:
    """Return when the action may proceed.

    Args:
        message: Question shown to the user.
        yes: Skip the prompt (``--yes``).
        dry_run: Nothing will be sent, so never prompt.
        default: Answer used when the user just presses enter.

    Raises:
        typer.Abort: The user declined.
        typer.Exit: Not interactive and ``yes`` was not given.
    """
    if dry_run or yes:
        return
    if not _stdin_is_tty():
        err_console.print(
            f"{message} Run with --yes to confirm without a prompt.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(code=1)
    if not typer.confirm(message, default=default, err=True):
        raise typer.Abort()
