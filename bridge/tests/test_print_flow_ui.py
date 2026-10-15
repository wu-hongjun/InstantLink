from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_ui_controller import (
    _FakeDisplay,
    _FakePairer,
    _FakeStatusProvider,
    _unused_wifi_mode_setter,
)

from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig, SyncConfig, SyncDestination
from instantlink_bridge.imaging.pipeline import PrintEdit
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiMode
from instantlink_bridge.ui.settings import SettingsPage


def make_ui(display: _FakeDisplay) -> BridgeUi:
    return BridgeUi(
        BridgeConfig(),
        display=display,
        input_device=NullInput(),
        pairer=_FakePairer([]),
        wifi_mode_setter=_unused_wifi_mode_setter,
    )


@pytest.mark.asyncio
async def test_receipt_records_photo_without_a_separate_screen_or_timer(tmp_path: Path) -> None:
    display = _FakeDisplay()
    ui = make_ui(display)
    ui._snapshot = ui._build_snapshot(mode=UiMode.READY)
    await ui.image_received(ReceivedImage(tmp_path / "photo.jpg", "camera"))
    assert ui.live_snapshot.mode is UiMode.READY
    assert ui.live_snapshot.last_image_name == "photo.jpg"
    assert display.snapshots == []
    assert ui._image_reset_task is None


@pytest.mark.asyncio
async def test_immediate_print_has_one_initial_connecting_frame(tmp_path: Path) -> None:
    display = _FakeDisplay()
    ui = make_ui(display)
    received = ReceivedImage(tmp_path / "photo.jpg", "camera")
    await ui.image_received(received)
    assert await ui.await_print_confirmation(received, timeout_s=0) == PrintEdit()
    assert display.snapshots == []
    await ui.printing_started(received)
    assert len(display.snapshots) == 1
    assert display.snapshots[0].mode is UiMode.PRINTING
    assert display.snapshots[0].print_title == "Connecting"
    assert display.snapshots[0].print_detail is None
    assert display.snapshots[0].print_progress_percent is None


@pytest.mark.asyncio
async def test_completion_timer_does_not_replace_settings_opened_by_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    display = _FakeDisplay()
    ui = make_ui(display)
    ui._snapshot = ui._build_snapshot(mode=UiMode.PRINT_COMPLETE)
    ui._show_settings(page=SettingsPage.POST)
    monkeypatch.setattr("instantlink_bridge.ui.controller.RETURN_HOME_DELAY_S", 0)
    await ui._return_home_after_print_complete()
    assert ui.live_snapshot.mode is UiMode.SETTINGS
    assert ui._settings_page is SettingsPage.POST


@pytest.mark.asyncio
async def test_receipt_cancels_previous_completion_timer(tmp_path: Path) -> None:
    display = _FakeDisplay()
    ui = make_ui(display)
    timer = asyncio.create_task(asyncio.sleep(100))
    ui._image_reset_task = timer
    await ui.image_received(ReceivedImage(tmp_path / "next.jpg", "camera"))
    with pytest.raises(asyncio.CancelledError):
        await timer
    assert ui._image_reset_task is None


@pytest.mark.asyncio
async def test_lock_while_printing_preserves_operational_print_state(tmp_path: Path) -> None:
    display = _FakeDisplay()
    ui = make_ui(display)
    await ui.printing_started(ReceivedImage(tmp_path / "photo.jpg", "camera"))
    await ui._handle_action(UiAction.BACK)
    assert ui._screen_locked
    assert ui.live_snapshot.mode is UiMode.PRINTING
    assert ui.live_snapshot.print_title == "Connecting"


@pytest.mark.asyncio
async def test_no_film_guidance_has_no_timer_that_replaces_user_navigation(tmp_path: Path) -> None:
    display = _FakeDisplay()
    ui = make_ui(display)
    ui._snapshot = replace(ui._snapshot, film_remaining=0)
    assert (
        await ui.await_print_confirmation(
            ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=0
        )
        is None
    )
    assert ui.live_snapshot.mode is UiMode.NO_FILM
    assert ui._image_reset_task is None
    await ui._handle_action(UiAction.SELECT)
    assert ui.live_snapshot.mode is UiMode.SETTINGS


@pytest.mark.asyncio
async def test_sync_failure_keeps_error_visible_without_restarting_printer_polling() -> None:
    display = _FakeDisplay()
    provider = _FakeStatusProvider()
    ui = BridgeUi(
        BridgeConfig(sync=SyncConfig(destination=SyncDestination.IPHONE)),
        display=display,
        input_device=NullInput(),
        pairer=_FakePairer([]),
        status_provider=provider,
        wifi_mode_setter=_unused_wifi_mode_setter,
    )
    ui._snapshot = replace(ui.live_snapshot, paired_printer=PairedPrinter("AA:BB", "INSTAX-1"))
    # A mode change can leave an old poll pending; the guard must cancel it too.
    poll = asyncio.create_task(asyncio.sleep(100))
    ui._status_task = poll
    await ui.print_failed("Sync unavailable")
    with pytest.raises(asyncio.CancelledError):
        await poll
    assert ui.live_snapshot.mode is UiMode.ERROR
    assert ui.live_snapshot.message == "Sync unavailable"
    assert ui._status_task is None
    assert provider.fetch_calls == 0
