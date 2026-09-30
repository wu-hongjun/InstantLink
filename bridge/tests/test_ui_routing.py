"""User-facing key, wake and saved-Printer recovery regressions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
from test_ui_controller import _FakeDisplay, _FakePairer, _FakeStatusProvider

from instantlink_bridge.config import BridgeConfig
from instantlink_bridge.power.monitor import IdleStage
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiMode
from instantlink_bridge.ui.settings import SettingKey, SettingsPage


def _ui(mode: UiMode, *, saved: bool = False) -> BridgeUi:
    printer = PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-12345678") if saved else None
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([printer] if printer else []),
        status_provider=_FakeStatusProvider(),
    )
    ui._snapshot = ui._build_snapshot(mode=mode, paired_printer=printer)
    return ui


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [UiMode.NEEDS_PAIRING, UiMode.PAIR_FAILED, UiMode.ERROR])
async def test_settings_access_does_not_require_printer(mode: UiMode) -> None:
    ui = _ui(mode)
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert ui._settings_page is SettingsPage.MAIN


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [UiAction.HELP, UiAction.PAIR])
async def test_ready_key3_opens_post_without_pairing(action: UiAction) -> None:
    ui = _ui(UiMode.READY, saved=True)
    ui._start_pairing = AsyncMock()
    await ui._handle_action(action)
    assert ui._settings_page is SettingsPage.POST
    ui._start_pairing.assert_not_awaited()


@pytest.mark.asyncio
async def test_printing_lock_and_wake_preserve_job() -> None:
    ui = _ui(UiMode.PRINTING, saved=True)
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.idle_stage == "screen_off"
    assert ui.snapshot.mode is UiMode.PRINTING
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.idle_stage == "active"
    assert ui.snapshot.mode is UiMode.PRINTING


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(UiAction))
async def test_automatic_dark_first_action_only_wakes(action: UiAction) -> None:
    ui = _ui(UiMode.READY, saved=True)
    ui._apply_idle_stage(IdleStage.SCREEN_OFF)
    await ui._handle_action(action)
    assert ui.snapshot.mode is UiMode.READY
    assert ui.snapshot.idle_stage == "active"


@pytest.mark.asyncio
async def test_queue_remembers_darkness_before_activity_callback_wakes() -> None:
    ui = _ui(UiMode.NEEDS_PAIRING)
    ui._apply_idle_stage(IdleStage.SCREEN_OFF)

    async def activity() -> None:
        ui._apply_idle_stage(IdleStage.ACTIVE)

    ui._power_activity_callback = activity
    task = asyncio.create_task(ui._run_actions())
    try:
        ui.inject_action(UiAction.SELECT)
        await asyncio.wait_for(ui._actions.join(), timeout=1)
        assert ui.snapshot.mode is UiMode.NEEDS_PAIRING
        ui.inject_action(UiAction.SELECT)
        await asyncio.wait_for(ui._actions.join(), timeout=1)
        assert ui.snapshot.mode is UiMode.SETTINGS
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [UiMode.PRINTER_OFFLINE, UiMode.PRINTER_SEARCHING, UiMode.ERROR])
async def test_saved_printer_check_coalesces_without_pairing_or_restarting_poll(
    mode: UiMode,
) -> None:
    ui = _ui(mode, saved=True)
    ui._start_pairing = AsyncMock()
    ui._schedule_printer_status_refresh = AsyncMock()
    poll = asyncio.create_task(asyncio.Event().wait())
    ui._status_task = poll
    try:
        await ui._handle_action(UiAction.PAIR)
        await ui._handle_action(UiAction.HELP)
        assert ui._printer_check_requested.is_set()
        assert ui._status_task is poll
        ui._start_pairing.assert_not_awaited()
        ui._schedule_printer_status_refresh.assert_not_awaited()
    finally:
        poll.cancel()
        with suppress(asyncio.CancelledError):
            await poll


@pytest.mark.asyncio
async def test_picker_help_preserves_focused_option_and_picker() -> None:
    ui = _ui(UiMode.READY, saved=True)
    ui._show_settings(page=SettingsPage.TRANSFORM)
    ui._show_setting_picker(SettingKey.JPEG_QUALITY)
    await ui._handle_action(UiAction.DOWN)
    index = ui.snapshot.selected_index
    rows = ui.snapshot.settings_rows
    await ui._handle_action(UiAction.HELP)
    assert ui.snapshot.mode is UiMode.HELP_DIALOG
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert ui.snapshot.selected_index == index
    assert ui.snapshot.settings_rows == rows
    assert ui._settings_picker_key is SettingKey.JPEG_QUALITY


@pytest.mark.asyncio
async def test_gpio_key3_hold_has_no_hidden_pair_or_release_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    from instantlink_bridge.ui.input import KEY3, GpioUiInput

    buttons: dict[int, SimpleNamespace] = {}

    class PinFactory:
        pass

    def button(pin: int, **_kwargs: object) -> SimpleNamespace:
        instance = SimpleNamespace(
            when_pressed=None, when_held=None, when_released=None, close=lambda: None
        )
        buttons[pin] = instance
        return instance

    monkeypatch.setitem(
        sys.modules,
        "gpiozero",
        SimpleNamespace(Button=button, Device=SimpleNamespace(pin_factory=PinFactory())),
    )
    monkeypatch.setitem(
        sys.modules, "gpiozero.pins.lgpio", SimpleNamespace(LGPIOFactory=PinFactory)
    )
    queue: asyncio.Queue[UiAction] = asyncio.Queue()
    gpio = GpioUiInput()
    gpio.start(queue, asyncio.get_running_loop())
    buttons[KEY3].when_pressed()
    await asyncio.sleep(0)
    assert queue.get_nowait() is UiAction.HELP
    assert buttons[KEY3].when_held is None
    assert buttons[KEY3].when_released is None
    assert queue.empty()
    gpio.close()


@pytest.mark.asyncio
async def test_reconnect_wakes_long_retry_wait_and_checks_saved_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from instantlink_bridge.ui import controller
    from instantlink_bridge.ui.status import PrinterStatusUnavailableError

    monkeypatch.setattr(controller, "MIN_OFFLINE_SEARCH_GAP_S", 0.01)
    ui = _ui(UiMode.PRINTER_OFFLINE, saved=True)
    saved = ui.snapshot.paired_printer
    assert saved is not None
    checked: list[PairedPrinter] = []
    first = asyncio.Event()
    second = asyncio.Event()

    async def fetch(printer: PairedPrinter) -> None:
        checked.append(printer)
        (first if len(checked) == 1 else second).set()
        raise PrinterStatusUnavailableError("Printer is off")

    provider = _FakeStatusProvider()
    provider.fetch = fetch  # type: ignore[method-assign, assignment]
    ui._status_provider = provider
    await ui._schedule_printer_status_refresh()
    try:
        await asyncio.wait_for(first.wait(), timeout=1)
        # Let the normal 30s retry wait begin, then request an immediate check.
        await asyncio.sleep(0.02)
        await ui._handle_action(UiAction.HELP)
        await asyncio.wait_for(second.wait(), timeout=1)
        assert checked == [saved, saved]
        assert ui.snapshot.paired_printer == saved
        assert provider.close_cached_calls == 0
        assert ui._pairer.saved_selected is None  # type: ignore[attr-defined]
    finally:
        task = ui._status_task
        await ui._cancel_status_refresh()
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [UiMode.IMAGE_RECEIVED, UiMode.PRINT_COMPLETE])
async def test_transient_photo_home_key2_locks_as_caption_promises(mode: UiMode) -> None:
    ui = _ui(mode, saved=True)
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.mode is mode
    assert ui.snapshot.idle_stage == "screen_off"
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is mode
    assert ui.snapshot.idle_stage == "active"


@pytest.mark.asyncio
async def test_film_reload_during_guidance_returns_to_current_readiness() -> None:
    from instantlink_bridge.ui.status import PrinterStatusSnapshot

    ui = _ui(UiMode.NO_FILM, saved=True)
    printer = ui.snapshot.paired_printer
    assert printer is not None
    ui._camera_receive_ready = True
    await ui._handle_action(UiAction.HELP)
    assert ui.snapshot.mode is UiMode.HELP_DIALOG
    ui._apply_printer_status(
        printer, PrinterStatusSnapshot(film_remaining=10, battery=90, is_charging=False)
    )
    assert ui.snapshot.mode is UiMode.HELP_DIALOG
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.mode is UiMode.READY
    assert ui.snapshot.film_remaining == 10


@pytest.mark.asyncio
async def test_main_mode_help_explains_print_and_sync_and_preserves_selection() -> None:
    ui = _ui(UiMode.NEEDS_PAIRING)
    ui._show_settings(page=SettingsPage.MAIN)
    for _ in range(3):
        await ui._handle_action(UiAction.DOWN)
    await ui._handle_action(UiAction.HELP)
    assert ui.snapshot.mode is UiMode.HELP_DIALOG
    body = ui.snapshot.help_dialog_body or ""
    assert "Print or sync" in body
    assert "Network" in body
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.selected_index == 3
    assert ui._settings_page is SettingsPage.MAIN
