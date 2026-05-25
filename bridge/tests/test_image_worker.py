from __future__ import annotations

import asyncio
from collections.abc import Callable
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
