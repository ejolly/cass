"""Bounded concurrent task runner with per-task error isolation."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class TaskResult(Generic[T]):
    """Result of a single task in a ``gather_bounded`` call.

    Attributes:
        key: Human-readable ID (assignment slug, student name).
        value: Result on success, ``None`` on failure.
        error: Exception on failure, ``None`` on success.
        index: 1-based completion order (for progress: "3/7 done").
    """

    key: str
    value: T | None
    error: Exception | None
    index: int


async def gather_bounded(
    tasks: dict[str, Coroutine[Any, Any, T]],
    *,
    max_concurrent: int = 5,
    on_complete: Callable[[TaskResult[T]], None] | None = None,
) -> list[TaskResult[T]]:
    """Run coroutines with bounded concurrency and per-task error isolation.

    Args:
        tasks: Mapping of key → coroutine. Keys identify tasks in results.
        max_concurrent: Maximum number of tasks running simultaneously.
        on_complete: Optional callback invoked as each task finishes.

    Returns:
        Results in **insertion order** (matching ``tasks`` dict), not
        completion order. Each result captures success value or exception.
    """
    if not tasks:
        return []

    sem = asyncio.Semaphore(max_concurrent)
    counter = 0
    counter_lock = asyncio.Lock()

    # Pre-allocate result slots keyed by position
    keys = list(tasks.keys())
    results: dict[int, TaskResult[T]] = {}

    async def _run(pos: int, key: str, coro: Coroutine[Any, Any, T]) -> None:
        nonlocal counter
        async with sem:
            value: T | None = None
            error: Exception | None = None
            try:
                value = await coro
            except Exception as exc:
                error = exc

        async with counter_lock:
            counter += 1
            idx = counter

        result = TaskResult(key=key, value=value, error=error, index=idx)
        results[pos] = result
        if on_complete is not None:
            on_complete(result)

    await asyncio.gather(
        *(_run(i, key, coro) for i, (key, coro) in enumerate(tasks.items()))
    )

    return [results[i] for i in range(len(keys))]
