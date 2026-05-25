"""Async, killable image preparation worker."""

from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Literal, Protocol, cast

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    ImagePipelineError,
    ImageTooLargeError,
    PreparedImage,
    PrintEdit,
    UnsupportedImageError,
    prepare_for_instax,
)


class ImageWorkerError(ImagePipelineError):
    """Raised when the image worker process fails outside image decoding."""


class ImagePreparationTimeoutError(ImagePipelineError):
    """Raised when image preparation exceeds its deadline."""


@dataclass(frozen=True, slots=True)
class ImagePreparationRequest:
    """Arguments for one image preparation job."""

    source_path: Path
    model: PrinterModel
    fit: FitMode = FitMode.AUTO
    quality: int = 100
    edit: PrintEdit | None = None


@dataclass(frozen=True, slots=True)
class _PreparedImageResult:
    prepared: PreparedImage


_WorkerFailureCode = Literal["unsupported", "too_large", "pipeline", "unexpected"]


@dataclass(frozen=True, slots=True)
class _WorkerFailureResult:
    code: _WorkerFailureCode
    message: str
    size: int | None = None
    maximum: int | None = None
    unit: str = "bytes"


class _Closable(Protocol):
    def close(self) -> None:
        """Close the resource."""


class _ResultReader(_Closable, Protocol):
    def poll(self, timeout: float = 0.0) -> bool:
        """Return whether a worker result is ready."""

    def recv(self) -> object:
        """Read one worker result."""


class _ManagedProcess(Protocol):
    pid: int | None
    exitcode: int | None

    def start(self) -> None:
        """Start the process."""

    def is_alive(self) -> bool:
        """Return whether the process is still running."""

    def terminate(self) -> None:
        """Terminate the process."""

    def kill(self) -> None:
        """Kill the process."""

    def join(self, timeout: float | None = None) -> None:
        """Join the process."""

    def close(self) -> None:
        """Close process resources."""


@dataclass(frozen=True, slots=True)
class _WorkerHandle:
    process: _ManagedProcess
    result_reader: _ResultReader
    parent_writer: _Closable | None = None


_ProcessFactory = Callable[[ImagePreparationRequest], _WorkerHandle]


class ImagePreparationWorker:
    """Run image preparation in at most one killable child process."""

    def __init__(
        self,
        *,
        process_factory: _ProcessFactory | None = None,
        poll_interval_s: float = 0.01,
        shutdown_grace_s: float = 0.5,
    ) -> None:
        self._process_factory = process_factory or _create_process
        self._poll_interval_s = poll_interval_s
        self._shutdown_grace_s = shutdown_grace_s
        self._lock = asyncio.Lock()
        self._active_process: _ManagedProcess | None = None
        self._termination_failed = False

    async def prepare(
        self,
        source_path: Path,
        model: PrinterModel,
        *,
        fit: FitMode = FitMode.AUTO,
        quality: int = 100,
        edit: PrintEdit | None = None,
        timeout_s: float | None = None,
    ) -> PreparedImage:
        """Prepare an image asynchronously in a killable worker process."""

        request = ImagePreparationRequest(
            source_path=source_path,
            model=model,
            fit=fit,
            quality=quality,
            edit=edit,
        )
        async with self._lock:
            if self._termination_failed:
                raise ImageWorkerError("image worker unavailable after failed termination")
            return await self._prepare_locked(request, timeout_s)

    async def aclose(self) -> None:
        """Terminate any active worker process."""

        async with self._lock:
            if self._active_process is not None:
                terminated = await self._terminate_process(self._active_process)
                if not terminated:
                    self._termination_failed = True
                    raise ImageWorkerError("image worker could not be terminated")

    async def _prepare_locked(
        self,
        request: ImagePreparationRequest,
        timeout_s: float | None,
    ) -> PreparedImage:
        handle = self._process_factory(request)
        process = handle.process
        self._active_process = process
        started = False

        try:
            process.start()
            started = True
            if handle.parent_writer is not None:
                _close_quietly(handle.parent_writer)

            result = self._wait_for_result(process, handle.result_reader)
            if timeout_s is None:
                return await result
            try:
                return await asyncio.wait_for(result, timeout=timeout_s)
            except TimeoutError as error:
                terminated = await self._terminate_process(process)
                if not terminated:
                    self._termination_failed = True
                    raise ImageWorkerError(
                        "image worker could not be terminated after timeout"
                    ) from error
                raise ImagePreparationTimeoutError(
                    f"image preparation timed out after {timeout_s:.2f}s"
                ) from error
        except asyncio.CancelledError:
            terminated = await self._terminate_process(process)
            if not terminated:
                self._termination_failed = True
            raise
        finally:
            if started:
                await self._finalize_process(process)
            else:
                _close_quietly(process)
            if handle.parent_writer is not None:
                _close_quietly(handle.parent_writer)
            _close_quietly(handle.result_reader)
            self._active_process = None

    async def _wait_for_result(
        self,
        process: _ManagedProcess,
        result_reader: _ResultReader,
    ) -> PreparedImage:
        while True:
            if result_reader.poll(0.0):
                return _decode_result(result_reader.recv())

            if not process.is_alive():
                process.join(0.0)
                if result_reader.poll(0.0):
                    return _decode_result(result_reader.recv())
                exitcode = process.exitcode
                if exitcode == 0:
                    raise ImageWorkerError("image worker exited without a result")
                raise ImageWorkerError(f"image worker exited with status {exitcode}")

            await asyncio.sleep(self._poll_interval_s)

    async def _finalize_process(self, process: _ManagedProcess) -> None:
        if process.is_alive():
            exited = await self._wait_for_exit(process, self._shutdown_grace_s)
            if not exited:
                terminated = await self._terminate_process(process)
                if not terminated:
                    self._termination_failed = True
                    return
        process.join(0.0)
        _close_quietly(process)

    async def _terminate_process(self, process: _ManagedProcess) -> bool:
        if not process.is_alive():
            process.join(0.0)
            return True

        process.terminate()
        if await self._wait_for_exit(process, self._shutdown_grace_s):
            return True

        process.kill()
        return await self._wait_for_exit(process, self._shutdown_grace_s)

    async def _wait_for_exit(self, process: _ManagedProcess, timeout_s: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while process.is_alive() and loop.time() < deadline:
            process.join(0.0)
            await asyncio.sleep(min(self._poll_interval_s, max(0.0, deadline - loop.time())))
        process.join(0.0)
        return not process.is_alive()


_default_worker: ImagePreparationWorker | None = None


def default_image_preparation_worker() -> ImagePreparationWorker:
    """Return the process-backed singleton image preparation worker."""

    global _default_worker

    if _default_worker is None:
        _default_worker = ImagePreparationWorker()
    return _default_worker


async def close_default_image_preparation_worker() -> None:
    """Close the process-backed singleton image preparation worker, if created."""

    if _default_worker is not None:
        await _default_worker.aclose()


async def prepare_for_instax_async(
    source_path: Path,
    model: PrinterModel,
    *,
    fit: FitMode = FitMode.AUTO,
    quality: int = 100,
    edit: PrintEdit | None = None,
    timeout_s: float | None = None,
    worker: ImagePreparationWorker | None = None,
) -> PreparedImage:
    """Prepare an image with the default killable process worker."""

    image_worker = worker or default_image_preparation_worker()
    return await image_worker.prepare(
        source_path,
        model,
        fit=fit,
        quality=quality,
        edit=edit,
        timeout_s=timeout_s,
    )


def _create_process(request: ImagePreparationRequest) -> _WorkerHandle:
    receive_connection, send_connection = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(
        target=_run_prepare_in_child,
        args=(send_connection, request),
        daemon=True,
    )
    return _WorkerHandle(
        process=cast(_ManagedProcess, process),
        result_reader=cast(_ResultReader, receive_connection),
        parent_writer=cast(_Closable, send_connection),
    )


def _run_prepare_in_child(
    result_writer: Connection,
    request: ImagePreparationRequest,
) -> None:
    try:
        prepared = prepare_for_instax(
            request.source_path,
            request.model,
            fit=request.fit,
            quality=request.quality,
            edit=request.edit,
        )
        result_writer.send(_PreparedImageResult(prepared))
    except ImageTooLargeError as error:
        result_writer.send(
            _WorkerFailureResult(
                code="too_large",
                message=str(error),
                size=error.size,
                maximum=error.maximum,
                unit=error.unit,
            )
        )
    except UnsupportedImageError as error:
        result_writer.send(_WorkerFailureResult(code="unsupported", message=str(error)))
    except ImagePipelineError as error:
        result_writer.send(_WorkerFailureResult(code="pipeline", message=str(error)))
    except Exception as error:
        result_writer.send(
            _WorkerFailureResult(
                code="unexpected",
                message=f"{type(error).__name__}: {error}",
            )
        )
    finally:
        _close_quietly(result_writer)


def _decode_result(result: object) -> PreparedImage:
    if isinstance(result, _PreparedImageResult):
        return result.prepared
    if isinstance(result, _WorkerFailureResult):
        if result.code == "too_large":
            if result.size is None or result.maximum is None:
                raise ImageWorkerError(result.message)
            raise ImageTooLargeError(result.size, result.maximum, result.unit)
        if result.code == "unsupported":
            raise UnsupportedImageError(result.message)
        if result.code == "pipeline":
            raise ImagePipelineError(result.message)
        raise ImageWorkerError(result.message)
    raise ImageWorkerError(f"image worker returned invalid result {type(result).__name__}")


def _close_quietly(resource: _Closable) -> None:
    try:
        resource.close()
    except (OSError, ValueError):
        return
