from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import pytest

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.imaging import worker as image_worker
from instantlink_bridge.imaging.pipeline import FitMode, ImageTooLargeError, PreparedImage
from instantlink_bridge.imaging.worker import (
    ImagePreparationRequest,
    ImagePreparationTimeoutError,
    ImagePreparationWorker,
)


class FakeProcess:
    def __init__(self) -> None:
        self.pid: int | None = 1234
        self.exitcode: int | None = None
        self.started = False
        self.terminated = False
        self.killed = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started and self.exitcode is None

    def terminate(self) -> None:
        self.terminated = True
        self.exitcode = -15

    def kill(self) -> None:
        self.killed = True
        self.exitcode = -9

    def join(self, timeout: float | None = None) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def finish(self, exitcode: int = 0) -> None:
        self.exitcode = exitcode


class FakeResultReader:
    def __init__(self) -> None:
        self.closed = False
        self._result: object | None = None

    def set_result(self, result: object) -> None:
        self._result = result

    def poll(self, timeout: float = 0.0) -> bool:
        return self._result is not None

    def recv(self) -> object:
        if self._result is None:
            raise AssertionError("result is not ready")
        return self._result

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(
        self,
        handles: list[tuple[FakeProcess, FakeResultReader]],
        on_call: Callable[[int], None] | None = None,
    ) -> None:
        self.handles = handles
        self.on_call = on_call
        self.requests: list[ImagePreparationRequest] = []

    def __call__(self, request: ImagePreparationRequest) -> image_worker._WorkerHandle:
        index = len(self.requests)
        self.requests.append(request)
        if self.on_call is not None:
            self.on_call(index)
        process, reader = self.handles[index]
        return image_worker._WorkerHandle(process=process, result_reader=reader)


def _prepared(model: PrinterModel = PrinterModel.MINI) -> image_worker._PreparedImageResult:
    return image_worker._PreparedImageResult(
        PreparedImage(
            data=b"\xff\xd8\xff\xd9",
            model=model,
            width=600,
            height=800,
            quality=90,
            fit=FitMode.AUTO,
        )
    )


@pytest.mark.asyncio
async def test_prepare_timeout_terminates_worker_process(tmp_path: Path) -> None:
    process = FakeProcess()
    reader = FakeResultReader()
    factory = FakeFactory([(process, reader)])
    worker = ImagePreparationWorker(
        process_factory=factory,
        poll_interval_s=0.001,
        shutdown_grace_s=0.001,
    )

    with pytest.raises(ImagePreparationTimeoutError):
        await worker.prepare(tmp_path / "image.hif", PrinterModel.MINI, timeout_s=0.005)

    assert process.started
    assert process.terminated
    assert process.closed
    assert reader.closed


@pytest.mark.asyncio
async def test_prepare_cancel_terminates_worker_process(tmp_path: Path) -> None:
    process = FakeProcess()
    reader = FakeResultReader()
    started = asyncio.Event()
    factory = FakeFactory([(process, reader)], on_call=lambda _index: started.set())
    worker = ImagePreparationWorker(
        process_factory=factory,
        poll_interval_s=0.001,
        shutdown_grace_s=0.001,
    )

    task = asyncio.create_task(worker.prepare(tmp_path / "image.arw", PrinterModel.MINI))
    await asyncio.wait_for(started.wait(), timeout=0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.started
    assert process.terminated
    assert process.closed
    assert reader.closed


@pytest.mark.asyncio
async def test_queued_prepare_waits_for_timed_out_worker_exit(tmp_path: Path) -> None:
    first_process = FakeProcess()
    first_reader = FakeResultReader()
    second_process = FakeProcess()
    second_reader = FakeResultReader()
    first_called = asyncio.Event()
    second_called = asyncio.Event()

    def on_factory_call(index: int) -> None:
        if index == 0:
            first_called.set()
        else:
            assert first_process.terminated
            assert not first_process.is_alive()
            second_called.set()

    factory = FakeFactory(
        [(first_process, first_reader), (second_process, second_reader)],
        on_call=on_factory_call,
    )
    worker = ImagePreparationWorker(
        process_factory=factory,
        poll_interval_s=0.001,
        shutdown_grace_s=0.001,
    )

    first = asyncio.create_task(
        worker.prepare(tmp_path / "first.hif", PrinterModel.MINI, timeout_s=0.02)
    )
    await asyncio.wait_for(first_called.wait(), timeout=0.1)
    second = asyncio.create_task(worker.prepare(tmp_path / "second.jpg", PrinterModel.MINI))
    await asyncio.sleep(0.005)

    assert len(factory.requests) == 1

    with pytest.raises(ImagePreparationTimeoutError):
        await first

    await asyncio.wait_for(second_called.wait(), timeout=0.1)
    second_reader.set_result(_prepared())
    second_process.finish()

    prepared = await second

    assert prepared.model is PrinterModel.MINI
    assert len(factory.requests) == 2


@pytest.mark.asyncio
async def test_worker_preserves_image_too_large_outcome(tmp_path: Path) -> None:
    process = FakeProcess()
    reader = FakeResultReader()
    reader.set_result(
        image_worker._WorkerFailureResult(
            code="too_large",
            message="too large",
            size=25_000_000,
            maximum=24_000_000,
            unit="pixels",
        )
    )
    process.finish()
    factory = FakeFactory([(process, reader)])
    worker = ImagePreparationWorker(process_factory=factory, poll_interval_s=0.001)

    with pytest.raises(ImageTooLargeError) as error:
        await worker.prepare(tmp_path / "image.hif", PrinterModel.MINI)

    assert error.value.size == 25_000_000
    assert error.value.maximum == 24_000_000
    assert error.value.unit == "pixels"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX isolated process groups")
@pytest.mark.parametrize("outcome", ["cancel", "timeout", "parent_crash", "close"])
async def test_hif_decoder_descendant_stops_with_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    import signal
    import sys
    import time

    from PIL import Image

    decoder_pid = tmp_path / "decoder.pid"
    decoder = tmp_path / "heif-thumbnailer"
    decoder.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"pathlib.Path({str(decoder_pid)!r}).write_text(str(os.getpid()))\n"
        + ("os.kill(os.getppid(), signal.SIGKILL)\n" if outcome == "parent_crash" else "")
        + "time.sleep(30)\n"
    )
    decoder.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    source = tmp_path / "source.hif"
    source.write_bytes(b"fake decoder fixture")
    worker = ImagePreparationWorker(poll_interval_s=0.005, shutdown_grace_s=0.05)
    task = asyncio.create_task(
        worker.prepare(source, PrinterModel.SQUARE, timeout_s=3 if outcome == "timeout" else None)
    )
    pid: int | None = None

    def running(pid: int) -> bool:
        status = Path(f"/proc/{pid}/stat")
        try:
            if status.exists() and status.read_text().split()[2] == "Z":
                return False
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    try:
        deadline = time.monotonic() + 5
        while not decoder_pid.exists() and time.monotonic() < deadline and not task.done():  # noqa: ASYNC110 - external process writes the file
            await asyncio.sleep(0.01)
        assert decoder_pid.exists(), "decoder did not start"
        pid = int(decoder_pid.read_text())
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        elif outcome == "close":
            await asyncio.wait_for(worker.aclose(), 1)
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "timeout":
            with pytest.raises(ImagePreparationTimeoutError):
                await asyncio.wait_for(task, 4)
        else:
            with pytest.raises((image_worker.ImageWorkerError, EOFError)):
                await asyncio.wait_for(task, 1)
        deadline = time.monotonic() + 1
        while running(pid) and time.monotonic() < deadline:  # noqa: ASYNC110 - external process exit
            await asyncio.sleep(0.01)
        assert not running(pid), "decoder kept consuming resources after worker exit"
        # Cancellation leaves the worker ready for the next image; no changed pixels.
        jpeg = tmp_path / "next.jpg"
        Image.new("RGB", (30, 30), "orange").save(jpeg)
        if outcome == "close":
            with pytest.raises(image_worker.ImageWorkerError, match="closed"):
                await worker.prepare(jpeg, PrinterModel.SQUARE)
        else:
            assert (
                await worker.prepare(jpeg, PrinterModel.SQUARE, timeout_s=5)
            ).model is PrinterModel.SQUARE
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if pid is not None and running(pid):
            os.kill(pid, signal.SIGKILL)
        await worker.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX isolated process groups")
async def test_cancellation_before_worker_isolation_never_signals_bridge_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess()
    process.pid = os.getpid() + 1
    process.start()
    bridge_group = os.getpgrp()
    calls: list[int] = []
    monkeypatch.setattr(image_worker.os, "getpgid", lambda _: bridge_group)
    monkeypatch.setattr(image_worker.os, "killpg", lambda group, _: calls.append(group))
    worker = ImagePreparationWorker()
    assert await worker._terminate_process(process, isolated_process_group=True)
    assert process.terminated
    assert calls == []
    await worker._finalize_process(process, isolated_process_group=True)
    assert calls == [process.pid]
    assert bridge_group not in calls


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX isolated process groups")
async def test_termination_of_already_exited_worker_still_cleans_owned_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess()
    process.pid = os.getpid() + 1
    process.finish()
    calls: list[int] = []
    monkeypatch.setattr(image_worker.os, "killpg", lambda group, _: calls.append(group))
    worker = ImagePreparationWorker()
    assert await worker._terminate_process(process, isolated_process_group=True)
    assert calls == [process.pid]


@pytest.mark.asyncio
async def test_close_interrupts_active_work_and_rejects_queued_preparation(tmp_path: Path) -> None:
    first_process = FakeProcess()
    first_reader = FakeResultReader()
    unused_process = FakeProcess()
    unused_reader = FakeResultReader()
    started = asyncio.Event()
    factory = FakeFactory(
        [(first_process, first_reader), (unused_process, unused_reader)],
        on_call=lambda _: started.set(),
    )
    worker = ImagePreparationWorker(process_factory=factory, shutdown_grace_s=0.01)
    first = asyncio.create_task(worker.prepare(tmp_path / "active.hif", PrinterModel.SQUARE))
    await asyncio.wait_for(started.wait(), 0.5)
    queued = asyncio.create_task(worker.prepare(tmp_path / "queued.hif", PrinterModel.SQUARE))
    await asyncio.wait_for(worker.aclose(), 0.5)
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(image_worker.ImageWorkerError, match="closed"):
        await queued
    assert first_process.terminated and first_process.closed and first_reader.closed
    assert not unused_process.started
    assert len(factory.requests) == 1
    await worker.aclose()


@pytest.mark.asyncio
async def test_concurrent_close_calls_join_one_process_cleanup(tmp_path: Path) -> None:
    termination_started = asyncio.Event()
    started = asyncio.Event()

    class SlowProcess(FakeProcess):
        def terminate(self) -> None:
            self.terminated = True
            termination_started.set()

    process = SlowProcess()
    reader = FakeResultReader()
    factory = FakeFactory([(process, reader)], on_call=lambda _: started.set())
    worker = ImagePreparationWorker(
        process_factory=factory, poll_interval_s=0.001, shutdown_grace_s=0.5
    )
    preparing = asyncio.create_task(worker.prepare(tmp_path / "active.hif", PrinterModel.SQUARE))
    await asyncio.wait_for(started.wait(), 0.5)
    first_close = asyncio.create_task(worker.aclose())
    await asyncio.wait_for(termination_started.wait(), 0.5)
    second_close = asyncio.create_task(worker.aclose())
    await asyncio.sleep(0)
    assert worker._active_prepare_task is not None
    assert worker._active_prepare_task.cancelling() == 1
    assert not second_close.done()
    process.finish(-15)
    await asyncio.wait_for(asyncio.gather(first_close, second_close), 0.5)
    with pytest.raises(asyncio.CancelledError):
        await preparing
    assert process.closed and reader.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("close_started", [False, True])
async def test_parent_cancellation_does_not_interrupt_existing_worker_cleanup(
    tmp_path: Path, close_started: bool
) -> None:
    started, terminating = asyncio.Event(), asyncio.Event()

    class SlowProcess(FakeProcess):
        def terminate(self) -> None:
            self.terminated = True
            terminating.set()

    process = SlowProcess()
    reader = FakeResultReader()
    worker = ImagePreparationWorker(
        process_factory=FakeFactory([(process, reader)], on_call=lambda _: started.set()),
        poll_interval_s=0.001,
        shutdown_grace_s=0.5,
    )
    parent = asyncio.create_task(worker.prepare(tmp_path / "active.hif", PrinterModel.SQUARE))
    await asyncio.wait_for(started.wait(), 0.5)
    closing = asyncio.create_task(worker.aclose()) if close_started else None
    if not close_started:
        parent.cancel()
    await asyncio.wait_for(terminating.wait(), 0.5)
    parent.cancel()
    await asyncio.sleep(0)
    parent.cancel()
    await asyncio.sleep(0)
    assert not parent.done()
    assert worker._active_prepare_task is not None
    assert worker._active_prepare_task.cancelling() == 1
    process.finish(-15)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(parent, 0.5)
    if closing is not None:
        await asyncio.wait_for(closing, 0.5)
    assert process.closed and reader.closed
    await worker.aclose()
