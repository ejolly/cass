from __future__ import annotations

__docformat__ = "google"

import shutil
import subprocess


def _executable() -> str:
    executable = shutil.which("sqlite-utils")
    if executable is None:
        msg = (
            "`sqlite-utils` is not installed or not on PATH.\n"
            "Install it with `uv tool install sqlite-utils` or add it to PATH."
        )
        raise RuntimeError(msg)
    return executable


def run_sqlite_utils(args: list[str]) -> str:
    """Run ``sqlite-utils`` and return its stdout."""
    result = subprocess.run(
        [_executable(), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (
            result.stderr.strip() or result.stdout.strip() or "sqlite-utils failed"
        )
        raise RuntimeError(message)
    return result.stdout


def render_rows(
    db_file: str,
    table: str,
    *,
    where: str = "",
    order: str = "",
    limit: int = 0,
) -> str:
    """Render rows from a table using ``sqlite-utils rows``."""
    args = ["rows", db_file, table, "--table"]
    if where:
        args.extend(["--where", where])
    if order:
        args.extend(["--order", order])
    if limit:
        args.extend(["--limit", str(limit)])
    return run_sqlite_utils(args)


def render_query(db_file: str, sql: str) -> str:
    """Render an arbitrary SQL query using ``sqlite-utils query``."""
    return run_sqlite_utils(["query", db_file, sql, "--table"])
