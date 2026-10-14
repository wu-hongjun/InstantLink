"""Async, killable image preparation worker."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal, Protocol, cast

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

from instantlink_bridge.ble.models import PrinterModel, spec_for
from instantlink_bridge.imaging.models import (
    HEIF_SUFFIXES,
    AdjustmentProfile,
    CorrectionProfile,
    FitMode,
    ImagePipelineError,
    ImageTooLargeError,
    PreparedImage,
    PrintEdit,
    SourceIdentity,
    UnsupportedImageError,
    WorkingImageCache,
    _working_size_for_model,
    source_identity,
)
from instantlink_bridge.imaging.models import (
    ImagePreparationTimeoutError as ImagePreparationTimeoutError,
)

LOGGER = logging.getLogger(__name__)


def prepare_for_instantlink_backend(
    source_path: Path,
    model: PrinterModel,
    *,
    fit: FitMode = FitMode.AUTO,
    quality: int = 100,
    edit: PrintEdit | None = None,
    adjustments: AdjustmentProfile | None = None,
    correction: CorrectionProfile | None = None,
    working_cache: WorkingImageCache | None = None,
    apply_model_flip: bool = False,
) -> PreparedImage:
    """Load preparation code in the existing killable image child process."""
    from instantlink_bridge.imaging.pipeline import prepare_for_instantlink_backend as prepare

    return prepare(
        source_path,
        model,
        fit=fit,
        quality=quality,
        edit=edit,
        adjustments=adjustments,
        correction=correction,
        working_cache=working_cache,
        apply_model_flip=apply_model_flip,
    )


class ImageWorkerError(ImagePipelineError):
    """Raised when the image worker process fails outside image decoding."""


@dataclass(frozen=True, slots=True)
class ImagePreparationRequest:
    """Arguments for one image preparation job."""

    source_path: Path
    model: PrinterModel
    fit: FitMode = FitMode.AUTO
    quality: int = 100
    edit: PrintEdit | None = None
    adjustments: AdjustmentProfile | None = None
    correction: CorrectionProfile | None = None
    working_cache: WorkingImageCache | None = None
    # False selects logical pixels for the legacy native file API; True
    # applies transport orientation before the final encode for direct bytes.
    apply_model_flip: bool = True


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
    isolated_process_group: bool = False


_ProcessFactory = Callable[[ImagePreparationRequest], _WorkerHandle]


class ImagePreparationWorker:
    """Run image preparation in at most one killable child process."""

    def __init__(
        self,
        *,
        process_factory: _ProcessFactory | None = None,
        poll_interval_s: float = 0.01,
        shutdown_grace_s: float = 0.5,
        working_cache_ttl_s: float = 300.0,
    ) -> None:
        if not math.isfinite(working_cache_ttl_s) or working_cache_ttl_s < 0:
            raise ValueError("working cache TTL must be finite and nonnegative")
        self._process_factory = process_factory or _create_process
        self._poll_interval_s = poll_interval_s
        self._shutdown_grace_s = shutdown_grace_s
        self._lock = asyncio.Lock()
        self._active_process: _ManagedProcess | None = None
        self._active_prepare_task: asyncio.Task[PreparedImage] | None = None
        self._termination_failed = False
        self._closed = False
        self._working_cache_ttl_s = working_cache_ttl_s
        self._working_cache_dir: TemporaryDirectory[str] | None = None
        self._working_cache: WorkingImageCache | None = None
        self._working_cache_key: tuple[SourceIdentity, PrinterModel, tuple[int, int]] | None = None
        self._working_cache_expiry_task: asyncio.Task[None] | None = None

    async def prepare(
        self,
        source_path: Path,
        model: PrinterModel,
        *,
        fit: FitMode = FitMode.AUTO,
        quality: int = 100,
        edit: PrintEdit | None = None,
        adjustments: AdjustmentProfile | None = None,
        correction: CorrectionProfile | None = None,
        timeout_s: float | None = None,
        apply_model_flip: bool = True,
    ) -> PreparedImage:
        """Prepare an image asynchronously in a killable worker process."""

        async with self._lock:
            if self._closed:
                raise ImageWorkerError("image worker is closed")
            if self._termination_failed:
                raise ImageWorkerError("image worker unavailable after failed termination")
            request = ImagePreparationRequest(
                source_path=source_path,
                model=model,
                fit=fit,
                quality=quality,
                edit=edit,
                adjustments=adjustments,
                correction=correction,
                working_cache=self._working_cache_for(source_path, model),
                apply_model_flip=apply_model_flip,
            )
            task = asyncio.create_task(self._prepare_locked(request, timeout_s))
            self._active_prepare_task = task
            try:
                prepared = await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done() and not task.cancelling():
                    task.cancel()
                # Closing the worker and cancelling its caller can race.
                # Further caller cancellation must never interrupt the one
                # process-group cleanup or release the serialization lock.
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                self._drop_working_cache()
                raise
            except BaseException:
                self._drop_working_cache()
                raise
            finally:
                self._active_prepare_task = None
            self._schedule_working_cache_expiry()
            return prepared

    async def aclose(self) -> None:
        """Stop active preparation and its descendants without waiting for its job deadline."""

        already_closing = self._closed
        self._closed = True
        task = self._active_prepare_task
        if task is not None and not task.done():
            if not already_closing and not task.cancelling():
                # Concurrent close callers join the same cleanup; another
                # cancellation must not interrupt process-group termination.
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    raise
        async with self._lock:
            expiry = self._working_cache_expiry_task
            self._drop_working_cache()
            if expiry is not None:
                try:
                    await expiry
                except asyncio.CancelledError:
                    pass
            if self._termination_failed:
                raise ImageWorkerError("image worker could not be terminated")

    def _working_cache_for(self, source: Path, model: PrinterModel) -> WorkingImageCache | None:
        if self._working_cache_ttl_s <= 0 or source.suffix.lower() not in HEIF_SUFFIXES:
            self._drop_working_cache()
            return None
        try:
            identity = source_identity(source)
        except OSError:
            self._drop_working_cache()
            return None
        spec = spec_for(model)
        key = (identity, model, _working_size_for_model(spec.width, spec.height))
        if key != self._working_cache_key:
            self._drop_working_cache()
            try:
                directory = TemporaryDirectory(prefix="instantlink-bridge-working-")
            except OSError:
                LOGGER.debug("image.working_cache_unavailable", exc_info=True)
                return None
            self._working_cache_dir = directory
            self._working_cache_key = key
            self._working_cache = WorkingImageCache(
                Path(directory.name) / "working.bmp", identity, model
            )
        return self._working_cache

    def _schedule_working_cache_expiry(self) -> None:
        if self._working_cache is None:
            return
        if self._working_cache_expiry_task is not None:
            self._working_cache_expiry_task.cancel()
        self._working_cache_expiry_task = asyncio.create_task(self._expire_working_cache())

    async def _expire_working_cache(self) -> None:
        await asyncio.sleep(self._working_cache_ttl_s)
        async with self._lock:
            self._drop_working_cache()

    def _drop_working_cache(self) -> None:
        expiry = self._working_cache_expiry_task
        self._working_cache_expiry_task = None
        if expiry is not None and expiry is not asyncio.current_task():
            expiry.cancel()
        directory = self._working_cache_dir
        self._working_cache_dir = None
        self._working_cache = None
        self._working_cache_key = None
        if directory is not None:
            try:
                directory.cleanup()
            except OSError:
                LOGGER.debug("image.working_cache_cleanup_failed", exc_info=True)

    async def _prepare_locked(
        self,
        request: ImagePreparationRequest,
        timeout_s: float | None,
    ) -> PreparedImage:
        handle = self._process_factory(request)
        process = handle.process
        self._active_process = process
        started = False
        terminated = False

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
                terminated = await self._terminate_process(
                    process, isolated_process_group=handle.isolated_process_group
                )
                if not terminated:
                    self._termination_failed = True
                    raise ImageWorkerError(
                        "image worker could not be terminated after timeout"
                    ) from error
                raise ImagePreparationTimeoutError(
                    f"image preparation timed out after {timeout_s:.2f}s"
                ) from error
        except asyncio.CancelledError:
            terminated = await self._terminate_process(
                process, isolated_process_group=handle.isolated_process_group
            )
            if not terminated:
                self._termination_failed = True
            raise
        finally:
            if started:
                await self._finalize_process(
                    process, isolated_process_group=handle.isolated_process_group and not terminated
                )
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

    async def _finalize_process(
        self, process: _ManagedProcess, *, isolated_process_group: bool = False
    ) -> None:
        group_cleaned = False
        if process.is_alive():
            exited = await self._wait_for_exit(process, self._shutdown_grace_s)
            if not exited:
                terminated = await self._terminate_process(
                    process, isolated_process_group=isolated_process_group
                )
                if not terminated:
                    self._termination_failed = True
                    return
                group_cleaned = True
        if isolated_process_group and not group_cleaned:
            _kill_isolated_process_group(process.pid)
        process.join(0.0)
        _close_quietly(process)

    async def _terminate_process(
        self, process: _ManagedProcess, *, isolated_process_group: bool = False
    ) -> bool:
        if not process.is_alive():
            if isolated_process_group:
                _kill_isolated_process_group(process.pid)
            process.join(0.0)
            return True

        group_id: int | None = None
        if isolated_process_group and process.pid is not None:
            try:
                # The child creates its session before decoding/spawning. If
                # cancelled before that point, terminate only the worker; never
                # signal the Bridge's own inherited process group.
                if os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGTERM)
                    group_id = process.pid
            except ProcessLookupError:
                pass
        if group_id is None:
            process.terminate()
        exited = await self._wait_for_exit(process, self._shutdown_grace_s)
        if group_id is not None:
            # A decoder can outlive its Python parent or ignore TERM. Always
            # finish the isolated group before another preparation can begin.
            try:
                os.killpg(group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if exited:
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


def _kill_isolated_process_group(pid: int | None) -> None:
    """Stop descendants even after their isolated worker parent has exited.

    A child cancelled before setsid still belongs to the Bridge group, whose
    id differs from its own pid. Targeting only the worker pid can never hit
    that inherited group; a missing worker-owned group is a harmless no-op.
    """
    if pid is None or pid == os.getpgrp():
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


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
    adjustments: AdjustmentProfile | None = None,
    correction: CorrectionProfile | None = None,
    timeout_s: float | None = None,
    worker: ImagePreparationWorker | None = None,
    apply_model_flip: bool = True,
) -> PreparedImage:
    """Prepare an image with the default killable process worker.

    ``apply_model_flip=False`` selects the InstantLink-backend flavour: the
    model transport flip is left to InstantLink, so the result is the upright
    image and is byte-identical to what the print path would build for itself
    (plan 056 T1.1).
    """

    image_worker = worker or default_image_preparation_worker()
    return await image_worker.prepare(
        source_path,
        model,
        fit=fit,
        quality=quality,
        edit=edit,
        adjustments=adjustments,
        correction=correction,
        timeout_s=timeout_s,
        apply_model_flip=apply_model_flip,
    )


def _create_process(request: ImagePreparationRequest) -> _WorkerHandle:
    # Imported here rather than at module scope (plan 056 T1.5): ~25 ms of
    # boot-path import cost for a module only needed once a job actually runs.
    import multiprocessing

    receive_connection, send_connection = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(
        target=_run_isolated_prepare_in_child,
        args=(send_connection, request),
        daemon=True,
    )
    return _WorkerHandle(
        process=cast(_ManagedProcess, process),
        result_reader=cast(_ResultReader, receive_connection),
        parent_writer=cast(_Closable, send_connection),
        isolated_process_group=os.name == "posix",
    )


def _run_isolated_prepare_in_child(
    result_writer: Connection,
    request: ImagePreparationRequest,
) -> None:
    if os.name == "posix":
        os.setsid()
    _run_prepare_in_child(result_writer, request)


def _run_prepare_in_child(
    result_writer: Connection,
    request: ImagePreparationRequest,
) -> None:
    try:
        prepared = prepare_for_instantlink_backend(
            request.source_path,
            request.model,
            fit=request.fit,
            quality=request.quality,
            edit=request.edit,
            adjustments=request.adjustments,
            correction=request.correction,
            working_cache=request.working_cache,
            apply_model_flip=request.apply_model_flip,
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
