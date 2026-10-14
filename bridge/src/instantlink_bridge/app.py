"""InstantLink Bridge vertical-slice application entry point."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import signal
import sys
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import Future as ThreadFuture
from contextlib import AsyncExitStack, suppress
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from instantlink_bridge.ble.instantlink import (
    close_default_instantlink_backend,
    instantlink_backend_enabled,
)
from instantlink_bridge.ble.instantlink import (
    print_file_to_printer as print_file_to_printer_instantlink,
)
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.ble.types import (
    CoverOpenError,
    DiscoveredPrinter,
    LowPrinterBatteryError,
    NoFilmError,
    PrinterBusyError,
    PrintRejectedError,
)
from instantlink_bridge.config import (
    DEFAULT_CONFIG_PATH,
    BridgeConfig,
    DatestampFormat,
    FtpConfig,
    PowerBackend,
    SyncConfig,
    SyncDestination,
    load_config,
)
from instantlink_bridge.imaging.models import (
    AdjustmentProfile,
    CorrectionProfile,
    FitMode,
    ImagePipelineError,
    ImagePreparationTimeoutError,
    ImageTooLargeError,
    PreparedImage,
    PrintEdit,
)
from instantlink_bridge.net.health import FtpActivityTracker
from instantlink_bridge.power.monitor import BatteryPolicy, IdlePolicy, PowerMonitor, PowerPolicy
from instantlink_bridge.power.performance import CpuPerformanceController
from instantlink_bridge.power.pisugar import PiSugarClient
from instantlink_bridge.power.x306 import NoBatteryClient, X306BatteryClient
from instantlink_bridge.printing import PrintProgress, PrintProgressCallback, PrintStage
from instantlink_bridge.system_info import (
    format_status_report,
    format_version_summary,
    read_device_id,
)
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiSnapshot
from instantlink_bridge.ui.pairing import (
    BluetoothctlPrinterPairer,
    BluezObjectsProvider,
    PrinterPairer,
)
from instantlink_bridge.ui.status import scan_bluez_instax_printers, status_target_for_visible_match
from instantlink_bridge.watchdog import WatchdogNotifier, run_watchdog_heartbeat

if TYPE_CHECKING:
    from PIL import Image

    from instantlink_bridge.ble.client import ConnectedInstaxPrinter
    from instantlink_bridge.ble.session import InstaxBleSessionManager
    from instantlink_bridge.camera.ftp import FtpReceiveService, ReceivedImage
    from instantlink_bridge.sync.outbox import SyncOutbox
    from instantlink_bridge.sync.server import SyncService

    # Full signature visible to type-checkers (ReceivedImage is importable here).
    PrinterSender = Callable[
        [PairedPrinter, ReceivedImage, BridgeConfig, PrintEdit, PrintProgressCallback],
        Awaitable[None],
    ]
else:
    # At runtime PrinterSender resolves to a generic callable so `typing.get_type_hints()` on a
    # function annotated with `PrinterSender` does NOT need to evaluate a forward reference to
    # `ReceivedImage` (codex finding 3 — keeps the TYPE_CHECKING-only `camera.ftp` import safe).
    PrinterSender = Callable[..., Awaitable[None]]

LOGGER = logging.getLogger(__name__)
AUTO_PRINT_DELAY_S = 1.0
IMAGE_QUEUE_MAXSIZE = 100
PRINT_JOB_TIMEOUT_S = 120.0
PRINT_JOB_HARD_TIMEOUT_S = 300.0
PRINT_TARGET_SCAN_TIMEOUT_S = 1.0
PRINT_TARGET_SCAN_ATTEMPTS = 5
POWEROFF_HELPER = "/usr/local/sbin/instantlink-bridge-poweroff"
SYNC_SERVICE_STOP_TIMEOUT_S = 5.0


class PrintJobError(RuntimeError):
    """Raised when a received image cannot be printed."""


class PrintUi(Protocol):
    """UI operations needed by the print orchestration flow."""

    async def image_received(self, received: ReceivedImage) -> None:
        """Show that a received image has been dequeued for processing."""

    async def await_print_confirmation(
        self,
        received: ReceivedImage,
        *,
        timeout_s: float | None = AUTO_PRINT_DELAY_S,
    ) -> PrintEdit | None:
        """Return preview edits when printing should continue."""

    def take_prepared_print_image(
        self,
        received: ReceivedImage,
        edit: PrintEdit | None,
    ) -> PreparedImage | None:
        """Return the preview's prepared image when it matches ``edit``.

        Returning ``None`` is always valid — the print path then prepares the
        image itself, exactly as it did before plan 056 T1.1.
        """

    async def printing_started(self, received: ReceivedImage) -> None:
        """Show printing state."""

    async def print_progress(self, progress: PrintProgress) -> None:
        """Show current print progress."""

    async def print_complete(self, received: ReceivedImage) -> None:
        """Show print complete state."""

    async def print_failed(self, message: str) -> None:
        """Show print failure state."""


class ImageQueueStatusUi(Protocol):
    """Optional UI hooks for receive queue state."""

    async def image_queue_changed(self, *, depth: int, max_size: int) -> None:
        """Show current receive queue depth."""

    async def image_queue_overflow(
        self,
        received: ReceivedImage,
        *,
        depth: int,
        max_size: int,
    ) -> None:
        """Show that a received image was dropped because the queue was full."""


class AsyncStopService(Protocol):
    """Small protocol for optional runtime helpers."""

    async def stop(self) -> None:
        """Stop the helper."""


class AsyncStartStopService(Protocol):
    """Startable/stoppable runtime helper (e.g. the iPhone sync service)."""

    async def start(self) -> None:
        """Start the helper."""

    async def stop(self) -> None:
        """Stop the helper."""


async def scan_instax_printers(timeout_s: float = 5.0) -> list[DiscoveredPrinter]:
    """Load the diagnostic scanner only when the fallback is requested."""
    await asyncio.to_thread(import_module, "instantlink_bridge.ble.client")
    from instantlink_bridge.ble.client import scan_instax_printers as scan

    return await scan(timeout_s)


async def close_default_ble_session_manager(*, forget_endpoint: bool = True) -> None:
    """Close existing fallback state without importing an unused diagnostic backend."""
    if "instantlink_bridge.ble.client" not in sys.modules:
        return
    # A cancelled first-use task may leave its import running in a worker. Join its
    # module lock away from the event loop before accessing partially published state.
    await asyncio.to_thread(import_module, "instantlink_bridge.ble.client")
    from instantlink_bridge.ble.client import close_default_ble_session_manager as close

    await close(forget_endpoint=forget_endpoint)


async def close_default_image_preparation_worker() -> None:
    """Close an existing photo worker without loading it on an idle native run."""
    if "instantlink_bridge.imaging.worker" not in sys.modules:
        return
    await asyncio.to_thread(import_module, "instantlink_bridge.imaging.worker")
    from instantlink_bridge.imaging.worker import close_default_image_preparation_worker as close

    await close()


async def print_file_to_printer_bleak(
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
    session_manager: object | None = None,
) -> None:
    """Import the diagnostic print path off the event loop before dispatching it."""
    await asyncio.to_thread(import_module, "instantlink_bridge.ble.client")
    from instantlink_bridge.ble.client import print_file_to_printer

    await print_file_to_printer(
        address,
        image_path,
        name=name,
        fit=fit,
        quality=quality,
        edit=edit,
        print_option=print_option,
        model=model,
        progress=progress,
        adjustments=adjustments,
        correction=correction,
        session_manager=cast(
            "InstaxBleSessionManager[ConnectedInstaxPrinter] | None", session_manager
        ),
    )


def read_exif_datestamp_text(
    source_path: Path, language: str = "en", *, fmt: DatestampFormat | None = None
) -> str:
    """Load EXIF helpers inside the existing metadata thread."""
    from instantlink_bridge.imaging.postprocess import read_exif_datestamp_text as read

    return read(source_path, language, fmt=fmt)


async def run_ftp_receive_slice(config_path: Path) -> None:
    """Run the first vertical slice: FTP upload -> logged file path."""

    LOGGER.info("bridge.boot.start")
    config = load_config(config_path)
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue(maxsize=IMAGE_QUEUE_MAXSIZE)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    notifier = WatchdogNotifier()
    watchdog_task: asyncio.Task[None] | None = None
    power_task: asyncio.Task[None] | None = None
    ui_event_tasks: set[asyncio.Task[None]] = set()
    ftp_activity = FtpActivityTracker()
    power_monitor: PowerMonitor | None = None
    cpu_performance = CpuPerformanceController()
    service: FtpReceiveService | None = None
    bluez_agent: AsyncStopService | None = None
    bluetooth_task: asyncio.Task[None] | None = None
    cpu_start_task: asyncio.Task[None] | None = None
    sync_outbox: SyncOutbox | None = None
    sync_service: SyncService | None = None
    sync_setup_task: asyncio.Task[None] | None = None
    # Desired sync-enabled state; updated by the runtime config-applied
    # callback so a destination flip that lands while sync setup is still
    # running is honored once setup finishes.
    sync_desired = config.sync.sync_enabled

    async def current_bluez_objects() -> object:
        provider = getattr(bluez_agent, "managed_objects_snapshot", None)
        if not callable(provider):
            raise RuntimeError("BlueZ pairing agent snapshot unavailable")
        return await cast(BluezObjectsProvider, provider)()

    async def watch_printer_disconnect(
        name: str, callback: Callable[[], None]
    ) -> Callable[[], None]:
        watcher = getattr(bluez_agent, "watch_printer_disconnect", None)
        if not callable(watcher):
            return lambda: None
        return await cast(
            Callable[[str, Callable[[], None]], Awaitable[Callable[[], None]]], watcher
        )(name, callback)

    pairer = BluetoothctlPrinterPairer(bluez_objects_provider=current_bluez_objects)

    async def record_power_activity() -> None:
        if power_monitor is not None:
            await power_monitor.record_activity()

    def apply_runtime_ftp_config(ftp_config: FtpConfig) -> None:
        if service is not None:
            service.set_config(ftp_config)

    async def handle_sync_client_activity() -> None:
        # Mirror the FTP upload path: an authenticated iPhone request is both
        # a UI event and power activity (keeps idle stages from cutting the
        # radio mid-transfer).
        await notify_sync_client_seen(ui)
        await record_power_activity()

    def on_sync_client_activity() -> None:
        # Called by SyncService's aiohttp middleware on this event loop.
        task = loop.create_task(handle_sync_client_activity())
        ui_event_tasks.add(task)
        task.add_done_callback(ui_event_tasks.discard)

    def on_sync_outbox_changed(depth: int) -> None:
        # Called by SyncService's ack handler on this event loop (plan 051
        # P1.2): same notify path as spool-add, scheduled as a task like
        # on_sync_client_activity so the HTTP response never waits on an
        # LCD render.
        task = loop.create_task(notify_sync_outbox_changed(ui, depth=depth))
        ui_event_tasks.add(task)
        task.add_done_callback(ui_event_tasks.discard)

    def apply_runtime_sync_config(sync_config: SyncConfig) -> None:
        nonlocal sync_desired
        sync_desired = sync_config.sync_enabled
        if sync_service is None and (sync_setup_task is None or not sync_setup_task.done()):
            # Construction follows core readiness. The setup worker reads the
            # latest desired state; this pending service is still starting.
            return
        task = loop.create_task(
            apply_sync_destination_change(sync_config, service=sync_service, ui=ui)
        )
        ui_event_tasks.add(task)
        task.add_done_callback(ui_event_tasks.discard)

    def on_sync_token_rotated() -> None:
        # The controller rotated the token file (plan 051 P3.11); restart
        # the service so SyncService.start re-reads it. Scheduled as a task
        # like the other UI-originated sync callbacks.
        task = loop.create_task(
            restart_sync_service_for_token_rotation(sync_service, enabled=sync_desired, ui=ui)
        )
        ui_event_tasks.add(task)
        task.add_done_callback(ui_event_tasks.discard)

    def _build_sync_service_sync() -> tuple[SyncOutbox, SyncService]:
        # Import in the worker thread for the same startup-latency reason as
        # _setup_ftp_service_sync: aiohttp/zeroconf are heavy imports on a
        # cold Pi Zero 2 W and sync must never delay FTP/BLE readiness.
        from instantlink_bridge.sync.outbox import SyncOutbox
        from instantlink_bridge.sync.server import SyncService

        outbox = SyncOutbox(config.sync.outbox_dir, budget_mb=config.sync.outbox_budget_mb)
        built = SyncService(
            outbox,
            port=config.sync.port,
            token_path=config.sync.token_path,
            device_id=read_device_id(),
            client_activity_callback=on_sync_client_activity,
            outbox_changed_callback=on_sync_outbox_changed,
            # Virtual LCD (plan 054 phase A): screen frames come from the
            # live snapshot via the pure renderer; input rides the same
            # action queue as GPIO. `[sync] remote_ui = false` 404s both
            # endpoints without unwiring anything.
            screen_provider=make_remote_screen_provider(lambda: ui.snapshot),
            input_injector=make_remote_input_injector(ui.inject_action),
            remote_ui_enabled=config.sync.remote_ui,
        )
        return outbox, built

    async def setup_sync_service() -> None:
        # Sync is secondary to printing: any failure here logs an error and
        # leaves the bridge running print-only.
        nonlocal sync_outbox, sync_service
        await ready_event.wait()
        construction = asyncio.create_task(asyncio.to_thread(_build_sync_service_sync))
        try:
            try:
                await asyncio.shield(construction)
            finally:
                try:
                    await join_photo_task_cleanup(construction)
                finally:
                    if (
                        construction.done()
                        and not construction.cancelled()
                        and construction.exception() is None
                    ):
                        sync_outbox, sync_service = construction.result()
        except Exception:
            LOGGER.exception("sync.setup_failed outbox_dir=%s", config.sync.outbox_dir)
            # Construction failure means nothing will ever listen this boot:
            # tell the UI so it degrades instead of claiming sync-ready
            # forever from the "starting" default (plan 051 P2.3).
            await notify_sync_service_state(ui, listening=False)
            return
        await announce_initial_outbox_depth(ui, sync_outbox)
        if sync_desired:
            await start_sync_service_guarded(sync_service, reason="startup", ui=ui)

    ready_event = asyncio.Event()
    bluetooth_ready_event = asyncio.Event()
    ui = BridgeUi(
        config,
        config_path=config_path,
        pairer=pairer,
        ftp_activity=ftp_activity,
        power_activity_callback=record_power_activity,
        cpu_performance=cpu_performance,
        ftp_config_applied_callback=apply_runtime_ftp_config,
        sync_config_applied_callback=apply_runtime_sync_config,
        sync_token_rotated_callback=on_sync_token_rotated,
        ready_event=ready_event,
        bluetooth_ready_event=bluetooth_ready_event,
        printer_disconnect_watcher=watch_printer_disconnect,
    )
    power_monitor = build_power_monitor(config, ui=ui)

    def notify_queue_overflow(
        received: ReceivedImage,
        depth: int,
        max_size: int,
    ) -> None:
        task = loop.create_task(
            notify_image_queue_overflow(ui, received, depth=depth, max_size=max_size)
        )
        ui_event_tasks.add(task)
        task.add_done_callback(ui_event_tasks.discard)

    def _setup_ftp_service_sync() -> FtpReceiveService:
        # Run the WHOLE FTP setup off the event loop: the `from instantlink_bridge.camera.ftp
        # import FtpReceiveService` line transitively pulls pyftpdlib (~1 s of synchronous import
        # on a cold Pi Zero 2 W). Doing that import on the main thread would block the BLE
        # gather sibling for the duration of the import, defeating M3. Performing the import +
        # construction + .start() in the executor thread lets the BLE branch make real progress
        # in parallel.
        from instantlink_bridge.camera.ftp import FtpReceiveService

        ftp_service = FtpReceiveService(
            config.ftp,
            queue,
            loop,
            activity_tracker=ftp_activity,
            queue_overflow_callback=notify_queue_overflow,
            bridge_snapshot_provider=lambda: live_ui_snapshot(ui),
        )
        try:
            ftp_service.start()  # blocks until the FTP thread's listener is bound
        except BaseException:
            ftp_service.stop()
            raise
        LOGGER.info("bridge.ftp.ready bind_host=%s port=%s", config.ftp.bind_host, config.ftp.port)
        return ftp_service

    async def start_ftp_service() -> FtpReceiveService:
        nonlocal service
        task = asyncio.create_task(asyncio.to_thread(_setup_ftp_service_sync))
        try:
            return await asyncio.shield(task)
        finally:
            try:
                await join_photo_task_cleanup(task)
            finally:
                if task.done() and not task.cancelled() and task.exception() is None:
                    service = task.result()

    async def start_ui_at_full_performance() -> None:
        if cpu_start_task is None:
            raise RuntimeError("BUG: CPU startup not assigned")
        await asyncio.shield(cpu_start_task)
        await ui.start()

    async def start_bluetooth() -> None:
        nonlocal bluez_agent
        bluez_agent = await start_bluez_agent_if_needed()
        bluetooth_ready_event.set()
        LOGGER.info("bridge.bluetooth.ready agent_registered=%s", bluez_agent is not None)

    async def bluetooth_ready_for_print() -> bool:
        if bluetooth_task is None:
            return False
        stop_waiter = asyncio.create_task(stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                {bluetooth_task, stop_waiter}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_waiter in done:
                return False
            await bluetooth_task
            return True
        finally:
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter

    async def dispatch_ready_image(received: ReceivedImage) -> None:
        # Capture this item's destination once. Readiness waits remain inside
        # the shutdown-observed job, retaining source ownership throughout.
        snapshot = live_ui_snapshot(ui)
        item_config = ui.config
        if snapshot.sync_destination == SyncDestination.IPHONE.value:
            if sync_setup_task is not None:
                await asyncio.shield(sync_setup_task)
        elif not await bluetooth_ready_for_print():
            return
        await dispatch_received_image(
            received,
            snapshot=snapshot,
            config=item_config,
            ui=ui,
            pairer=pairer,
            outbox=sync_outbox,
            cpu_performance=cpu_performance,
        )

    try:
        # UI and FTP are the core service; Bluetooth initializes independently.
        # Separate readiness events prevent early Printer operations without
        # keeping the LCD/input path waiting for BlueZ. Sync imports begin after
        # core readiness so their CPU/I/O cost does not compete with these paths.
        # CPU helper I/O, FTP binding and agent registration are independent.
        # First LCD/input and core READY still require the awake CPU tier.
        cpu_start_task = asyncio.create_task(cpu_performance.start(), name="bridge.cpu_start")
        bluetooth_task = asyncio.create_task(start_bluetooth(), name="bridge.bluetooth_start")
        sync_setup_task = asyncio.create_task(setup_sync_service())
        ftp_result, ui_result = await asyncio.gather(
            start_ftp_service(),
            start_ui_at_full_performance(),
            return_exceptions=True,
        )
        if not isinstance(ftp_result, BaseException):
            service = ftp_result
        # If BOTH primary branches failed, log the secondary failure before re-raising the
        # primary so the second exception is never silently dropped (codex finding 1).
        failures = [exc for exc in (ftp_result, ui_result) if isinstance(exc, BaseException)]
        for exc in failures[1:]:
            LOGGER.error("bridge.startup_secondary_failure", exc_info=exc)
        if failures:
            raise failures[0]
        # Robust runtime guard (not just `assert`, which would be stripped under `python -O`).
        if service is None:
            raise RuntimeError("BUG: FTP service not assigned after successful gather")
        if bluetooth_task.done():
            await bluetooth_task
        notifier.ready()
        ready_event.set()
        watchdog_task = asyncio.create_task(run_watchdog_heartbeat(stop_event, notifier))
        power_task = asyncio.create_task(power_monitor.run(stop_event))
        LOGGER.info(
            "bridge.ready mode=ftp_receive bind_host=%s usb_host=%s port=%s incoming=%s",
            config.ftp.bind_host,
            config.ftp.host,
            config.ftp.port,
            config.ftp.incoming_dir,
        )
        while not stop_event.is_set():
            if bluetooth_task.done():
                await bluetooth_task
            service.raise_if_failed()
            try:
                received = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            LOGGER.info(
                "bridge.image_dequeued path=%s remote_ip=%s queue_depth=%s",
                received.path,
                received.remote_ip,
                queue.qsize(),
            )
            try:
                await notify_image_queue_changed(
                    ui,
                    depth=queue.qsize(),
                    max_size=queue.maxsize,
                )
                await power_monitor.record_activity()
                await run_image_job_until_stopped(
                    dispatch_ready_image(received),
                    stop_event=stop_event,
                    on_stop=service.begin_stopping,
                )
            except Exception as exc:
                LOGGER.exception(
                    "bridge.image_job_unhandled path=%s error_type=%s",
                    received.path,
                    type(exc).__name__,
                )
            finally:
                queue.task_done()
                service.release_received_image(received.path)
    finally:
        if service is not None:
            service.begin_stopping()
            # The consumer has exited. Retain abandoned originals on disk,
            # but release every queued job's ownership and queue accounting.
            while True:
                try:
                    abandoned = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                queue.task_done()
                service.release_received_image(abandoned.path)
        notifier.stopping()
        stop_event.set()

        async def shutdown_resources() -> None:
            failures: list[BaseException] = []

            async def close_resource(name: str, work: Awaitable[object]) -> None:
                try:
                    await work
                except BaseException as exc:
                    failures.append(exc)
                    LOGGER.error("bridge.shutdown_resource_failed resource=%s", name, exc_info=exc)

            async def stop_task(task: asyncio.Task[None]) -> None:
                task.cancel()
                await join_stopped_task(task)

            async def join_stopped_task(task: asyncio.Task[None]) -> None:
                with suppress(asyncio.CancelledError):
                    await task

            if watchdog_task is not None:
                await close_resource("watchdog", stop_task(watchdog_task))
            if power_task is not None:
                await close_resource("power", stop_task(power_task))
            event_tasks = tuple(ui_event_tasks)
            for task in event_tasks:
                task.cancel()
            for task in event_tasks:
                await close_resource("ui_event", join_stopped_task(task))
            if sync_setup_task is not None:
                await close_resource("sync_setup", stop_task(sync_setup_task))
            if cpu_start_task is not None:
                await close_resource("cpu_start", join_photo_task_cleanup(cpu_start_task))
            await close_resource(
                "sync", stop_sync_service_guarded(sync_service, reason="shutdown", ui=ui)
            )
            await close_resource("ui", ui.stop())
            if bluetooth_task is not None:
                await close_resource("bluetooth_start", stop_task(bluetooth_task))
            await close_resource("cpu", cpu_performance.close())
            await close_resource("instantlink_backend", close_default_instantlink_backend())
            if bluez_agent is not None:
                await close_resource("bluez_agent", bluez_agent.stop())
            await close_resource("ble_sessions", close_default_ble_session_manager())
            await close_resource("image_worker", close_default_image_preparation_worker())
            if service is not None:
                try:
                    service.stop()
                except BaseException as exc:
                    failures.append(exc)
                    LOGGER.error("bridge.shutdown_resource_failed resource=ftp", exc_info=exc)
            if failures:
                raise failures[0]

        # A second shutdown/cancellation request must not abandon the remaining
        # services while child operations still own their resources.
        cleanup = asyncio.create_task(shutdown_resources(), name="bridge.shutdown")
        try:
            await asyncio.shield(cleanup)
        finally:
            await join_photo_task_cleanup(cleanup)


async def start_bluez_agent_if_needed() -> AsyncStopService | None:
    """Register a NoInputNoOutput BlueZ agent for InstantLink printer bonding."""

    if not instantlink_backend_enabled():
        return None
    try:
        from instantlink_bridge.ble.agent import BluezAgentService

        agent = BluezAgentService()
        try:
            await agent.start()
        except BaseException:
            # Registration can be canceled during shutdown after opening D-Bus
            # but before returning ownership to the caller.
            await agent.stop()
            raise
        return agent
    except Exception:
        LOGGER.exception("bluetooth.agent_start_failed")
        raise


def build_power_monitor(config: BridgeConfig, *, ui: BridgeUi) -> PowerMonitor:
    """Create the power monitor wired to UI events and system shutdown."""

    power = config.power
    policy = PowerPolicy(
        battery=BatteryPolicy(
            poll_interval_s=power.battery_poll_interval_s,
            warning_threshold_percent=power.battery_warning_threshold_percent,
            safe_shutdown_threshold_percent=power.battery_safe_shutdown_threshold_percent,
        ),
        idle=IdlePolicy(
            dim_after_s=power.idle_dim_after_s,
            screen_off_after_s=power.idle_screen_off_after_s,
            deep_idle_after_s=power.idle_deep_after_s,
            poweroff_after_s=power.idle_poweroff_after_s,
            poweroff_enabled=power.idle_poweroff_enabled,
        ),
    )
    return PowerMonitor(
        battery_client=battery_client_for_backend(power.backend),
        policy=policy,
        shutdown=request_system_poweroff,
        event_handler=ui.apply_power_event,
    )


def battery_client_for_backend(
    backend: PowerBackend,
) -> X306BatteryClient | PiSugarClient | NoBatteryClient:
    """Return a battery backend for the configured hardware."""

    if backend is PowerBackend.PISUGAR:
        return PiSugarClient()
    if backend is PowerBackend.NONE:
        return NoBatteryClient()
    return X306BatteryClient()


async def request_system_poweroff() -> None:
    """Ask systemd to power off through the provisioned sudo helper."""

    if os.environ.get("INSTANTLINK_BRIDGE_DISABLE_POWEROFF") == "1":
        LOGGER.warning("power.shutdown_disabled_by_environment")
        return

    helper = os.environ.get("INSTANTLINK_BRIDGE_POWEROFF_HELPER", POWEROFF_HELPER)
    process = await asyncio.create_subprocess_exec(
        "sudo",
        "-n",
        helper,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            "poweroff helper failed "
            f"rc={process.returncode} stdout={stdout.decode(errors='replace').strip()!r} "
            f"stderr={stderr.decode(errors='replace').strip()!r}"
        )


def live_ui_snapshot(ui: BridgeUi) -> UiSnapshot:
    """Keep operational admission checks independent of a visible unlock overlay."""
    return ui.live_snapshot


async def dispatch_received_image(
    received: ReceivedImage,
    *,
    snapshot: UiSnapshot,
    config: BridgeConfig,
    ui: PrintUi,
    pairer: PrinterPairer,
    outbox: SyncOutbox | None,
    printer_sender: PrinterSender | None = None,
    cpu_performance: CpuPerformanceController | None = None,
) -> None:
    """Fan one dequeued image out to the sync outbox and/or the print flow.

    The destination is read from the UI snapshot per item so runtime Settings
    changes apply without a restart. Spooling always happens BEFORE the print
    flow because the print pipeline may consume/delete the received file; an
    outbox failure never breaks the print path.
    """

    destination = snapshot.sync_destination
    if destination in _SYNC_SPOOL_DESTINATIONS:
        if not await spool_image_to_sync_outbox(received, ui=ui, outbox=outbox):
            await ui.print_failed("Sync unavailable")
    if destination == SyncDestination.IPHONE.value:
        LOGGER.info("sync.print_skipped_destination path=%s", received.path)
        return
    await ui.image_received(received)
    await handle_received_image(
        received,
        config=config,
        ui=ui,
        pairer=pairer,
        printer_sender=printer_sender,
        timeout_s=config.workflow.auto_print_delay_s,
        notify_received=False,
        cpu_performance=cpu_performance,
        preparation_model_hint=snapshot.printer_model,
    )


_SYNC_SPOOL_DESTINATIONS = frozenset({SyncDestination.IPHONE.value})


async def spool_image_to_sync_outbox(
    received: ReceivedImage,
    *,
    ui: object,
    outbox: SyncOutbox | None,
) -> bool:
    """Spool a received original for iPhone pickup; never raise into printing."""

    if outbox is None:
        LOGGER.error("sync.outbox_add_failed path=%s reason=outbox_unavailable", received.path)
        return False
    add_task = asyncio.create_task(
        asyncio.to_thread(outbox.add, received.path, remote_ip=received.remote_ip)
    )
    try:
        try:
            await asyncio.shield(add_task)
        finally:
            # A filesystem transaction cannot be cancelled with its asyncio
            # waiter. Keep ownership until its thread commits or fails.
            await join_photo_task_cleanup(add_task)
    except Exception:
        LOGGER.exception("sync.outbox_add_failed path=%s", received.path)
        return False
    depth = await asyncio.to_thread(outbox.depth)
    await notify_sync_outbox_changed(ui, depth=depth)
    return True


async def announce_initial_outbox_depth(ui: object, outbox: object) -> None:
    """Push the outbox depth reloaded from disk to the UI at startup.

    The spool index survives restarts but the controller's chip state does
    not — without this the LCD shows a stale zero until the next add/ack
    (found on-device 2026-07-15 via the remote screen).
    """

    depth_fn = getattr(outbox, "depth", None)
    if not callable(depth_fn):
        return
    try:
        depth = int(await asyncio.to_thread(depth_fn))
    except Exception:
        LOGGER.exception("sync.initial_depth_failed")
        return
    await notify_sync_outbox_changed(ui, depth=depth)


async def notify_sync_outbox_changed(ui: object, *, depth: int) -> None:
    """Notify UI implementations that opt in to sync outbox depth updates."""

    await call_optional_ui_hook(ui, "sync_outbox_changed", depth)


async def notify_sync_client_seen(ui: object) -> None:
    """Notify UI implementations that opt in to sync client activity."""

    await call_optional_ui_hook(ui, "sync_client_seen")


async def notify_sync_service_state(ui: object, *, listening: bool) -> None:
    """Notify UI implementations that opt in to sync-service state (plan 051 P2.3)."""

    await call_optional_ui_hook(ui, "sync_service_state_changed", listening)


def make_remote_screen_provider(
    snapshot_provider: Callable[[], UiSnapshot],
) -> Callable[[], Image.Image | None]:
    """Build the virtual-LCD frame source for SyncService (plan 054 phase A).

    Renders the live :class:`UiSnapshot` through the pure renderer. While
    the snapshot compares equal to the previous one (snapshots are frozen;
    equality is the same dedup the controller's ``_render`` uses for SPI
    traffic) the SAME frame object is returned, which lets SyncService key
    its encoded-PNG cache on frame identity — an idle screen polled at
    3 fps costs one render, ever. SyncService calls the provider from a
    worker thread and serializes calls behind a lock, so the closure state
    needs no locking of its own.
    """

    from instantlink_bridge.ui.render import render_snapshot

    last_snapshot: UiSnapshot | None = None
    last_frame: Image.Image | None = None

    def provide() -> Image.Image | None:
        nonlocal last_snapshot, last_frame
        snapshot = snapshot_provider()
        if last_frame is not None and snapshot == last_snapshot:
            return last_frame
        frame = render_snapshot(snapshot)
        last_snapshot = snapshot
        last_frame = frame
        return frame

    return provide


def make_remote_input_injector(
    inject: Callable[[UiAction], bool],
) -> Callable[[str], bool]:
    """Map virtual-LCD action strings onto ``BridgeUi.inject_action`` (plan 054).

    The sync server validates strings against its own allowlist before
    calling this, so the ``ValueError`` guard only matters if the two
    action vocabularies ever drift — it degrades to a 400 instead of a
    crashed request.
    """

    def injector(action: str) -> bool:
        try:
            ui_action = UiAction(action)
        except ValueError:
            LOGGER.warning("sync.remote_input_unknown action=%s", action)
            return False
        return inject(ui_action)

    return injector


async def apply_sync_destination_change(
    sync_config: SyncConfig,
    *,
    service: AsyncStartStopService | None,
    ui: object | None = None,
) -> None:
    """Apply a runtime destination change to the sync service lifecycle."""

    LOGGER.info(
        "sync.config_applied destination=%s sync_enabled=%s",
        sync_config.destination.value,
        sync_config.sync_enabled,
    )
    if sync_config.sync_enabled:
        await start_sync_service_guarded(service, reason="config_applied", ui=ui)
    else:
        await stop_sync_service_guarded(service, reason="config_applied", ui=ui)


async def restart_sync_service_for_token_rotation(
    service: AsyncStartStopService | None,
    *,
    enabled: bool,
    ui: object | None = None,
) -> None:
    """Restart the sync service so it re-reads a rotated bearer token.

    Plan 051 P3.11. The stop leg deliberately does not notify the UI: the
    controller already put the surface in the mild "starting" window when
    it rotated the file, so only the start outcome matters — the state
    flow reads "starting" → "listening" (or "unavailable" on a failed
    rebind). With sync disabled there is nothing to restart; the rotated
    file is picked up whenever the destination re-enables sync.
    """

    LOGGER.info("sync.token_rotation_restart enabled=%s", enabled)
    await stop_sync_service_guarded(service, reason="token_rotated", ui=None)
    if enabled:
        await start_sync_service_guarded(service, reason="token_rotated", ui=ui)


async def start_sync_service_guarded(
    service: AsyncStartStopService | None,
    *,
    reason: str,
    ui: object | None = None,
) -> None:
    """Start the sync service; failures log an error but never propagate.

    The UI is told the actual outcome (plan 051 P2.3) so the LCD never
    claims sync-ready while nothing listens on the sync port.
    """

    if service is None:
        LOGGER.warning("sync.service_unavailable action=start reason=%s", reason)
        await notify_sync_service_state(ui, listening=False)
        return
    try:
        await service.start()
        LOGGER.info("sync.service_start reason=%s", reason)
        await notify_sync_service_state(ui, listening=True)
    except Exception:
        LOGGER.exception("sync.service_start_failed reason=%s", reason)
        await notify_sync_service_state(ui, listening=False)


async def stop_sync_service_guarded(
    service: AsyncStartStopService | None,
    *,
    reason: str,
    ui: object | None = None,
) -> None:
    """Stop the sync service within the shutdown budget; never propagate.

    Whether the stop succeeds or times out, the service is no longer
    reliable — the UI is told it is not listening (plan 051 P2.3).
    """

    if service is None:
        return
    try:
        await asyncio.wait_for(service.stop(), timeout=SYNC_SERVICE_STOP_TIMEOUT_S)
        LOGGER.info("sync.service_stop reason=%s", reason)
    except Exception:
        LOGGER.exception("sync.service_stop_failed reason=%s", reason)
    await notify_sync_service_state(ui, listening=False)


async def handle_received_image(
    received: ReceivedImage,
    *,
    config: BridgeConfig,
    ui: PrintUi,
    pairer: PrinterPairer,
    printer_sender: PrinterSender | None = None,
    timeout_s: float | None = AUTO_PRINT_DELAY_S,
    notify_received: bool = True,
    cpu_performance: CpuPerformanceController | None = None,
    preparation_model_hint: PrinterModel | None = None,
) -> None:
    """Run one FTP-received image through the auto-print flow."""

    progress_tasks: list[asyncio.Future[None] | ThreadFuture[None]] = []
    accepting_progress = False
    performance_scope = AsyncExitStack()
    try:
        if notify_received:
            await ui.image_received(received)
        edit = await ui.await_print_confirmation(received, timeout_s=timeout_s)
        if edit is None:
            LOGGER.info("bridge.print_cancelled path=%s", received.path)
            return

        # Preview preparation reads the live settings after readiness/pairing
        # waits. Freeze those accepted settings before consuming its JPEG, so
        # model-mismatch preparation and sender options describe the same photo.
        # Injected/headless PrintUi implementations retain their supplied config.
        accepted_config = getattr(ui, "config", None)
        if isinstance(accepted_config, BridgeConfig):
            config = accepted_config

        if cpu_performance is not None:
            await performance_scope.enter_async_context(cpu_performance.boost())

        if printer_sender is not None:
            sender = printer_sender
        else:
            # Bind the preview's already-prepared image here rather than
            # widening PrinterSender: injected senders keep the 5-positional
            # signature, and only the real sender learns about it
            # (plan 056 T1.1). Must run after await_print_confirmation, so the
            # edit is final.
            sender = partial(
                send_print_to_printer,
                prepared_image=ui.take_prepared_print_image(received, edit),
                preparation_model_hint=preparation_model_hint,
            )
        await ui.printing_started(received)
        selected = select_configured_printer(
            await pairer.list_paired(),
            configured_name=config.printer.device_name,
        )
        if selected is None:
            raise PrintJobError("Select printer first")
        target = await resolve_print_target(selected)
        LOGGER.info(
            "bridge.print_start path=%s target=%s name=%s",
            received.path,
            target.address,
            target.name,
        )
        loop = asyncio.get_running_loop()
        accepting_progress = True

        def progress_callback(progress: PrintProgress) -> None:
            if not accepting_progress:
                return
            progress_tasks.append(
                asyncio.run_coroutine_threadsafe(ui.print_progress(progress), loop)
            )

        await await_print_sender_without_cancelling_on_timeout(
            sender(target, received, config, edit, progress_callback),
            ui=ui,
            received=received,
            slow_after_s=PRINT_JOB_TIMEOUT_S,
            hard_after_s=PRINT_JOB_HARD_TIMEOUT_S,
        )
        accepting_progress = False
        await drain_print_progress(progress_tasks)
    except ImagePipelineError as exc:
        accepting_progress = False
        await drain_print_progress(progress_tasks)
        LOGGER.warning("bridge.print_image_rejected path=%s error=%s", received.path, exc)
        await ui.print_failed(print_error_message(exc))
    except PrintJobError as exc:
        accepting_progress = False
        await drain_print_progress(progress_tasks)
        LOGGER.warning("bridge.print_not_ready path=%s error=%s", received.path, exc)
        await ui.print_failed(str(exc))
    except PrintRejectedError as exc:
        accepting_progress = False
        await drain_print_progress(progress_tasks)
        LOGGER.warning("bridge.print_rejected path=%s error=%s", received.path, exc)
        await ui.print_failed(printer_rejection_message(exc))
    except Exception as exc:
        accepting_progress = False
        await drain_print_progress(progress_tasks)
        LOGGER.exception(
            "bridge.print_failed path=%s error_type=%s", received.path, type(exc).__name__
        )
        await ui.print_failed("Print failed")
    else:
        LOGGER.info("bridge.print_complete path=%s", received.path)
        await ui.print_complete(received)
    finally:
        accepting_progress = False
        await performance_scope.aclose()


async def run_image_job_until_stopped(
    work: Awaitable[None],
    *,
    stop_event: asyncio.Event,
    on_stop: Callable[[], None] | None = None,
) -> None:
    """Observe shutdown while one ordered photo job owns its resources.

    Cancellation joins the job's cleanup before another photo or service
    teardown can use the same Printer/image worker. The backend retains its
    own serialization and bounded FFI cancellation grace.
    """
    job = asyncio.ensure_future(work)
    stopping = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait({job, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if stopping in done and on_stop is not None:
            on_stop()
        if job in done:
            await job
        else:
            await cancel_and_join_photo_task(job)
    except asyncio.CancelledError:
        if on_stop is not None:
            on_stop()
        raise
    finally:
        stopping.cancel()
        try:
            await cancel_and_join_photo_task(job)
        finally:
            await asyncio.gather(stopping, return_exceptions=True)


async def cancel_and_join_photo_task(task: asyncio.Future[None]) -> None:
    """Cancel once, then retain resource ownership through repeated outer cancellation."""
    if not task.done() and not (isinstance(task, asyncio.Task) and task.cancelling()):
        task.cancel()
    await join_photo_task_cleanup(task)


async def join_photo_task_cleanup(task: Awaitable[object]) -> None:
    """Join existing work without forwarding repeated cancellation into its cleanup."""
    joined = asyncio.gather(task, return_exceptions=True)
    cancelled = False
    while True:
        try:
            await asyncio.shield(joined)
            break
        except asyncio.CancelledError:
            # Forwarding this into the sender could interrupt its FFI grace,
            # release the Printer lock and leave a blocking call still alive.
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError


async def await_print_sender_without_cancelling_on_timeout(
    send: Awaitable[None],
    *,
    ui: PrintUi,
    received: ReceivedImage,
    slow_after_s: float | None,
    hard_after_s: float | None = None,
) -> None:
    """Wait for one print send while keeping an over-time hardware job serialized."""

    send_task = asyncio.ensure_future(send)
    try:
        try:
            await asyncio.wait_for(asyncio.shield(send_task), timeout=slow_after_s)
        except TimeoutError:
            if send_task.done():
                # A sender can fail with its own TimeoutError. Preserve that
                # result rather than treating completed work as still printing.
                send_task.result()
                return
            LOGGER.warning(
                "bridge.print_slow path=%s timeout_s=%s",
                received.path,
                slow_after_s,
            )
            await ui.print_progress(
                PrintProgress(PrintStage.FINISHING, "Still printing", "Waiting for printer")
            )
            if hard_after_s is None or slow_after_s is None:
                await asyncio.shield(send_task)
                return
            remaining_s = max(1.0, hard_after_s - slow_after_s)
            try:
                await asyncio.wait_for(asyncio.shield(send_task), timeout=remaining_s)
            except TimeoutError:
                if send_task.done():
                    send_task.result()
                    return
                LOGGER.critical(
                    "bridge.print_hard_timeout path=%s hard_timeout_s=%s",
                    received.path,
                    hard_after_s,
                )
                await ui.print_progress(
                    PrintProgress(PrintStage.FINISHING, "Print stalled", "Restarting bridge")
                )
                os._exit(1)
    finally:
        # A slow-print notice keeps the hardware job running. Shutdown is a
        # separate cancellation path: join the sender before releasing its
        # CPU boost or closing the UI/backend, rather than orphaning it.
        await cancel_and_join_photo_task(send_task)


async def drain_print_progress(
    progress_tasks: Sequence[asyncio.Future[None] | ThreadFuture[None]],
) -> None:
    """Let app-scheduled progress updates finish before terminal UI states."""

    if not progress_tasks:
        return
    awaitables = [
        asyncio.wrap_future(task) if isinstance(task, ThreadFuture) else task
        for task in progress_tasks
    ]
    results = await asyncio.gather(*awaitables, return_exceptions=True)
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            continue
        if isinstance(result, Exception):
            LOGGER.warning(
                "bridge.print_progress_ui_failed error_type=%s error=%s",
                type(result).__name__,
                result,
            )


async def notify_image_queue_changed(
    ui: object,
    *,
    depth: int,
    max_size: int,
) -> None:
    """Notify UI implementations that opt in to queue depth updates."""

    await call_optional_ui_hook(
        ui,
        "image_queue_changed",
        depth=depth,
        max_size=max_size,
    )


async def notify_image_queue_overflow(
    ui: object,
    received: ReceivedImage,
    *,
    depth: int,
    max_size: int,
) -> None:
    """Notify UI implementations that opt in to queue overflow updates."""

    await call_optional_ui_hook(
        ui,
        "image_queue_overflow",
        received,
        depth=depth,
        max_size=max_size,
    )


async def call_optional_ui_hook(
    ui: object,
    hook_name: str,
    /,
    *args: object,
    **kwargs: object,
) -> None:
    hook = getattr(ui, hook_name, None)
    if hook is None:
        return
    try:
        result = hook(*args, **kwargs)
        if inspect.isawaitable(result):
            await result
    except Exception:
        LOGGER.exception("bridge.ui_hook_failed hook=%s", hook_name)


async def send_print_to_printer(
    printer: PairedPrinter,
    received: ReceivedImage,
    config: BridgeConfig,
    edit: PrintEdit,
    progress: PrintProgressCallback,
    *,
    prepared_image: PreparedImage | None = None,
    preparation_model_hint: PrinterModel | None = None,
) -> None:
    """Print a received file through the model-detecting BLE path."""

    from dataclasses import replace as _replace

    from instantlink_bridge.imaging.models import correction_profile
    from instantlink_bridge.imaging.presets import resolve_preset

    adjustments = resolve_preset(config.adjustments)
    # If datestamp is enabled, read EXIF and format the date now so
    # apply_adjustments stays locale-agnostic.
    if config.adjustments.datestamp:
        metadata = asyncio.create_task(
            asyncio.to_thread(
                read_exif_datestamp_text,
                received.path,
                config.ui.language.value,
                fmt=config.adjustments.datestamp_format,
            )
        )
        try:
            datestamp_text = await asyncio.shield(metadata)
        except BaseException:
            # Retain the FTP source until the thread actually stops reading it.
            await join_photo_task_cleanup(metadata)
            raise
        adjustments = _replace(adjustments, datestamp_text=datestamp_text)
    if instantlink_backend_enabled():
        # When a preview was shown it already built this exact image; hand it
        # over rather than running the pipeline a second time (plan 056 T1.1).
        # Returns None whenever the preview was skipped (auto_print_delay_s=0)
        # or its edit no longer matches, in which case the printer prepares
        # normally.
        await print_file_to_printer_instantlink(
            printer.address,
            received.path,
            name=printer.name,
            fit=config.printer.fit,
            quality=config.printer.quality,
            edit=edit,
            print_option=config.printer.print_option,
            model=config.printer.model,
            progress=progress,
            adjustments=adjustments,
            correction=correction_profile(config.correction),
            prepared_image=prepared_image,
            preparation_model_hint=preparation_model_hint,
        )
    else:
        await print_file_to_printer_bleak(
            printer.address,
            received.path,
            name=printer.name,
            fit=config.printer.fit,
            quality=config.printer.quality,
            edit=edit,
            print_option=config.printer.print_option,
            model=config.printer.model,
            progress=progress,
            adjustments=adjustments,
            correction=correction_profile(config.correction),
        )


async def resolve_print_target(selected: PairedPrinter) -> PairedPrinter:
    """Resolve a selected printer to the currently connectable BLE endpoint."""

    if instantlink_backend_enabled():
        return selected

    for attempt in range(PRINT_TARGET_SCAN_ATTEMPTS):
        target = await _visible_print_target(selected, scan_instax_printers)
        if target is not None:
            return target
        LOGGER.info(
            "bridge.print_target_retry selected=%s attempt=%s attempts=%s",
            selected.name,
            attempt + 1,
            PRINT_TARGET_SCAN_ATTEMPTS,
        )
    target = await _visible_print_target(
        selected,
        scan_bluez_instax_printers,
        timeout_s=max(PRINT_TARGET_SCAN_TIMEOUT_S, 2.0),
    )
    if target is not None:
        return target
    raise PrintJobError("Printer offline")


async def _visible_print_target(
    selected: PairedPrinter,
    scanner: Callable[[float], Awaitable[Sequence[DiscoveredPrinter | PairedPrinter]]],
    *,
    timeout_s: float = PRINT_TARGET_SCAN_TIMEOUT_S,
) -> PairedPrinter | None:
    try:
        candidates = await scanner(timeout_s)
    except Exception:
        LOGGER.exception("bridge.print_target_scan_failed selected=%s", selected.name)
        return None
    target = status_target_for_visible_match(selected, candidates)
    LOGGER.info(
        "bridge.print_target_scan count=%s selected=%s target=%s",
        len(candidates),
        selected.name,
        target.address if target is not None else "none",
    )
    return target


def select_configured_printer(
    printers: Sequence[PairedPrinter],
    *,
    configured_name: str | None,
) -> PairedPrinter | None:
    """Select the configured printer, falling back to the first selected printer."""

    if configured_name is not None:
        for printer in printers:
            if printer.name == configured_name:
                return printer
    return printers[0] if printers else None


def print_error_message(error: ImagePipelineError) -> str:
    """Map image pipeline errors to short LCD-friendly text."""

    message = str(error).lower()
    if "printer offline" in message:
        return "Printer offline"
    if "printer timed out" in message:
        return "Printer timed out"
    if "printer type unknown" in message:
        return "Printer type unknown"
    if isinstance(error, ImagePreparationTimeoutError):
        return "Image timed out"
    if isinstance(error, ImageTooLargeError):
        return "Image too large"
    return "Image unsupported"


def printer_rejection_message(error: PrintRejectedError) -> str:
    """Map printer rejection errors to short LCD-friendly text."""

    if isinstance(error, NoFilmError):
        return "No film"
    if isinstance(error, CoverOpenError):
        return "Cover open"
    if isinstance(error, LowPrinterBatteryError):
        return "Battery low"
    if isinstance(error, PrinterBusyError):
        return "Printer busy"
    return "Print rejected"


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description="InstantLink Bridge service")
    info_group = parser.add_mutually_exclusive_group()
    info_group.add_argument(
        "--version",
        action="store_true",
        help="show InstantLink Bridge and runtime versions, then exit",
    )
    info_group.add_argument(
        "--status",
        action="store_true",
        help="show read-only system status, then exit",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"config file path (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level",
    )
    args = parser.parse_args(argv)
    if args.version:
        print(format_version_summary())
        return
    if args.status:
        print(format_status_report())
        return
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_ftp_receive_slice(args.config))


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            signal.signal(signum, lambda _signum, _frame: stop_event.set())


if __name__ == "__main__":
    main()
