from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest
from test_app import FakePrintUi
from test_ui_controller import _FakeDisplay, _FakePairer, _FakeStatusProvider

from instantlink_bridge import app
from instantlink_bridge.ble import instantlink
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig
from instantlink_bridge.power.monitor import IdleStage
from instantlink_bridge.system_info import SystemInfo
from instantlink_bridge.system_stats import SystemStatsSnapshot
from instantlink_bridge.ui import controller
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiMode
from instantlink_bridge.ui.settings import SettingsPage
from instantlink_bridge.ui.status import PrinterStatusSnapshot, PrinterStatusUnavailableError

PRINTER = PairedPrinter(address="AA:BB:CC:DD:EE:FF", name="INSTAX-12345678")


def make_ui(provider: _FakeStatusProvider | None = None) -> BridgeUi:
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([PRINTER]),
        status_provider=provider or _FakeStatusProvider(),
    )
    ui._snapshot = ui._build_snapshot(mode=UiMode.READY, paired_printer=PRINTER)
    return ui


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        PrinterStatusUnavailableError("old failure", stale_bond_suspected=True),
        PrinterStatusUnavailableError("old scan", printer_not_found=True),
        TimeoutError("old timeout"),
        RuntimeError("old unexpected error"),
    ],
)
async def test_superseded_status_failure_cannot_schedule_recovery_or_change_counters(
    error: Exception,
) -> None:
    ui = make_ui(_FakeStatusProvider(error=error))
    ui._status_generation = 2
    before = ui.snapshot
    try:
        assert not await ui._refresh_printer_status_in_background(PRINTER, generation=1)
        assert ui._printer_status_misses == 0
        assert ui._auto_rebond_task is None
        assert ui._silent_link_recovery_task is None
        assert ui.snapshot == before
    finally:
        await ui.stop()


@pytest.mark.asyncio
async def test_cancellation_during_bond_reset_reaches_the_caller() -> None:
    ui = make_ui()
    started = asyncio.Event()

    async def reset(_printer: PairedPrinter) -> bool:
        started.set()
        await asyncio.Event().wait()
        return False

    ui._pairer.reset_bond_if_disconnected = reset  # type: ignore[method-assign]
    task = asyncio.create_task(ui._maybe_reset_bond_on_drop(PRINTER))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await ui.stop()


@pytest.mark.asyncio
async def test_unchanged_status_is_not_repeated_at_info(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = make_ui(
        _FakeStatusProvider(
            snapshot=PrinterStatusSnapshot(film_remaining=5, battery=80, is_charging=False)
        )
    )
    caplog.set_level(logging.INFO, logger="instantlink_bridge.ui.controller")
    clock = [1000.0]
    monkeypatch.setattr(ui, "_monotonic", lambda: clock[0])
    try:
        for _ in range(3):
            assert await ui._refresh_printer_status_in_background(PRINTER)
        messages = [r for r in caplog.records if r.message.startswith("ui.printer_status ")]
        assert len(messages) == 1
        clock[0] += 301
        assert await ui._refresh_printer_status_in_background(PRINTER)
        messages = [r for r in caplog.records if r.message.startswith("ui.printer_status ")]
        assert len(messages) == 2  # bounded heartbeat still proves continued successful polling
    finally:
        await ui.stop()


@pytest.mark.asyncio
async def test_status_failure_superseded_during_fetch_has_no_recovery_side_effects() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class Provider(_FakeStatusProvider):
        async def fetch(self, _printer: PairedPrinter) -> PrinterStatusSnapshot:
            started.set()
            await release.wait()
            raise PrinterStatusUnavailableError("old error", stale_bond_suspected=True)

    ui = make_ui(Provider())
    task = asyncio.create_task(ui._refresh_printer_status_in_background(PRINTER, generation=0))
    try:
        await started.wait()
        ui._status_generation += 1
        release.set()
        assert not await task
        assert ui._printer_status_misses == 0
        assert ui._auto_rebond_task is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await ui.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("after_slow_notice", [False, True])
async def test_sender_timeout_error_is_a_completed_failure_not_a_stuck_print(
    monkeypatch: pytest.MonkeyPatch, after_slow_notice: bool
) -> None:
    slow_notice = asyncio.Event()

    class Ui(FakePrintUi):
        async def print_progress(self, progress: app.PrintProgress) -> None:
            await super().print_progress(progress)
            if progress.title == "Still printing":
                slow_notice.set()

    async def send() -> None:
        if after_slow_notice:
            await slow_notice.wait()
        raise TimeoutError("sender's own timeout")

    def restart(_code: int) -> None:
        raise AssertionError("completed sender must not restart Bridge")

    monkeypatch.setattr(app.os, "_exit", restart)
    ui = Ui(should_print=True)
    with pytest.raises(TimeoutError, match="sender's own timeout"):
        await app.await_print_sender_without_cancelling_on_timeout(
            send(),
            ui=ui,
            received=ReceivedImage(Path("unused.jpg"), "camera"),
            slow_after_s=0.001 if after_slow_notice else 1,
            hard_after_s=2,
        )
    assert slow_notice.is_set() == after_slow_notice


@pytest.mark.asyncio
async def test_stop_waits_for_retired_status_cleanup_before_closing_display() -> None:
    started, cleaning, release = (asyncio.Event() for _ in range(3))

    class Provider(_FakeStatusProvider):
        async def fetch(self, _printer: PairedPrinter) -> PrinterStatusSnapshot:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                await release.wait()
                raise
            raise AssertionError("unreachable")

    ui = make_ui(Provider())
    await ui._schedule_printer_status_refresh()
    retired = ui._status_task
    assert retired is not None
    stop: asyncio.Task[None] | None = None
    try:
        await started.wait()
        await ui._cancel_status_refresh()
        await cleaning.wait()
        assert retired in ui._retired_status_tasks
        stop = asyncio.create_task(ui.stop())
        await asyncio.sleep(0)
        assert not stop.done()
        release.set()
        await asyncio.wait_for(stop, 1)
        assert retired.done()
        assert not ui._retired_status_tasks
    finally:
        release.set()
        await asyncio.gather(retired, *([stop] if stop else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_dark_maintenance_expires_printer_and_sync_freshness_on_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = make_ui()
    ui._lock_screen()
    now = asyncio.get_running_loop().time()
    ui._last_printer_status_ok_at = now - ui._printer_status_fresh_ttl_s() + 0.025
    ui._sync_client_seen_at = now - controller.SYNC_CLIENT_RECENT_TTL_S + 0.05
    ui._snapshot = replace(ui._snapshot, printer_status_fresh=True, sync_client_recent=True)
    expired = asyncio.Event()
    original_render = ui._render

    def render() -> None:
        original_render()
        if not ui.snapshot.printer_status_fresh and not ui.snapshot.sync_client_recent:
            expired.set()

    monkeypatch.setattr(ui, "_render", render)
    task = asyncio.create_task(ui._run_render_tick())
    try:
        await asyncio.wait_for(expired.wait(), 0.5)
        assert ui._render_tick_interval_s() == controller.RENDER_SCREEN_OFF_TICK_S
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await ui.stop()


@pytest.mark.asyncio
async def test_display_wake_interrupts_long_dark_maintenance_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = make_ui()
    ui._lock_screen()
    tick_ran = asyncio.Event()
    tick: asyncio.Task[None] | None = None

    def render() -> None:
        if asyncio.current_task() is tick:
            tick_ran.set()

    monkeypatch.setattr(ui, "_render", render)
    tick = asyncio.create_task(ui._run_render_tick())
    try:
        await asyncio.sleep(0)
        assert ui._render_tick_interval_s() == controller.RENDER_SCREEN_OFF_TICK_S
        ui._screen_locked = False
        ui._apply_idle_stage(IdleStage.ACTIVE)
        await asyncio.wait_for(tick_ran.wait(), 0.5)
        assert ui._render_tick_interval_s() == controller.RENDER_TICK_S
    finally:
        tick.cancel()
        await asyncio.gather(tick, return_exceptions=True)
        await ui.stop()


@pytest.mark.asyncio
async def test_locked_about_does_not_start_hidden_collectors_but_wake_can(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = SystemStatsSnapshot(12, 200, 463, 2, 32, 45)
    monkeypatch.setattr(
        controller, "read_system_info", lambda: SystemInfo("IB-1234", "1", "3", "5", "Debian")
    )
    monkeypatch.setattr(controller, "read_system_stats", lambda _: stats)
    monkeypatch.setattr(controller, "ABOUT_PAGE_REFRESH_S", 0.01)
    ui = make_ui()
    ui._lock_screen()
    ui._show_settings(page=SettingsPage.ABOUT)
    task = asyncio.create_task(ui._run_about_page_refresh())
    try:
        for _ in range(3):
            ui._system_stats_snapshot()
            ui._system_info_snapshot()
            await asyncio.sleep(0.012)
            assert ui._about_load_task is None
        ui._screen_locked = False
        ui._apply_idle_stage(IdleStage.ACTIVE)
        ui._system_stats_snapshot()
        assert ui._about_load_task is not None
        await asyncio.wait_for(ui._about_load_task, 1)
        assert ui._system_stats_snapshot() is stats
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await ui.stop()


@pytest.mark.asyncio
async def test_expected_offline_is_info_once_and_real_errors_remain_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _FakeStatusProvider(
        error=PrinterStatusUnavailableError("Printer off", printer_not_found=True)
    )
    ui = make_ui(provider)
    caplog.set_level(logging.DEBUG, logger="instantlink_bridge.ui.controller")
    try:
        for _ in range(3):
            assert not await ui._refresh_printer_status_in_background(PRINTER)
        records = [
            r for r in caplog.records if r.message.startswith("ui.printer_status_unavailable ")
        ]
        assert len(records) == 1 and records[0].levelno == logging.INFO
        provider._error = RuntimeError("genuine failure")
        assert not await ui._refresh_printer_status_in_background(PRINTER)
        assert any(
            r.levelno == logging.WARNING and "genuine failure" in r.message for r in caplog.records
        )
        provider._error = None
        provider._snapshot = PrinterStatusSnapshot(5, 80, False)
        assert await ui._refresh_printer_status_in_background(PRINTER)
        provider._snapshot = replace(provider._snapshot, film_remaining=4)
        assert await ui._refresh_printer_status_in_background(PRINTER)
        changed = [r for r in caplog.records if r.message.startswith("ui.printer_status ")]
        assert len(changed) == 2 and all(r.levelno == logging.INFO for r in changed)
    finally:
        await ui.stop()


def test_native_offline_logging_stays_quiet_after_interval_but_errors_are_visible(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = instantlink.InstantLinkBackend()
    caplog.set_level(logging.DEBUG, logger="instantlink_bridge.ble.instantlink")
    absence = instantlink.InstantLinkPrinterNotFoundError("printer not found", code=-1)
    backend._log_status_failure(PRINTER.name, absence, disconnected=True)
    backend._last_status_failure_log_at = -float("inf")
    backend._log_status_failure(PRINTER.name, absence, disconnected=True)
    visible = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert len(visible) == 1 and visible[0].levelno == logging.INFO
    backend._log_status_failure(
        PRINTER.name,
        instantlink.InstantLinkBleError("real BLE failure", code=-3),
        disconnected=False,
    )
    assert any(
        r.levelno == logging.WARNING and "real BLE failure" in r.message for r in caplog.records
    )


def test_progress_logging_keeps_late_failure_and_stage_tracker_visible(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="instantlink_bridge.ble.instantlink")
    tracker = instantlink._ConnectStageTracker()
    emit = instantlink._connect_progress_logger(PRINTER.name, tracker)
    emit(0, None)
    emit(1, None)
    emit(10, b"no Instax printer found")
    assert not caplog.records
    assert tracker.max_stage == 1
    emit(2, b"matched")
    emit(5, None)
    emit(10, b"encrypted write failed")
    assert tracker.max_stage == 5
    assert any(
        "stage=failed" in r.message and "encrypted write failed" in r.message
        for r in caplog.records
    )
