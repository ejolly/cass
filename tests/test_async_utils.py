"""Tests for bounded concurrent task runner."""

from __future__ import annotations

__docformat__ = "google"

import asyncio

from cass.async_utils import TaskResult, gather_bounded


class TestGatherBounded:
    async def test_all_tasks_succeed(self) -> None:
        """All tasks complete, results in insertion order, values set, errors None."""

        async def work(n: int) -> int:
            return n * 10

        tasks = {f"t{i}": work(i) for i in range(5)}
        results = await gather_bounded(tasks, max_concurrent=3)

        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.key == f"t{i}"
            assert r.value == i * 10
            assert r.error is None
            assert 1 <= r.index <= 5

    async def test_respects_concurrency_limit(self) -> None:
        """Peak concurrency never exceeds max_concurrent."""
        peak = 0
        current = 0
        lock = asyncio.Lock()

        async def work() -> str:
            nonlocal peak, current
            async with lock:
                current += 1
                if current > peak:
                    peak = current
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1
            return "done"

        tasks = {f"t{i}": work() for i in range(10)}
        await gather_bounded(tasks, max_concurrent=3)

        assert peak <= 3

    async def test_continues_on_error(self) -> None:
        """One failing task doesn't cancel siblings."""

        async def work(n: int) -> int:
            if n == 2:
                raise RuntimeError("boom")
            return n

        tasks = {f"t{i}": work(i) for i in range(5)}
        results = await gather_bounded(tasks, max_concurrent=5)

        assert len(results) == 5
        assert results[2].error is not None
        assert isinstance(results[2].error, RuntimeError)
        assert results[2].value is None
        for i in [0, 1, 3, 4]:
            assert results[i].value == i
            assert results[i].error is None

    async def test_on_complete_indices(self) -> None:
        """on_complete receives monotonically increasing indices 1..N."""
        completed: list[TaskResult[str]] = []

        async def work(delay: float) -> str:
            await asyncio.sleep(delay)
            return "ok"

        tasks = {"fast": work(0.01), "medium": work(0.03), "slow": work(0.05)}

        await gather_bounded(
            tasks,
            max_concurrent=3,
            on_complete=lambda r: completed.append(r),
        )

        assert len(completed) == 3
        indices = [r.index for r in completed]
        assert sorted(indices) == [1, 2, 3]
        # Keys should all be present
        keys = {r.key for r in completed}
        assert keys == {"fast", "medium", "slow"}

    async def test_empty_tasks(self) -> None:
        """Empty input returns empty list."""
        results = await gather_bounded({}, max_concurrent=3)
        assert results == []

    async def test_all_fail(self) -> None:
        """All failing tasks produce results with errors, no values."""

        async def fail(msg: str) -> str:
            raise ValueError(msg)

        tasks = {f"t{i}": fail(f"err-{i}") for i in range(3)}
        results = await gather_bounded(tasks, max_concurrent=3)

        assert len(results) == 3
        for r in results:
            assert r.value is None
            assert r.error is not None
            assert isinstance(r.error, ValueError)
