"""User-facing key, wake and saved-Printer recovery regressions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
from test_ui_controller import _FakeDisplay, _FakePairer, _FakeStatusProvider

from instantlink_bridge.config import BridgeConfig, UiConfig
from instantlink_bridge.power.monitor import IdleStage
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiButtonPress, UiMode
from instantlink_bridge.ui.settings import SettingKey, SettingsPage


def _ui(mode: UiMode, *, saved: bool = False, three_presses: bool = False) -> BridgeUi:
    printer = PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-12345678") if saved else None
    ui = BridgeUi(
        BridgeConfig(ui=UiConfig(unlock_requires_three_presses=three_presses)),
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
@pytest.mark.parametrize(
    "pin,action", [(16, UiAction.HELP), (21, UiAction.SELECT), (13, UiAction.SELECT)]
)
async def test_gpio_button_emits_identity_without_hold_or_release_action(
    monkeypatch: pytest.MonkeyPatch,
    pin: int,
    action: UiAction,
) -> None:
    import sys
    from types import SimpleNamespace

    from instantlink_bridge.ui.input import GpioUiInput

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
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio = GpioUiInput()
    gpio.start(queue, asyncio.get_running_loop())
    buttons[pin].when_pressed()
    await asyncio.sleep(0)
    assert queue.get_nowait() == UiButtonPress(action, f"gpio:{pin}")
    assert buttons[pin].when_held is None
    assert buttons[pin].when_released is None
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


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(UiAction))
async def test_three_press_unlock_consumes_each_key_and_then_accepts_actions(
    action: UiAction,
) -> None:
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._lock_screen()
    for presses in (1, 2):
        await ui._handle_action(action)
        assert ui.snapshot.mode is UiMode.UNLOCKING
        assert ui.snapshot.unlock_presses == presses
        assert ui.snapshot.unlock_required == 3
        assert ui._snapshot.mode is UiMode.PRINTER_SEARCHING
        assert ui.snapshot.idle_stage == "active"
    await ui._handle_action(action)
    assert ui.snapshot.mode is UiMode.PRINTER_SEARCHING
    assert ui.snapshot.idle_stage == "active"
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert ui._unlock_timeout_task is None


@pytest.mark.asyncio
async def test_unlock_overlay_preserves_incoming_printer_and_photo_state() -> None:
    from pathlib import Path

    from instantlink_bridge.camera.ftp import ReceivedImage
    from instantlink_bridge.ui.status import PrinterStatusSnapshot

    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    printer = ui.snapshot.paired_printer
    assert printer is not None
    ui._lock_screen()
    await ui._handle_action(UiAction.HELP)
    ui._apply_printer_status(
        printer, PrinterStatusSnapshot(film_remaining=7, battery=90, is_charging=False)
    )
    assert ui.snapshot.mode is UiMode.UNLOCKING
    assert ui.snapshot.film_remaining == 7
    received = ReceivedImage(path=Path("/tmp/photo.jpg"), remote_ip="192.168.8.2")
    await ui.printing_started(received)
    assert ui.snapshot.mode is UiMode.UNLOCKING
    assert ui._snapshot.mode is UiMode.PRINTING
    await ui._handle_action(UiAction.HELP)
    await ui._handle_action(UiAction.HELP)
    assert ui.snapshot.mode is UiMode.PRINTING
    assert ui.snapshot.last_image_name == "photo.jpg"
    assert ui._unlock_timeout_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first,second", [(UiAction.SELECT, UiAction.BACK), (UiAction.HELP, UiAction.UP)]
)
async def test_different_unlock_button_restarts_count_without_extending_timeout(
    first: UiAction, second: UiAction
) -> None:
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._lock_screen()
    await ui._handle_action(first)
    timer = ui._unlock_timeout_task
    await ui._handle_action(first)
    assert ui.snapshot.unlock_presses == 2
    await ui._handle_action(second)
    assert ui.snapshot.mode is UiMode.UNLOCKING
    assert ui.snapshot.unlock_presses == 1
    assert ui._unlock_timeout_task is timer
    await ui._handle_action(second)
    assert ui.snapshot.unlock_presses == 2
    await ui._handle_action(second)
    assert ui.snapshot.mode is UiMode.PRINTER_SEARCHING
    assert ui._unlock_button_id is None
    assert ui._unlock_timeout_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("other_button", ["gpio:13", "remote:select"])
async def test_select_buttons_and_remote_select_remain_distinct_in_input_queue(
    other_button: str,
) -> None:
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._lock_screen()
    runner = asyncio.create_task(ui._run_actions())
    try:
        for button in ("gpio:21", other_button, "gpio:21"):
            if button == "remote:select":
                assert ui.inject_action(UiAction.SELECT)
            else:
                ui._actions.put_nowait(UiButtonPress(UiAction.SELECT, button))
        await asyncio.wait_for(ui._actions.join(), timeout=1)
        assert ui.snapshot.mode is UiMode.UNLOCKING
        assert ui.snapshot.unlock_presses == 1
        for _ in range(2):
            ui._actions.put_nowait(UiButtonPress(UiAction.SELECT, "gpio:21"))
        await asyncio.wait_for(ui._actions.join(), timeout=1)
        assert ui.snapshot.mode is UiMode.PRINTER_SEARCHING
        ui._actions.put_nowait(UiButtonPress(UiAction.SELECT, "gpio:21"))
        await asyncio.wait_for(ui._actions.join(), timeout=1)
        assert ui.snapshot.mode is UiMode.SETTINGS
    finally:
        ui._cancel_unlock_timeout()
        runner.cancel()
        with suppress(asyncio.CancelledError):
            await runner


@pytest.mark.asyncio
async def test_incomplete_unlock_expires_to_dark_idle_and_resets_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from instantlink_bridge.power.performance import CpuPerformanceController
    from instantlink_bridge.ui import controller

    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)

    monkeypatch.setattr(controller, "UNLOCK_TIMEOUT_S", 0.02)
    cpu = CpuPerformanceController(setter)
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._cpu_performance = cpu
    await cpu.start()
    ui._lock_screen()
    await cpu.start()
    assert modes[-1] == "powersave"
    await ui._handle_action(UiAction.SELECT)
    assert modes[-1] == "performance"
    timer = ui._unlock_timeout_task
    assert timer is not None
    await timer
    await cpu.start()
    assert ui.snapshot.idle_stage == "screen_off"
    assert ui.snapshot.mode is UiMode.PRINTER_SEARCHING
    assert modes[-1] == "powersave"
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.UNLOCKING
    assert ui.snapshot.unlock_presses == 1
    ui._lock_screen()
    await cpu.close()


@pytest.mark.asyncio
async def test_disabled_gate_repaints_identical_prelock_home() -> None:
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True)
    ui._render()
    display = ui._display
    assert isinstance(display, _FakeDisplay)
    before = len(display.snapshots)
    ui._lock_screen()
    await ui._handle_action(UiAction.SELECT)
    assert len(display.snapshots) == before + 1
    assert display.snapshots[-1].mode is UiMode.PRINTER_SEARCHING


@pytest.mark.asyncio
async def test_first_press_finishes_cpu_wake_before_third_queued_press() -> None:
    from instantlink_bridge.power.performance import CpuPerformanceController

    assert BridgeConfig().ui.unlock_requires_three_presses is True
    warming = asyncio.Event()
    warmed = asyncio.Event()
    hold_wake = False

    async def setter(mode: str) -> None:
        if mode == "performance" and hold_wake:
            warming.set()
            await warmed.wait()

    cpu = CpuPerformanceController(setter)
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._cpu_performance = cpu
    await cpu.start()
    ui._lock_screen()
    await cpu.start()
    hold_wake = True
    actions = asyncio.create_task(ui._run_actions())
    try:
        for _ in range(3):
            ui.inject_action(UiAction.SELECT)
        await asyncio.wait_for(warming.wait(), timeout=1)
        assert ui.snapshot.mode is UiMode.UNLOCKING
        assert ui.snapshot.unlock_presses == 1
        warmed.set()
        await asyncio.wait_for(ui._actions.join(), timeout=1)
        assert ui.snapshot.mode is UiMode.PRINTER_SEARCHING
        assert not ui._screen_locked
        assert ui._unlock_timeout_task is None
    finally:
        warmed.set()
        actions.cancel()
        with suppress(asyncio.CancelledError):
            await actions
        ui._cancel_unlock_timeout()
        await cpu.close()


@pytest.mark.asyncio
async def test_system_unlock_toggle_changes_next_wake() -> None:
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._show_settings(page=SettingsPage.SYSTEM)
    keys = ui._visible_keys_for_page(SettingsPage.SYSTEM)
    for _ in range(keys.index(SettingKey.UNLOCK_THREE_PRESSES)):
        await ui._handle_action(UiAction.DOWN)
    assert ui.snapshot.settings_rows[ui.snapshot.selected_index].label == "Unlock: 3 presses"
    await ui._handle_action(UiAction.SELECT)
    await ui._handle_action(UiAction.DOWN)
    await ui._handle_action(UiAction.SELECT)
    assert ui._config.ui.unlock_requires_three_presses is False
    ui._lock_screen()
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert not ui._screen_locked
    assert ui._unlock_timeout_task is None
