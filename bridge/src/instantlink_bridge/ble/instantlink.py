"""InstantLink-backed printer transport.

The Python Bleak transport remains in the tree as a fallback, but hardware testing showed that
BlueZ/Bleak can see some Instax Link printers and still disconnect during service discovery.
InstantLink's Rust backend uses btleplug and is the authoritative implementation for printer
connection, model detection, status, and print transfer.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import platform
import re
import tempfile
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TypeVar

from instantlink_bridge.ble.instax import (
    CoverOpenError,
    LowPrinterBatteryError,
    NoFilmError,
    PrinterBusyError,
    PrintRejectedError,
)
from instantlink_bridge.ble.models import PrinterModel, spec_for
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    ImagePipelineError,
    PreparedImage,
    PrintEdit,
    prepare_for_instantlink_backend,
)
from instantlink_bridge.imaging.postprocess import AdjustmentProfile, CorrectionProfile
from instantlink_bridge.printing import PrintProgress, PrintProgressCallback, PrintStage

LOGGER = logging.getLogger(__name__)

ERROR_PRINTER_NOT_FOUND = -1
ERROR_MULTIPLE_PRINTERS = -2
ERROR_BLE = -3
ERROR_TIMEOUT = -4
ERROR_INVALID_ARGUMENT = -5
ERROR_IMAGE = -6
ERROR_PRINT_REJECTED = -7
ERROR_NO_FILM = -8
ERROR_LOW_BATTERY = -9
ERROR_COVER_OPEN = -10
ERROR_PRINTER_BUSY = -11

INSTANTLINK_FIT_CROP = 0
INSTANTLINK_FIT_CONTAIN = 1
INSTANTLINK_FIT_STRETCH = 2
PREPARED_MODEL_CODES = {
    PrinterModel.MINI: 0,
    PrinterModel.MINI_LINK3: 1,
    PrinterModel.SQUARE: 2,
    PrinterModel.WIDE: 3,
}
DEFAULT_SCAN_DURATION_S = 5
STRING_BUFFER_SIZE = 4096
FFI_CANCEL_GRACE_S = 5.0
STATUS_FAILURE_LOG_INTERVAL_S = 30.0

_PRINT_PROGRESS_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32)
_CONNECT_PROGRESS_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_char_p)
CONNECT_STAGE_NAMES = {
    0: "scan_started",
    1: "scan_finished",
    2: "device_matched",
    3: "ble_connecting",
    4: "service_discovery",
    5: "characteristic_lookup",
    6: "notification_subscribe",
    7: "model_detecting",
    8: "status_fetching",
    9: "connected",
    10: "failed",
}
# Named connect milestone: the encrypted notify subscription succeeded.
CONNECT_STAGE_NOTIFICATION_SUBSCRIBE = 6
# Earliest phase used by the stale-key recovery heuristic. Modern native builds distinguish
# confirmed resolved-table characteristic absence from uncertain readiness and dropped links;
# terminal detail excludes the latter before this phase gate. Legacy builds retain phase-based
# behavior. Confirmed missing encrypted characteristics or encrypted subscription/write failures
# still qualify for the existing bounded bond recovery.
CONNECT_STAGE_STALE_BOND_MIN = 5
# Consecutive status failures that mean the cached BLE link is dead (not a one-off hiccup),
# after which the connection is torn down so the next poll does a fresh connect (which can
# re-establish the link and trigger auto-rebond). Tolerates a single transient failure to
# avoid needless reconnect churn; the persistent btleplug Manager means reconnects don't leak.
STALE_LINK_STATUS_FAILURE_THRESHOLD = 2
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class InstantLinkStatus:
    """Status returned by the InstantLink backend."""

    name: str
    model: PrinterModel
    battery: int
    film_remaining: int
    is_charging: bool
    print_count: int | None


class InstantLinkError(RuntimeError):
    """Base error for the InstantLink backend."""

    def __init__(self, message: str, *, code: int) -> None:
        super().__init__(message)
        self.code = code
        # Highest connect-progress stage observed during the in-flight connect attempt that
        # produced this error, when known. ``None`` means the error did not originate from a
        # connect attempt (e.g. a status read on an already-established link).
        self.connect_failure_stage: int | None = None
        # Native terminal progress carries the actual setup error; the C ABI return code alone
        # cannot distinguish unresolved GATT from a confirmed encrypted-characteristic failure.
        self.connect_failure_detail: str | None = None


class InstantLinkLibraryUnavailableError(InstantLinkError):
    """Raised when the Rust FFI library is not installed."""


class InstantLinkPrinterNotFoundError(InstantLinkError):
    """Raised when InstantLink cannot find the selected printer."""


class InstantLinkMultiplePrintersError(InstantLinkError):
    """Raised when InstantLink finds multiple possible printers."""


class InstantLinkBleError(InstantLinkError):
    """Raised for BLE transport errors reported by InstantLink."""


class InstantLinkInvalidArgumentError(InstantLinkError):
    """Raised when InstantLink Bridge passes invalid data to the FFI layer."""


_DEFAULT_BACKEND: InstantLinkBackend | None = None


def instantlink_backend_enabled() -> bool:
    """Return whether the InstantLink backend should be used by default."""

    backend = os.environ.get("INSTANTLINK_BRIDGE_PRINTER_BACKEND", "instantlink")
    return backend.strip().casefold() in {
        "",
        "instantlink",
        "rust",
    }


def default_instantlink_backend() -> InstantLinkBackend:
    """Return the process-wide InstantLink backend wrapper."""

    global _DEFAULT_BACKEND
    if _DEFAULT_BACKEND is None:
        _DEFAULT_BACKEND = InstantLinkBackend()
    return _DEFAULT_BACKEND


def prepared_jpeg_available() -> bool:
    """Report a loaded native capability without loading FFI or touching BLE.

    Printer status normally loads the library before uploads become ready.
    Earlier callers safely prepare the legacy flavor; printing rechecks the
    actual loaded library and rebuilds an incompatible orientation if needed.
    """
    return (
        instantlink_backend_enabled()
        and _DEFAULT_BACKEND is not None
        and _DEFAULT_BACKEND.prepared_jpeg_available()
    )


async def close_default_instantlink_backend() -> None:
    """Disconnect the process-wide InstantLink backend, if loaded."""

    if _DEFAULT_BACKEND is not None:
        await _DEFAULT_BACKEND.disconnect()


def stable_instantlink_address(name: str) -> str:
    """Return a stable pseudo-address for a printer selected by InstantLink."""

    normalized = normalize_printer_name(name)
    serial = _extract_serial(normalized)
    return f"instantlink:{serial or normalized}".upper()


def normalize_printer_name(name: str) -> str:
    """Strip platform suffixes from an Instax advertising name."""

    return re.sub(r"\s*\((IOS|ANDROID)\)$", "", name.strip(), flags=re.IGNORECASE).strip()


async def scan_instax_printers(timeout_s: float = DEFAULT_SCAN_DURATION_S) -> list[str]:
    """Scan for nearby Instax printer names through InstantLink."""

    return await default_instantlink_backend().scan(timeout_s)


async def print_file_to_printer(
    address: str,
    image_path: Path,
    *,
    name: str | None = None,
    fit: FitMode = FitMode.AUTO,
    quality: int = 100,
    edit: PrintEdit | None = None,
    print_option: int = 0,
    model: PrinterModel | None = None,
    progress: PrintProgressCallback | None = None,
    adjustments: AdjustmentProfile | None = None,
    correction: CorrectionProfile | None = None,
    prepared_image: PreparedImage | None = None,
    preparation_model_hint: PrinterModel | None = None,
) -> None:
    """Print a file through InstantLink's Rust transport.

    ``prepared_image`` lets a caller that has already built the model-sized
    JPEG — the LCD preview does — skip the pipeline entirely (plan 056 T1.1).
    It is used only when its model matches the printer detected on connect.
    """

    _ = address
    await default_instantlink_backend().print_file(
        name or _name_from_address(address),
        image_path,
        fit=fit,
        quality=quality,
        edit=edit,
        print_option=print_option,
        model_override=model,
        progress=progress,
        adjustments=adjustments,
        correction=correction,
        prepared_image=prepared_image,
        preparation_model_hint=preparation_model_hint,
    )


class InstantLinkBackend:
    """Async wrapper around InstantLink's synchronous C FFI."""

    def __init__(self, library_path: Path | None = None) -> None:
        self._library_path = library_path
        self._lib: ctypes.CDLL | None = None
        self._lock = asyncio.Lock()
        self._last_status_failure_log_at = -float("inf")
        self._last_status_failure_signature: tuple[str, str, str, bool] | None = None
        self._consecutive_status_failures = 0

    def prepared_jpeg_available(self) -> bool:
        """Read the optional export from an already loaded library only."""
        return self._lib is not None and hasattr(
            self._lib, "instantlink_print_prepared_jpeg_with_progress"
        )

    async def scan(self, timeout_s: float = DEFAULT_SCAN_DURATION_S) -> list[str]:
        """Return normalized visible Instax printer names."""

        return await self._run_blocking_serialized(
            "scan",
            partial(self._scan_blocking, timeout_s),
        )

    async def status(
        self,
        name: str,
        *,
        scan_duration_s: int = DEFAULT_SCAN_DURATION_S,
    ) -> InstantLinkStatus:
        """Connect if needed and return current printer status."""

        return await self._run_blocking_serialized(
            "status",
            partial(self._status_blocking, name, scan_duration_s),
        )

    async def print_file(
        self,
        name: str,
        image_path: Path,
        *,
        fit: FitMode = FitMode.AUTO,
        quality: int = 100,
        edit: PrintEdit | None = None,
        print_option: int = 0,
        model_override: PrinterModel | None = None,
        progress: PrintProgressCallback | None = None,
        adjustments: AdjustmentProfile | None = None,
        correction: CorrectionProfile | None = None,
        prepared_image: PreparedImage | None = None,
        preparation_model_hint: PrinterModel | None = None,
    ) -> None:
        """Prepare an edited image and send it through InstantLink."""

        await self._run_blocking_serialized(
            "print",
            partial(
                self._print_file_blocking,
                name,
                image_path,
                fit,
                quality,
                edit,
                print_option,
                model_override,
                progress,
                adjustments,
                correction,
                prepared_image,
                preparation_model_hint,
            ),
        )

    async def disconnect(self) -> None:
        """Disconnect the current InstantLink device."""

        await self._run_blocking_serialized("disconnect", self._disconnect_blocking)

    async def configure_keepalive(self, interval_s: float | None) -> None:
        """Configure InstantLink core's background keepalive loop."""

        await self._run_blocking_serialized(
            "configure_keepalive",
            partial(self._configure_keepalive_blocking, interval_s),
        )

    async def keepalive_once(self) -> None:
        """Send one explicit InstantLink keepalive/status request."""

        await self._run_blocking_serialized("keepalive", self._keepalive_blocking)

    async def _run_blocking_serialized(self, operation: str, worker: Callable[[], _T]) -> _T:
        """Run one synchronous FFI call while preserving serialization through cancellation."""

        async with self._lock:
            task = asyncio.ensure_future(asyncio.to_thread(worker))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                LOGGER.warning("instantlink.%s_cancel_waiting_for_worker", operation)
                loop = asyncio.get_running_loop()
                deadline = loop.time() + FFI_CANCEL_GRACE_S
                while not task.done():
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(task), timeout=max(0.0, deadline - loop.time())
                        )
                    except asyncio.CancelledError:
                        # Retain the Printer lock through repeated cancellation,
                        # without granting the blocking call a fresh grace period.
                        continue
                    except TimeoutError:
                        if task.done():
                            # The worker's own TimeoutError is a completed
                            # failure, not expiration of the cleanup deadline.
                            break
                        LOGGER.critical(
                            "instantlink.%s_cancel_worker_stuck restarting_process grace_s=%.1f",
                            operation,
                            FFI_CANCEL_GRACE_S,
                        )
                        os._exit(1)
                    except Exception:
                        # Consume a completed worker failure without replacing
                        # the caller's cancellation with an obsolete result.
                        break
                # Retrieve completion (including a worker failure) before releasing
                # the serialization lock and propagating the caller's cancellation.
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        LOGGER.debug(
                            "instantlink.%s_cancel_worker_failed error_type=%s",
                            operation,
                            type(error).__name__,
                        )
                raise

    def _scan_blocking(self, timeout_s: float) -> list[str]:
        duration = max(1, round(timeout_s))
        buf = ctypes.create_string_buffer(STRING_BUFFER_SIZE)
        rc = int(self._library().instantlink_scan(duration, buf, len(buf)))
        if rc < 0:
            _raise_for_code(rc, "scan failed")
        raw_json = bytes(buf.value).decode("utf-8", errors="replace")
        try:
            values = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise InstantLinkBleError("scan returned invalid JSON", code=ERROR_BLE) from exc
        if not isinstance(values, list):
            raise InstantLinkBleError("scan returned non-list JSON", code=ERROR_BLE)
        names = [
            normalize_printer_name(value)
            for value in values
            if isinstance(value, str) and value.strip() and not _is_android_advertisement(value)
        ]
        return _dedupe_names(names)

    def _status_blocking(self, name: str, scan_duration_s: int) -> InstantLinkStatus:
        try:
            status = self._status_blocking_connected(name, scan_duration_s)
            self._clear_status_failure_log_state()
            self._consecutive_status_failures = 0
            return status
        except (InstantLinkBleError, InstantLinkPrinterNotFoundError, TimeoutError) as exc:
            # Persistent-connection policy: keep the cached link across a single transient
            # read/timeout so we don't pay a full scan + reconnect every tick. But a link
            # that keeps failing is dead (e.g. the printer slept and dropped BLE), so after
            # a few consecutive failures we MUST tear it down — otherwise we'd retry status
            # on a dead handle forever and never reconnect (or trigger auto-rebond).
            self._consecutive_status_failures += 1
            disconnect = self._should_disconnect_on_status_error(
                exc, self._consecutive_status_failures
            )
            self._log_status_failure(name, exc, disconnected=disconnect)
            if disconnect:
                self._disconnect_blocking()
                self._consecutive_status_failures = 0
            raise

    def _should_disconnect_on_status_error(
        self, exc: BaseException, consecutive_failures: int
    ) -> bool:
        """Decide whether to drop the cached connection after a status error.

        Tear down when the printer is genuinely gone (``InstantLinkPrinterNotFoundError``),
        the native session is known closed, or the link has failed on
        ``STALE_LINK_STATUS_FAILURE_THRESHOLD`` consecutive
        attempts (a dead link, not a one-off hiccup). A single transient
        ``InstantLinkBleError`` / ``TimeoutError`` keeps the connection so the next poll
        reuses the live link; persistent failures force a fresh reconnect.
        """

        if isinstance(exc, InstantLinkPrinterNotFoundError):
            return True
        if self._native_connection_known_closed():
            return True
        return consecutive_failures >= STALE_LINK_STATUS_FAILURE_THRESHOLD

    def _native_connection_known_closed(self) -> bool:
        is_connected = getattr(self._library(), "instantlink_is_connected", None)
        return is_connected is not None and int(is_connected()) == 0

    def _log_status_failure(self, name: str, exc: BaseException, *, disconnected: bool) -> None:
        normalized_name = normalize_printer_name(name)
        event = "status_failed_disconnect" if disconnected else "status_failed_keep_connection"
        signature = (normalized_name, type(exc).__name__, str(exc), disconnected)
        expected_absence = isinstance(exc, InstantLinkPrinterNotFoundError)
        now = time.monotonic()
        if signature != self._last_status_failure_signature or (
            not expected_absence
            and now - self._last_status_failure_log_at >= STATUS_FAILURE_LOG_INTERVAL_S
        ):
            LOGGER.log(
                logging.INFO if expected_absence else logging.WARNING,
                "instantlink.%s name=%s error_type=%s error=%s",
                event,
                normalized_name,
                type(exc).__name__,
                exc,
            )
            LOGGER.debug("instantlink.%s_trace", event, exc_info=True)
            self._last_status_failure_signature = signature
            self._last_status_failure_log_at = now
        else:
            LOGGER.debug(
                "instantlink.%s_suppressed name=%s error_type=%s error=%s",
                event,
                normalized_name,
                type(exc).__name__,
                exc,
            )

    def _clear_status_failure_log_state(self) -> None:
        self._last_status_failure_signature = None
        self._last_status_failure_log_at = -float("inf")

    def _status_blocking_connected(self, name: str, scan_duration_s: int) -> InstantLinkStatus:
        initial_status = self._ensure_connected_blocking(
            name, scan_duration_s=scan_duration_s, read_initial_status=True
        )

        battery = ctypes.c_int()
        film = ctypes.c_int()
        charging = ctypes.c_int()
        print_count = ctypes.c_int()
        if initial_status is not None:
            # This snapshot belongs only to the fresh connection created by this worker.
            # Established sessions and every later poll still request current printer status.
            battery.value, film.value, charging.value, print_count.value = initial_status
        elif hasattr(self._library(), "instantlink_status"):
            rc = int(
                self._library().instantlink_status(
                    ctypes.byref(battery),
                    ctypes.byref(film),
                    ctypes.byref(charging),
                    ctypes.byref(print_count),
                )
            )
            if rc == ERROR_NO_FILM:
                battery.value = self._battery_value_for_no_film_status()
                film.value = 0
                charging.value = 0
                print_count.value = -1
            elif rc < 0:
                _raise_for_code(rc, "status failed")
        else:
            battery.value = self._battery_value_for_no_film_status()
            print_count.value = -1
            rc = int(
                self._library().instantlink_film_and_charging(
                    ctypes.byref(film),
                    ctypes.byref(charging),
                )
            )
            if rc == ERROR_NO_FILM:
                film.value = 0
                charging.value = 0
            elif rc < 0:
                _raise_for_code(rc, "status film failed")

        model = self._device_model_blocking()
        connected_name = self._device_name_blocking() or normalize_printer_name(name)
        return InstantLinkStatus(
            name=connected_name,
            model=model,
            battery=battery.value,
            film_remaining=film.value,
            is_charging=bool(charging.value),
            print_count=print_count.value if print_count.value >= 0 else None,
        )

    def _battery_value_for_no_film_status(self) -> int:
        battery_value = int(self._library().instantlink_battery())
        if battery_value < 0:
            _raise_for_code(battery_value, "status battery failed")
        return battery_value

    def _print_file_blocking(
        self,
        name: str,
        image_path: Path,
        fit: FitMode,
        quality: int,
        edit: PrintEdit | None,
        print_option: int,
        model_override: PrinterModel | None,
        progress: PrintProgressCallback | None,
        adjustments: AdjustmentProfile | None = None,
        correction: CorrectionProfile | None = None,
        prepared_image: PreparedImage | None = None,
        preparation_model_hint: PrinterModel | None = None,
    ) -> None:
        # Image prep needs no BLE link, so overlap it with the connect and
        # model query below — seconds of radio work (plan 056 T1.6). Only
        # speculate when a configured model or a cached detection hint is
        # available. A hint affects preparation only; detection still chooses
        # the actual output model and discards a mismatched preparation. Skip
        # speculation when a preview already supplied prepared bytes.
        speculative: Future[PreparedImage] | None = None
        prep_executor: ThreadPoolExecutor | None = None
        prepared_native = hasattr(self._library(), "instantlink_print_prepared_jpeg_with_progress")
        preparation_model = model_override or preparation_model_hint
        if prepared_image is None and preparation_model is not None:
            prep_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="instantlink-prep")
            speculative = prep_executor.submit(
                partial(
                    prepare_for_instantlink_backend,
                    image_path,
                    preparation_model,
                    fit=fit,
                    quality=quality,
                    edit=edit,
                    adjustments=adjustments,
                    correction=correction,
                    apply_model_flip=prepared_native,
                )
            )

        try:
            self._print_file_connected(
                name=name,
                image_path=image_path,
                fit=fit,
                quality=quality,
                edit=edit,
                print_option=print_option,
                model_override=model_override,
                progress=progress,
                adjustments=adjustments,
                correction=correction,
                prepared_image=prepared_image,
                speculative=speculative,
            )
        finally:
            if prep_executor is not None:
                # wait=True so a speculative prep can never outlive the print
                # and leak a worker into the next job.
                prep_executor.shutdown(wait=True)

    def _print_file_connected(
        self,
        *,
        name: str,
        image_path: Path,
        fit: FitMode,
        quality: int,
        edit: PrintEdit | None,
        print_option: int,
        model_override: PrinterModel | None,
        progress: PrintProgressCallback | None,
        adjustments: AdjustmentProfile | None,
        correction: CorrectionProfile | None,
        prepared_image: PreparedImage | None,
        speculative: Future[PreparedImage] | None,
    ) -> None:
        _emit_progress(
            progress,
            PrintProgress(PrintStage.CONNECTING, "Connecting", normalize_printer_name(name), None),
        )
        self._ensure_connected_blocking(name, scan_duration_s=DEFAULT_SCAN_DURATION_S)
        detected_model = self._device_model_blocking()
        prepared_native = hasattr(self._library(), "instantlink_print_prepared_jpeg_with_progress")
        model = (
            detected_model
            if prepared_native
            else _compatible_model_override(detected_model, model_override)
        )

        spec = spec_for(model)
        _emit_progress(
            progress,
            PrintProgress(PrintStage.PREPARING, "Preparing image", spec.name, None),
        )
        # A preview, when one was shown, has already built exactly this image
        # (plan 056 T1.1); failing that, a speculative prep may have run
        # alongside the connect (T1.6). Both build for the *configured* model,
        # which can disagree with the printer we actually detected, and models
        # differ in output dimensions — so both go through the same guard.
        prepared = prepared_image
        source = "preview"
        if prepared is None and speculative is not None:
            prepared = _speculative_prepared(speculative)
            source = "speculative"
        expected_flip = prepared_native and spec.flip_vertical
        if prepared is not None and (
            prepared.model is not model
            or prepared.transport_flip_applied != expected_flip
            or (prepared.width, prepared.height) != (spec.width, spec.height)
        ):
            LOGGER.info(
                "instantlink.prepared_discarded expected=%s prepared=%s source=%s",
                model.value,
                prepared.model.value,
                source,
            )
            prepared = None
        prepare_started = time.monotonic()
        if prepared is None:
            source = "inline"
            try:
                prepared = prepare_for_instantlink_backend(
                    image_path,
                    model,
                    fit=fit,
                    quality=quality,
                    edit=edit,
                    adjustments=adjustments,
                    correction=correction,
                    apply_model_flip=prepared_native,
                )
            except ImagePipelineError:
                raise
            except Exception as exc:
                raise ImagePipelineError("Image unsupported") from exc

        # source=preview means the LCD preview's image was reused and the
        # pipeline did not run again; speculative means it ran alongside the
        # BLE connect; inline means it ran here on the critical path
        # (plan 056 T1.1/T1.6). prepare_ms is ~0 for anything but inline.
        LOGGER.info(
            "instantlink.image_prepared source=%s model=%s bytes=%d quality=%d prepare_ms=%.0f",
            source,
            prepared.model.value,
            len(prepared.data),
            prepared.quality,
            (time.monotonic() - prepare_started) * 1000,
        )

        _emit_progress(
            progress,
            PrintProgress(
                PrintStage.SENDING,
                "Sending to printer",
                f"{len(prepared.data) // 1024} KB",
                0,
            ),
        )
        callback = _print_progress_callback(progress, len(prepared.data))
        if prepared_native:
            # Both locals remain strongly referenced until the synchronous
            # native call returns. Embedded NUL bytes are ordinary JPEG data;
            # the explicit length, not C-string termination, bounds the input.
            buffer = (ctypes.c_uint8 * len(prepared.data)).from_buffer_copy(prepared.data)
            rc = int(
                self._library().instantlink_print_prepared_jpeg_with_progress(
                    buffer,
                    ctypes.c_uint32(len(prepared.data)),
                    ctypes.c_uint8(PREPARED_MODEL_CODES[prepared.model]),
                    ctypes.c_uint8(int(prepared.transport_flip_applied)),
                    ctypes.c_uint8(max(0, min(255, print_option))),
                    callback,
                )
            )
        else:
            rc = self._send_legacy_prepared(prepared, print_option, callback)
        if rc < 0:
            _raise_for_code(rc, "print failed")
        _emit_progress(
            progress,
            PrintProgress(PrintStage.FINISHING, "Finishing", "Waiting for printer", 100),
        )

    def _send_legacy_prepared(
        self,
        prepared: PreparedImage,
        print_option: int,
        callback: Callable[[int, int], None],
    ) -> int:
        """Use the older file API with logical pixels and its existing encode quality."""
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="instantlink-bridge-instantlink-", suffix=".jpg", delete=False
            ) as temp_file:
                temp_file.write(prepared.data)
                temp_path = Path(temp_file.name)
            return int(
                self._library().instantlink_print_with_progress(
                    str(temp_path).encode("utf-8"),
                    ctypes.c_uint8(max(1, min(100, prepared.quality))),
                    ctypes.c_uint8(INSTANTLINK_FIT_STRETCH),
                    ctypes.c_uint8(max(0, min(255, print_option))),
                    callback,
                )
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _ensure_connected_blocking(
        self,
        name: str,
        *,
        scan_duration_s: int,
        read_initial_status: bool = False,
    ) -> tuple[int, int, int, int] | None:
        target_name = _connect_target_name(name)
        connected_name = self._device_name_blocking()
        if connected_name is not None and _printer_names_match(connected_name, target_name):
            # New native builds report terminal session state without a hardware query; older
            # ones report cached presence. Only a confirmed closure retires a reusable session.
            if not self._native_connection_known_closed():
                return None
            self._disconnect_blocking()
        stage_tracker = _ConnectStageTracker()
        initial_status: tuple[int, int, int, int] | None = None
        connect_with_status = getattr(
            self._library(), "instantlink_connect_named_with_status", None
        )
        if read_initial_status and connect_with_status is not None:
            battery, film, charging, print_count = (ctypes.c_int() for _ in range(4))
            callback = _connect_progress_logger(target_name, stage_tracker)
            rc = int(
                connect_with_status(
                    target_name.encode("utf-8"),
                    max(1, scan_duration_s),
                    callback,
                    ctypes.byref(battery),
                    ctypes.byref(film),
                    ctypes.byref(charging),
                    ctypes.byref(print_count),
                )
            )
            if rc >= 0:
                initial_status = battery.value, film.value, charging.value, print_count.value
        else:
            rc = self._connect_named_blocking(target_name, scan_duration_s, stage_tracker)
        if rc < 0:
            try:
                _raise_for_code(rc, "connect failed")
            except InstantLinkError as exc:
                # Carry the current attempt's phase and terminal detail so readiness uncertainty
                # cannot masquerade as a confirmed encrypted-characteristic failure.
                exc.connect_failure_stage = stage_tracker.max_stage
                exc.connect_failure_detail = stage_tracker.failure_detail
                raise
        # The new session must not inherit a transient failure streak from the previous link.
        self._consecutive_status_failures = 0
        return initial_status

    def _connect_named_blocking(
        self,
        target_name: str,
        scan_duration_s: int,
        stage_tracker: _ConnectStageTracker | None = None,
    ) -> int:
        library = self._library()
        duration = max(1, scan_duration_s)
        if hasattr(library, "instantlink_connect_named_with_progress"):
            callback = _connect_progress_logger(target_name, stage_tracker)
            return int(
                library.instantlink_connect_named_with_progress(
                    target_name.encode("utf-8"),
                    duration,
                    callback,
                )
            )
        return int(library.instantlink_connect_named(target_name.encode("utf-8"), duration))

    def _device_name_blocking(self) -> str | None:
        return self._string_result("instantlink_device_name", missing_ok=True)

    def _device_model_blocking(self) -> PrinterModel:
        model = self._string_result("instantlink_device_model", missing_ok=False)
        if model is None:
            raise InstantLinkPrinterNotFoundError("printer is not connected", code=-1)
        return _parse_instantlink_model(model)

    def _disconnect_blocking(self) -> None:
        if self._lib is None:
            return
        rc = int(self._library().instantlink_disconnect())
        if rc in {0, ERROR_PRINTER_NOT_FOUND}:
            return
        LOGGER.warning("instantlink.disconnect_failed code=%s", rc)

    def _configure_keepalive_blocking(self, interval_s: float | None) -> None:
        library = self._library()
        configure = getattr(library, "instantlink_set_keepalive_interval", None)
        if configure is None:
            LOGGER.debug("instantlink.keepalive_config_unsupported")
            return
        seconds = 0 if interval_s is None or interval_s <= 0 else max(1, round(interval_s))
        rc = int(configure(seconds))
        if rc < 0:
            _raise_for_code(rc, "set keepalive failed")
        LOGGER.info("instantlink.keepalive_configured interval_s=%s", seconds)

    def _keepalive_blocking(self) -> None:
        library = self._library()
        keepalive = getattr(library, "instantlink_keepalive", None)
        if keepalive is None:
            LOGGER.debug("instantlink.keepalive_unsupported")
            return
        rc = int(keepalive())
        if rc < 0:
            _raise_for_code(rc, "keepalive failed")

    def _string_result(self, function_name: str, *, missing_ok: bool) -> str | None:
        buf = ctypes.create_string_buffer(STRING_BUFFER_SIZE)
        fn = getattr(self._library(), function_name)
        rc = int(fn(buf, len(buf)))
        if rc == ERROR_PRINTER_NOT_FOUND and missing_ok:
            return None
        if rc < 0:
            _raise_for_code(rc, f"{function_name} failed")
        return bytes(buf.value).decode("utf-8", errors="replace").strip() or None

    def _library(self) -> ctypes.CDLL:
        if self._lib is None:
            self._lib = _load_library(self._library_path)
        return self._lib


def _print_progress_callback(
    progress: PrintProgressCallback | None,
    image_size: int,
) -> Callable[[int, int], None]:
    last_percent = -5

    def emit(done: int, total: int) -> None:
        nonlocal last_percent
        if total <= 0:
            return
        percent = min(100, max(0, int(done * 100 / total)))
        if percent < 100 and percent < last_percent + 5:
            return
        last_percent = percent
        _emit_progress(
            progress,
            PrintProgress(
                PrintStage.SENDING,
                f"Sending {percent}%",
                # detail = None: chunk count + KB size dropped per user
                # request; the progress bar carries the full signal.
                None,
                percent,
            ),
        )

    return _PRINT_PROGRESS_CALLBACK(emit)


def _emit_progress(progress: PrintProgressCallback | None, update: PrintProgress) -> None:
    if progress is not None:
        progress(update)


def _load_library(library_path: Path | None) -> ctypes.CDLL:
    candidates = list(_candidate_library_paths(library_path))
    for candidate in candidates:
        if not candidate.exists():
            continue
        lib = ctypes.CDLL(str(candidate))
        _configure_library(lib)
        lib.instantlink_init()
        LOGGER.info("instantlink.library_loaded path=%s", candidate)
        return lib
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise InstantLinkLibraryUnavailableError(
        f"InstantLink backend library is not installed; searched {searched}",
        code=ERROR_BLE,
    )


def _candidate_library_paths(library_path: Path | None) -> Iterable[Path]:
    if library_path is not None:
        yield library_path
        return
    env_path = os.environ.get("INSTANTLINK_BRIDGE_INSTANTLINK_LIB")
    if env_path:
        yield Path(env_path)
    system = platform.system()
    file_name = "libinstantlink_ffi.dylib" if system == "Darwin" else "libinstantlink_ffi.so"
    bridge_root = Path(__file__).resolve().parents[3]
    workspace_root = bridge_root.parent
    yield Path("/opt/InstantLinkBridge/lib") / file_name
    yield bridge_root / "lib" / file_name
    yield workspace_root / "target" / "release" / file_name
    yield workspace_root / "target" / "aarch64-unknown-linux-gnu" / "release" / file_name


def _configure_library(lib: ctypes.CDLL) -> None:
    lib.instantlink_init.argtypes = []
    lib.instantlink_init.restype = None
    lib.instantlink_scan.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.instantlink_scan.restype = ctypes.c_int
    lib.instantlink_connect_named.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.instantlink_connect_named.restype = ctypes.c_int
    if hasattr(lib, "instantlink_connect_named_with_progress"):
        lib.instantlink_connect_named_with_progress.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            _CONNECT_PROGRESS_CALLBACK,
        ]
        lib.instantlink_connect_named_with_progress.restype = ctypes.c_int
    if hasattr(lib, "instantlink_connect_named_with_status"):
        lib.instantlink_connect_named_with_status.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            _CONNECT_PROGRESS_CALLBACK,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.instantlink_connect_named_with_status.restype = ctypes.c_int
    lib.instantlink_disconnect.argtypes = []
    lib.instantlink_disconnect.restype = ctypes.c_int
    if hasattr(lib, "instantlink_is_connected"):
        lib.instantlink_is_connected.argtypes = []
        lib.instantlink_is_connected.restype = ctypes.c_int
    lib.instantlink_status.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.instantlink_status.restype = ctypes.c_int
    lib.instantlink_battery.argtypes = []
    lib.instantlink_battery.restype = ctypes.c_int
    lib.instantlink_film_and_charging.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.instantlink_film_and_charging.restype = ctypes.c_int
    if hasattr(lib, "instantlink_keepalive"):
        lib.instantlink_keepalive.argtypes = []
        lib.instantlink_keepalive.restype = ctypes.c_int
    if hasattr(lib, "instantlink_set_keepalive_interval"):
        lib.instantlink_set_keepalive_interval.argtypes = [ctypes.c_int]
        lib.instantlink_set_keepalive_interval.restype = ctypes.c_int
    lib.instantlink_device_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.instantlink_device_name.restype = ctypes.c_int
    lib.instantlink_device_model.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.instantlink_device_model.restype = ctypes.c_int
    lib.instantlink_print_with_progress.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint8,
        ctypes.c_uint8,
        ctypes.c_uint8,
        _PRINT_PROGRESS_CALLBACK,
    ]
    lib.instantlink_print_with_progress.restype = ctypes.c_int
    if hasattr(lib, "instantlink_print_prepared_jpeg_with_progress"):
        lib.instantlink_print_prepared_jpeg_with_progress.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_uint32,
            ctypes.c_uint8,
            ctypes.c_uint8,
            ctypes.c_uint8,
            _PRINT_PROGRESS_CALLBACK,
        ]
        lib.instantlink_print_prepared_jpeg_with_progress.restype = ctypes.c_int


def _raise_for_code(code: int, context: str) -> None:
    if code == ERROR_PRINTER_NOT_FOUND:
        raise InstantLinkPrinterNotFoundError(f"{context}: printer not found", code=code)
    if code == ERROR_MULTIPLE_PRINTERS:
        raise InstantLinkMultiplePrintersError(f"{context}: multiple printers found", code=code)
    if code == ERROR_BLE:
        raise InstantLinkBleError(f"{context}: BLE communication failed", code=code)
    if code == ERROR_TIMEOUT:
        raise TimeoutError(context)
    if code == ERROR_INVALID_ARGUMENT:
        raise InstantLinkInvalidArgumentError(f"{context}: invalid argument", code=code)
    if code == ERROR_IMAGE:
        raise ImagePipelineError("Image unsupported")
    if code == ERROR_NO_FILM:
        raise NoFilmError("no film remaining")
    if code == ERROR_LOW_BATTERY:
        raise LowPrinterBatteryError("printer battery too low")
    if code == ERROR_COVER_OPEN:
        raise CoverOpenError("printer cover is open")
    if code == ERROR_PRINTER_BUSY:
        raise PrinterBusyError("printer is busy")
    if code == ERROR_PRINT_REJECTED:
        if context.startswith("print"):
            raise PrintRejectedError("print rejected")
        raise InstantLinkBleError(f"{context}: unexpected printer response", code=code)
    raise InstantLinkError(f"{context}: InstantLink error {code}", code=code)


def _parse_instantlink_model(value: str) -> PrinterModel:
    normalized = value.casefold()
    if "mini link 3" in normalized or "minilink3" in normalized:
        return PrinterModel.MINI_LINK3
    if "square" in normalized:
        return PrinterModel.SQUARE
    if "wide" in normalized:
        return PrinterModel.WIDE
    if "mini" in normalized:
        return PrinterModel.MINI
    raise InstantLinkBleError(f"unknown InstantLink model string: {value}", code=ERROR_BLE)


def _speculative_prepared(future: Future[PreparedImage]) -> PreparedImage | None:
    """Return the speculative prep result, or ``None`` if it failed.

    A speculative failure must never be the error the user sees: returning
    ``None`` falls through to the synchronous prepare, which raises the
    authoritative ``ImagePipelineError`` with the normal handling around it
    (plan 056 T1.6).
    """

    try:
        return future.result()
    except Exception:
        LOGGER.debug("instantlink.speculative_prepare_failed", exc_info=True)
        return None


def _compatible_model_override(
    detected_model: PrinterModel,
    model_override: PrinterModel | None,
) -> PrinterModel:
    if model_override is None or model_override is detected_model:
        return detected_model
    detected_spec = spec_for(detected_model)
    override_spec = spec_for(model_override)
    if (detected_spec.width, detected_spec.height) == (override_spec.width, override_spec.height):
        LOGGER.info(
            "instantlink.model_override detected=%s override=%s",
            detected_model.value,
            model_override.value,
        )
        return model_override
    LOGGER.warning(
        "instantlink.model_override_ignored detected=%s override=%s",
        detected_model.value,
        model_override.value,
    )
    return detected_model


def _printer_names_match(left: str, right: str) -> bool:
    left_normalized = normalize_printer_name(left).casefold()
    right_normalized = normalize_printer_name(right).casefold()
    if left_normalized == right_normalized:
        return True
    left_serial = _extract_serial(left_normalized)
    right_serial = _extract_serial(right_normalized)
    return bool(left_serial and right_serial and left_serial == right_serial)


def _extract_serial(name: str) -> str | None:
    normalized = normalize_printer_name(name).upper()
    if not normalized.startswith("INSTAX-"):
        return None
    serial = "".join(ch for ch in normalized.removeprefix("INSTAX-") if ch.isalnum())
    return serial or None


def _is_android_advertisement(name: str) -> bool:
    return name.strip().upper().endswith("(ANDROID)")


def _connect_target_name(name: str) -> str:
    if _has_platform_suffix(name):
        return name.strip()
    return normalize_printer_name(name)


def _has_platform_suffix(name: str) -> bool:
    upper = name.strip().upper()
    return upper.endswith("(IOS)") or upper.endswith("(ANDROID)")


class _ConnectStageTracker:
    """Capture the current attempt's real phase and terminal native error."""

    def __init__(self) -> None:
        self.max_stage: int | None = None
        self.failure_detail: str | None = None

    def observe(self, stage: int, detail: str = "") -> None:
        if stage == _CONNECT_STAGE_FAILED:
            self.failure_detail = detail or None
            return
        if stage not in CONNECT_STAGE_NAMES:
            return
        # Native callbacks are synchronous. A phase regression starts a setup retry, including
        # reused-link fallbacks that begin at service_discovery without ble_connecting.
        if self.max_stage is None or stage < self.max_stage:
            self.failure_detail = None
        self.max_stage = stage


_CONNECT_STAGE_FAILED = 10


def _connect_progress_logger(
    target_name: str,
    stage_tracker: _ConnectStageTracker | None = None,
) -> Callable[[int, bytes | None], None]:
    def emit(stage: int, detail: bytes | None) -> None:
        detail_text = detail.decode("utf-8", errors="replace") if detail else ""
        if stage_tracker is not None:
            stage_tracker.observe(stage, detail_text)
        stage_name = CONNECT_STAGE_NAMES.get(stage, "unknown")
        routine_scan = stage in {0, 1} or (
            stage == _CONNECT_STAGE_FAILED
            and stage_tracker is not None
            and stage_tracker.max_stage in {None, 0, 1}
        )
        LOGGER.log(
            logging.DEBUG if routine_scan else logging.INFO,
            "instantlink.connect_progress target=%s stage=%s detail=%s",
            target_name,
            stage_name,
            detail_text,
        )

    return _CONNECT_PROGRESS_CALLBACK(emit)


def _dedupe_names(names: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = normalize_printer_name(name).casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalize_printer_name(name))
    return deduped


def _name_from_address(address: str) -> str:
    if address.upper().startswith("INSTANTLINK:"):
        return address.split(":", maxsplit=1)[1]
    return address
