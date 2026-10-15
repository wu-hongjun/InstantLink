from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_ui_controller import _FakePairer, _FakeStatusProvider
from test_ui_render import _drawn_texts
from test_ui_settings_streamline import _ui

from instantlink_bridge.ble.instantlink import InstantLinkBackend, InstantLinkStatus
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.config import FontSize
from instantlink_bridge.power.monitor import IdleStage
from instantlink_bridge.ui.i18n import t
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiMode
from instantlink_bridge.ui.render import error_copy_for_message
from instantlink_bridge.ui.settings import SETTINGS_BY_PAGE, SettingKey, SettingsPage
from instantlink_bridge.ui.status import (
    InstantLinkPrinterStatusProvider,
    PrinterStatusSnapshot,
    PrinterStatusUnavailableError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dark", "attempt_s", "starts"),
    [
        (False, 0.2, [0, 1, 2, 3]),
        (False, 1.0, [0, 1.05, 2.1, 3.15]),
        (False, 5.0, [0, 5.05, 10.1, 15.15]),
        (True, 0.2, [0, 30, 60, 90]),
        (True, 5.0, [0, 30, 60, 90]),
    ],
)
async def test_offline_poll_screen_policy_and_no_overlapping_slow_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dark: bool,
    attempt_s: float,
    starts: list[float],
) -> None:
    clock = [0.0]
    observed: list[float] = []
    policy: list[tuple[int, float]] = []

    class Provider(_FakeStatusProvider):
        def configure_discovery(self, *, scan_duration_s: int, retry_interval_s: float) -> None:
            policy.append((scan_duration_s, retry_interval_s))

        async def fetch(self, printer: PairedPrinter) -> PrinterStatusSnapshot:
            observed.append(clock[0])
            if len(observed) == len(starts):
                raise asyncio.CancelledError
            clock[0] += attempt_s
            raise PrinterStatusUnavailableError("not advertising", printer_not_found=True)

    async def wait_for(waiter: Coroutine[object, object, bool], duration: float) -> bool:
        waiter.close()
        clock[0] += duration
        raise TimeoutError

    ui = _ui(tmp_path)
    ui._status_provider = Provider()
    assert isinstance(ui._pairer, _FakePairer)
    ui._pairer.link_is_connected = False
    ui._idle_stage = IdleStage.SCREEN_OFF if dark else IdleStage.ACTIVE
    monkeypatch.setattr(ui, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    printer = ui.snapshot.paired_printer
    assert printer is not None
    with pytest.raises(asyncio.CancelledError):
        await ui._poll_printer_status(printer, ui._status_generation)
    assert observed == pytest.approx(starts)
    assert policy == [(5, 30.0) if dark else (1, 1.0)] * len(starts)


@pytest.mark.asyncio
async def test_lock_reschedules_awake_wait_to_thirty_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = _ui(tmp_path)
    clock = [0.2]
    waits: list[float] = []

    async def wait_for(waiter: Coroutine[object, object, bool], duration: float) -> bool:
        waiter.close()
        waits.append(duration)
        if len(waits) == 1:
            clock[0] = 0.5
            ui._lock_screen()
            return True
        clock[0] += duration
        raise TimeoutError

    monkeypatch.setattr(ui, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    await ui._wait_for_printer_poll(0.0, online=False, recovering=False)
    assert waits == pytest.approx([0.8, 29.5])
    assert clock[0] == 30.0


@pytest.mark.asyncio
async def test_first_unlock_press_interrupts_dark_wait_without_finishing_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = _ui(tmp_path)
    ui._lock_screen()
    ui._printer_check_requested.clear()
    clock = [0.2]

    async def wait_for(waiter: Coroutine[object, object, bool], duration: float) -> bool:
        waiter.close()
        assert duration == pytest.approx(29.8)
        clock[0] = 3.0
        await ui._begin_unlock("remote:select")
        return True

    monkeypatch.setattr(ui, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    try:
        await ui._wait_for_printer_poll(0.0, online=False, recovering=False)
        assert clock[0] == 3.0
        assert ui._unlocking and ui._screen_locked
        assert ui._unlock_presses == 1
        assert ui._printer_status_retry_delay(False) == 1.0
    finally:
        task = ui._unlock_timeout_task
        ui._cancel_unlock_timeout()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_manual_requests_preserve_a_single_minimum_scan_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = _ui(tmp_path)
    clock = [0.0]
    requests = [0.01, 0.02, 0.03]

    async def wait_for(waiter: Coroutine[object, object, bool], duration: float) -> bool:
        waiter.close()
        if requests:
            clock[0] = requests.pop(0)
            ui._printer_check_requested.set()
            return True
        clock[0] += duration
        raise TimeoutError

    monkeypatch.setattr(ui, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    await ui._wait_for_printer_poll(0.0, online=False, recovering=False)
    assert clock[0] == pytest.approx(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("opener", "title", "keys"),
    [
        (SettingKey.OPEN_FTP, "FTP", SETTINGS_BY_PAGE[SettingsPage.FTP]),
        (SettingKey.OPEN_WIFI, "Wi-Fi", SETTINGS_BY_PAGE[SettingsPage.WIFI]),
        (SettingKey.OPEN_IPHONE, "iPhone", SETTINGS_BY_PAGE[SettingsPage.IPHONE]),
        (SettingKey.OPEN_CONNECTIONS, "Connections", SETTINGS_BY_PAGE[SettingsPage.CONNECTIONS]),
    ],
)
async def test_network_submenu_navigation_restores_parent_cursor(
    tmp_path: Path, opener: SettingKey, title: str, keys: tuple[SettingKey, ...]
) -> None:
    ui = _ui(tmp_path)
    ui._show_settings(page=SettingsPage.MAIN)
    await ui._handle_action(UiAction.DOWN)
    await ui._handle_action(UiAction.SELECT)
    assert [row.label for row in ui.snapshot.settings_rows] == [
        "FTP",
        "Wi-Fi",
        "iPhone",
        "Connections",
    ]
    index = SETTINGS_BY_PAGE[SettingsPage.NETWORK].index(opener)
    for _ in range(index):
        await ui._handle_action(UiAction.DOWN)
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.settings_title == title
    assert ui._visible_keys_for_page(ui._settings_page) == keys
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.settings_title == "Network"
    assert ui.snapshot.selected_index == index
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.settings_title == "Settings"
    assert ui.snapshot.selected_index == 1


@pytest.mark.parametrize("font_size", list(FontSize))
@pytest.mark.parametrize("language", ["en", "zh-Hans"])
@pytest.mark.parametrize("mode", [UiMode.NO_FILM, UiMode.ERROR])
def test_empty_film_copy_is_readable_and_does_not_promote_test_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    font_size: FontSize,
    language: str,
    mode: UiMode,
) -> None:
    ui = _ui(tmp_path)
    snapshot = replace(
        ui.snapshot,
        mode=mode,
        message="No film",
        film_remaining=0,
        font_size=font_size.value,
        language=language,
    )
    texts = _drawn_texts(monkeypatch, snapshot)
    assert t("No film is left in the Printer.", language) in " ".join(texts)
    assert not any("No-film test" in text for text in texts)
    assert error_copy_for_message("No film")[2] == "Load a new film pack."


@pytest.mark.asyncio
async def test_discovery_budget_change_preserves_inflight_native_status() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    durations: list[int] = []

    class Backend:
        async def status(self, name: str, *, scan_duration_s: int) -> InstantLinkStatus:
            durations.append(scan_duration_s)
            started.set()
            await release.wait()
            return InstantLinkStatus(name, PrinterModel.SQUARE, 95, 0, False, 123)

    provider = InstantLinkPrinterStatusProvider(backend=cast(InstantLinkBackend, Backend()))
    printer = PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-12345678")
    provider.configure_discovery(scan_duration_s=1, retry_interval_s=1)
    fetch = asyncio.create_task(provider.fetch(printer))
    await started.wait()
    provider.configure_discovery(scan_duration_s=5, retry_interval_s=30)
    assert not fetch.done()
    release.set()
    first = await fetch
    second = await provider.fetch(printer)
    assert first == second
    assert first.film_remaining == 0 and first.model is PrinterModel.SQUARE
    assert durations == [1, 5]


@pytest.mark.parametrize("interval", [5, 15, 30, 60])
def test_discovery_help_localizes_screen_policy(interval: int) -> None:
    expected = f"亮屏时每秒搜索，熄屏时每 {interval} 秒搜索"  # noqa: RUF001
    assert (
        t(f"Searches every 1s with screen on; every {interval}s with screen off", "zh-Hans")
        == expected
    )


@pytest.mark.asyncio
async def test_screen_group_returns_to_system_without_executing_a_setting(tmp_path: Path) -> None:
    ui = _ui(tmp_path)
    ui._show_settings(page=SettingsPage.SYSTEM)
    assert [row.label for row in ui.snapshot.settings_rows] == [
        "Idle poweroff",
        "Screen",
        "Refresh status",
        "About",
    ]
    original = ui.config
    await ui._handle_action(UiAction.DOWN)
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.settings_title == "Screen"
    assert [row.label for row in ui.snapshot.settings_rows] == [
        "Unlock guard",
        "Appearance",
        "Text size",
        "Language",
    ]
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.settings_title == "System"
    assert ui.snapshot.selected_index == 1
    assert ui.config == original
