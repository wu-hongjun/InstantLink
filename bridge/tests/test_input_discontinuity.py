from __future__ import annotations

import asyncio
import os
from contextlib import suppress

import pytest
from test_ui_input import _edge_pipe, _event, _gpiozero
from test_ui_routing import _ui

from instantlink_bridge.ui import gpio_edges
from instantlink_bridge.ui.input import GpioUiInput
from instantlink_bridge.ui.models import UiAction, UiButtonPress, UiInputEvent, UiMode


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["edges", "gpiozero", "remote"])
async def test_overflow_relocks_before_accepting_a_new_unlock_sequence(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._lock_screen()
    await ui._begin_unlock("gpio:21")
    ui._advance_unlock("gpio:21")
    ui._actions = asyncio.Queue[UiInputEvent](maxsize=1)
    ui._actions.put_nowait(UiButtonPress(UiAction.SELECT, "gpio:21"))
    gpio = GpioUiInput()
    write_fd: int | None = None
    if backend == "edges":
        _, write_fd = _edge_pipe(monkeypatch)
        gpio.start(ui._actions, asyncio.get_running_loop())
        os.write(write_fd, _event(20, 1))
        gpio._read_edges()
    elif backend == "gpiozero":
        _, buttons, _ = _gpiozero(monkeypatch)
        gpio._start_gpiozero(ui._actions, asyncio.get_running_loop())
        callback = buttons[6].when_pressed
        assert callback is not None
        callback()
        await asyncio.sleep(0)
    else:
        assert not ui.inject_action(UiAction.BACK)
    runner = asyncio.create_task(ui._run_actions())
    try:
        await asyncio.wait_for(ui._actions.join(), 1)
        assert ui._screen_locked and not ui._unlocking
        for count in (1, 2, 3):
            ui._actions.put_nowait(UiButtonPress(UiAction.SELECT, "gpio:21"))
            await asyncio.wait_for(ui._actions.join(), 1)
            assert ui._screen_locked is (count < 3)
        assert ui.snapshot.mode is UiMode.PRINTER_SEARCHING
    finally:
        gpio.close()
        if write_fd is not None:
            os.close(write_fd)
        runner.cancel()
        with suppress(asyncio.CancelledError):
            await runner
        await ui.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("resync_fails", [False, True])
async def test_kernel_sequence_gap_relocks_even_without_application_overflow(
    monkeypatch: pytest.MonkeyPatch,
    resync_fails: bool,
) -> None:
    _, write_fd = _edge_pipe(monkeypatch)
    ui = _ui(UiMode.PRINTER_SEARCHING, saved=True, three_presses=True)
    ui._lock_screen()
    gpio = GpioUiInput()
    gpio.start(ui._actions, asyncio.get_running_loop())
    runner = asyncio.create_task(ui._run_actions())
    try:
        os.write(
            write_fd,
            _event(21, 1) + _event(21, 2, edge=1) + _event(21, 3) + _event(21, 4, edge=1),
        )
        await asyncio.sleep(0.01)
        await asyncio.wait_for(ui._actions.join(), 1)
        assert ui.snapshot.unlock_presses == 2
        monkeypatch.setattr("instantlink_bridge.ui.input.time.monotonic_ns", lambda: 2000)
        buttons = None
        if resync_fails:
            _, buttons, _ = _gpiozero(monkeypatch)

            def fail(*_args: object) -> int:
                raise OSError("resync failed")

            monkeypatch.setattr(gpio_edges, "read_levels", fail)
        else:
            monkeypatch.setattr(gpio_edges, "read_levels", lambda *_: 255)
        os.write(write_fd, _event(20, 6, edge=1, timestamp=900))
        await asyncio.sleep(0.01)
        await asyncio.wait_for(ui._actions.join(), 1)
        assert ui._screen_locked and not ui._unlocking
        if buttons is None:
            os.write(write_fd, _event(21, 7, timestamp=2100))
        else:
            callback = buttons[5].when_pressed
            assert callback is not None
            callback()
        await asyncio.sleep(0.01)
        await asyncio.wait_for(ui._actions.join(), 1)
        assert ui._screen_locked and ui.snapshot.unlock_presses == 1
    finally:
        gpio.close()
        os.close(write_fd)
        runner.cancel()
        with suppress(asyncio.CancelledError):
            await runner
        await ui.stop()
