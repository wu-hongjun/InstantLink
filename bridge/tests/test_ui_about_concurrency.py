from __future__ import annotations

import asyncio
from threading import Event

import pytest
from test_ui_controller import _FakeDisplay, _FakePairer, _FakeStatusProvider

from instantlink_bridge.config import BridgeConfig
from instantlink_bridge.system_info import SystemInfo
from instantlink_bridge.system_stats import SystemStatsSnapshot
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import UiAction, UiMode
from instantlink_bridge.ui.settings import SettingsPage

INFO = SystemInfo("IB-12345678", "0.1.17", "3.13.5", "5.82", "Debian 13")
STATS = SystemStatsSnapshot(12, 200, 463, 2, 32, 45)


def _ui() -> BridgeUi:
    return BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([]),
        status_provider=_FakeStatusProvider(),
    )


@pytest.mark.asyncio
async def test_about_collection_is_shared_and_navigation_survives_slow_version_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    calls = 0

    def read_info() -> SystemInfo:
        nonlocal calls
        calls += 1
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return INFO

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", read_info)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_stats", lambda _: STATS)
    ui = _ui()
    ui._show_settings(page=SettingsPage.ABOUT)
    collector = ui._about_load_task
    assert collector is not None
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        for _ in range(10):
            assert ui._system_info_snapshot().device_id == "…"
            ui._system_stats_snapshot()
            assert ui._about_load_task is collector
        await asyncio.wait_for(ui._handle_action(UiAction.BACK), 0.05)
        assert ui._settings_page is SettingsPage.SYSTEM
        display = ui._display
        assert isinstance(display, _FakeDisplay)
        render_count = len(display.snapshots)
        release.set()
        await asyncio.wait_for(collector, 0.5)
        assert calls == 1
        assert ui._system_info_snapshot() is INFO
        assert ui._system_stats_snapshot() is STATS
        assert len(display.snapshots) == render_count
        assert ui._settings_page is SettingsPage.SYSTEM
    finally:
        release.set()
        if not collector.done():
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)


@pytest.mark.asyncio
async def test_about_collector_updates_rows_only_while_viewing_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", lambda: INFO)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_stats", lambda _: STATS)
    ui = _ui()
    ui._show_settings(page=SettingsPage.ABOUT)
    assert ui._about_load_task is not None
    await ui._about_load_task
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert ui.snapshot.settings_title == "About"
    values = {row.label: row.value for row in ui.snapshot.settings_rows}
    assert values["Device ID"] == INFO.device_id
    assert values["BlueZ"] == "5.82"
    assert values["CPU"] == "12%"
    collector = ui._about_load_task
    for _ in range(3):
        assert ui._system_info_snapshot() is INFO
        assert ui._system_stats_snapshot() is STATS
    assert ui._about_load_task is collector


@pytest.mark.asyncio
async def test_about_collection_does_not_apply_after_ui_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def read_info() -> SystemInfo:
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return INFO

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", read_info)
    ui = _ui()
    ui._show_settings(page=SettingsPage.ABOUT)
    collector = ui._about_load_task
    assert collector is not None
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        ui._stopping = True
        display = ui._display
        assert isinstance(display, _FakeDisplay)
        renders = len(display.snapshots)
        release.set()
        await asyncio.wait_for(collector, 0.5)
        assert ui._system_info is None
        assert ui._cached_system_stats is None
        assert len(display.snapshots) == renders
    finally:
        release.set()
        if not collector.done():
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)


def test_cached_about_inspection_without_event_loop_does_not_collect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_read() -> SystemInfo:
        raise AssertionError("snapshot inspection must not run a collector")

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", unexpected_read)
    ui = _ui()
    assert ui._system_info_snapshot().device_id == "…"
    assert ui._system_stats_snapshot().cpu_percent is None
    assert ui._about_load_task is None


@pytest.mark.asyncio
async def test_about_detail_opened_while_loading_gets_value_without_replacing_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def read_info() -> SystemInfo:
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return INFO

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", read_info)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_stats", lambda _: STATS)
    ui = _ui()
    ui._show_settings(page=SettingsPage.ABOUT)
    collector = ui._about_load_task
    assert collector is not None
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        await ui._handle_action(UiAction.SELECT)
        assert ui.snapshot.mode is UiMode.HELP_DIALOG
        assert ui.snapshot.help_dialog_title == "Device ID"
        assert ui.snapshot.help_dialog_body == "…"
        release.set()
        await asyncio.wait_for(collector, 0.5)
        assert ui.snapshot.mode is UiMode.HELP_DIALOG
        assert ui.snapshot.help_dialog_title == "Device ID"
        assert ui.snapshot.help_dialog_body == INFO.device_id
    finally:
        release.set()
        if not collector.done():
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)


@pytest.mark.asyncio
async def test_pairing_qr_uses_real_identity_without_waiting_for_about_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from instantlink_bridge.config import SyncConfig, SyncDestination

    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def read_info() -> SystemInfo:
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return INFO

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", read_info)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_stats", lambda _: STATS)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_device_id", lambda: "IB-REALID")
    monkeypatch.setattr(
        "instantlink_bridge.sync.server.load_or_create_sync_token", lambda _: "token"
    )
    ui = _ui()
    ui._config = BridgeConfig(sync=SyncConfig(destination=SyncDestination.IPHONE))
    ui._sync_service_state = "listening"
    ui._show_settings(page=SettingsPage.ABOUT)
    collector = ui._about_load_task
    assert collector is not None
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        await asyncio.wait_for(ui._show_sync_pairing(return_home=True), 0.5)
        assert ui.snapshot.mode is UiMode.SYNC_PAIRING
        assert "device=IB-REALID" in (ui.snapshot.sync_qr_payload or "")
        assert ui._system_info is None
    finally:
        release.set()
        await asyncio.wait_for(collector, 0.5)
        ui._exit_sync_pairing()


@pytest.mark.asyncio
async def test_identity_timeout_reuses_one_reader_and_shows_existing_pairing_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from instantlink_bridge.config import SyncConfig, SyncDestination

    calls = 0
    release = Event()

    def read_identity() -> str:
        nonlocal calls
        calls += 1
        release.wait(timeout=1)
        return "IB-REALID"

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_device_id", read_identity)
    monkeypatch.setattr("instantlink_bridge.ui.controller.SYSTEM_IDENTITY_TIMEOUT_S", 0.01)
    ui = _ui()
    ui._config = BridgeConfig(sync=SyncConfig(destination=SyncDestination.IPHONE))
    ui._sync_service_state = "listening"
    try:
        await ui._show_sync_pairing(return_home=True)
        reader = ui._identity_load_task
        assert reader is not None
        assert not reader.done()
        assert ui.snapshot.mode is UiMode.HELP_DIALOG
        assert ui.snapshot.help_dialog_body == "Pairing unavailable"
        assert ui.snapshot.sync_qr_payload is None
        await ui._show_sync_pairing(return_home=True)
        assert ui._identity_load_task is reader
        assert calls == 1
        release.set()
        await asyncio.wait_for(reader, 0.5)
        assert ui._device_id == "IB-REALID"
        assert ui.snapshot.mode is UiMode.HELP_DIALOG
    finally:
        release.set()
        if ui._identity_load_task is not None:
            await asyncio.wait_for(ui._identity_load_task, 0.5)


@pytest.mark.asyncio
async def test_about_version_and_metrics_start_without_waiting_for_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_started = Event()
    metrics_started = Event()

    def read_info() -> SystemInfo:
        version_started.set()
        assert metrics_started.wait(timeout=0.5), "metrics waited for the version probe"
        return INFO

    def read_stats(_sampler: object) -> SystemStatsSnapshot:
        metrics_started.set()
        assert version_started.wait(timeout=0.5), "version probe waited for metrics"
        return STATS

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", read_info)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_stats", read_stats)
    ui = _ui()
    ui._show_settings(page=SettingsPage.ABOUT)
    assert ui._about_load_task is not None
    await asyncio.wait_for(ui._about_load_task, 1)
    assert ui._system_info is INFO
    assert ui._cached_system_stats is STATS


@pytest.mark.asyncio
async def test_cpu_warmup_blocks_only_metrics_not_about_version_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_started = asyncio.Event()
    warmup = asyncio.Event()
    metrics_started = Event()
    loop = asyncio.get_running_loop()

    def read_info() -> SystemInfo:
        loop.call_soon_threadsafe(version_started.set)
        return INFO

    def read_stats(_sampler: object) -> SystemStatsSnapshot:
        metrics_started.set()
        return STATS

    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_info", read_info)
    monkeypatch.setattr("instantlink_bridge.ui.controller.read_system_stats", read_stats)
    ui = _ui()
    ui._cpu_sampler_task = asyncio.create_task(warmup.wait())
    ui._show_settings(page=SettingsPage.ABOUT)
    collector = ui._about_load_task
    assert collector is not None
    try:
        await asyncio.wait_for(version_started.wait(), 0.5)
        assert not metrics_started.is_set()
        warmup.set()
        await asyncio.wait_for(collector, 0.5)
        assert metrics_started.is_set()
        assert ui._system_info is INFO
        assert ui._cached_system_stats is STATS
    finally:
        warmup.set()
        await ui._cpu_sampler_task
        if not collector.done():
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
