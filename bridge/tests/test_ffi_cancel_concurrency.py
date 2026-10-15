from __future__ import annotations

import asyncio
import threading

import pytest

from instantlink_bridge.ble import instantlink
from instantlink_bridge.ble.instantlink import InstantLinkBackend


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("worker failed"), TimeoutError("worker deadline")])
async def test_cancelled_worker_failure_preserves_cancellation_without_false_restart(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    started, release, next_started = (threading.Event() for _ in range(3))
    backend = InstantLinkBackend()

    def worker() -> None:
        started.set()
        assert release.wait(2)
        raise error

    def restart(_code: int) -> None:
        raise AssertionError("completed failing worker must not restart the process")

    monkeypatch.setattr(instantlink.os, "_exit", restart)
    task = asyncio.create_task(backend._run_blocking_serialized("status", worker))
    next_task: asyncio.Task[object] | None = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        next_task = asyncio.create_task(
            backend._run_blocking_serialized("next", lambda: next_started.set())
        )
        await asyncio.sleep(0)
        assert not next_started.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        await asyncio.wait_for(next_task, 1)
        assert next_started.is_set()
    finally:
        release.set()
        await asyncio.gather(task, *([next_task] if next_task else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancellation_retains_printer_lock_until_blocking_worker_finishes() -> None:
    started, release, second_started = (threading.Event() for _ in range(3))
    backend = InstantLinkBackend()

    def first_work() -> None:
        started.set()
        if not release.wait(2):
            raise AssertionError("test did not release worker")

    def second_work() -> int:
        second_started.set()
        return 42

    first = asyncio.create_task(backend._run_blocking_serialized("first", first_work))
    second: asyncio.Task[int] | None = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        first.cancel()
        await asyncio.sleep(0)
        second = asyncio.create_task(backend._run_blocking_serialized("second", second_work))
        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()
        assert backend._lock.locked()
        assert not second_started.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 1)
        assert await asyncio.wait_for(second, 1) == 42
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_extend_ffi_restart_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = threading.Event(), threading.Event()
    backend = InstantLinkBackend()
    restart_times: list[float] = []
    loop = asyncio.get_running_loop()

    def worker() -> None:
        started.set()
        if not release.wait(2):
            raise AssertionError("test did not release worker")

    def restart(code: int) -> None:
        assert code == 1
        restart_times.append(loop.time())
        raise RuntimeError("restart requested")

    monkeypatch.setattr(instantlink, "FFI_CANCEL_GRACE_S", 0.2)
    monkeypatch.setattr(instantlink.os, "_exit", restart)
    task = asyncio.create_task(backend._run_blocking_serialized("stalled", worker))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        cancelled_at = loop.time()
        task.cancel()
        await asyncio.sleep(0.08)
        task.cancel()
        await asyncio.sleep(0.09)
        task.cancel()
        with pytest.raises(RuntimeError, match="restart requested"):
            await asyncio.wait_for(task, 0.13)
        assert len(restart_times) == 1
        assert 0.19 <= restart_times[0] - cancelled_at < 0.3
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
