from __future__ import annotations

import asyncio
import ctypes
import fcntl
import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from instantlink_bridge.ui import gpio_edges
from instantlink_bridge.ui.input import ACTION_PINS, GpioUiInput, _enqueue
from instantlink_bridge.ui.models import UiAction, UiButtonPress


def _event(pin: int, sequence: int, *, edge: int = 2, timestamp: int = 1) -> bytes:
    return gpio_edges.GPIO_EVENT.pack(timestamp, edge, pin, sequence, 1, 0, 0, 0, 0, 0, 0)


def _edge_pipe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    levels: int = 255,
) -> tuple[int, int]:
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    monkeypatch.setattr(gpio_edges, "button_chip", lambda: Path("/dev/gpiochip0"))
    monkeypatch.setattr(gpio_edges, "request_edges", lambda *_args, **_kwargs: read_fd)
    monkeypatch.setattr(gpio_edges, "read_levels", lambda *_args: levels)
    return read_fd, write_fd


@pytest.mark.asyncio
async def test_edge_buttons_keep_all_mappings_and_one_action_per_press(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, write_fd = _edge_pipe(monkeypatch)
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio = GpioUiInput()
    gpio.start(queue, asyncio.get_running_loop())
    try:
        events = b""
        sequence = 0
        for pin in ACTION_PINS:
            # A held/duplicate falling edge cannot repeat a press; release is quiet.
            for edge in (2, 2, 1):
                sequence += 1
                events += _event(pin, sequence, edge=edge)
        os.write(write_fd, events)
        await asyncio.sleep(0.01)
        assert [queue.get_nowait() for _ in ACTION_PINS] == [
            UiButtonPress(action, f"gpio:{pin}") for pin, action in ACTION_PINS.items()
        ]
        assert queue.empty()
        assert not gpio._buttons
    finally:
        gpio.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_initially_held_key_requires_release_before_press(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, write_fd = _edge_pipe(monkeypatch, levels=255 & ~(1 << tuple(ACTION_PINS).index(21)))
    gpio = GpioUiInput()
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio.start(queue, asyncio.get_running_loop())
    try:
        os.write(write_fd, _event(21, 1) + _event(21, 2, edge=1) + _event(21, 3))
        await asyncio.sleep(0.01)
        assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
        assert queue.empty()
    finally:
        gpio.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_full_queue_does_not_stop_edges_or_repeat_held_press(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, write_fd = _edge_pipe(monkeypatch)
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue(maxsize=1)
    queue.put_nowait(UiAction.BACK)
    gpio = GpioUiInput()
    gpio.start(queue, asyncio.get_running_loop())
    try:
        os.write(write_fd, _event(21, 1))
        await asyncio.sleep(0.01)
        assert queue.get_nowait() is UiAction.BACK
        os.write(write_fd, _event(21, 2) + _event(21, 3, edge=1) + _event(21, 4))
        await asyncio.sleep(0.01)
        assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
        assert queue.empty()
        assert gpio._edge_fd is not None
    finally:
        gpio.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_sequence_gap_suppresses_uncertain_press_and_resumes_after_release(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, write_fd = _edge_pipe(monkeypatch)
    gpio = GpioUiInput()
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio.start(queue, asyncio.get_running_loop())
    monkeypatch.setattr("instantlink_bridge.ui.input.time.monotonic_ns", lambda: 1000)
    monkeypatch.setattr(gpio_edges, "read_levels", lambda *_args: 255 & ~(1 << 5))
    try:
        os.write(write_fd, _event(21, 3, timestamp=900) + _event(21, 4, timestamp=950))
        await asyncio.sleep(0.01)
        assert queue.empty()
        assert "ui.input_edge_gap" in caplog.text
        os.write(
            write_fd,
            _event(21, 5, edge=1, timestamp=1001) + _event(21, 6, timestamp=1002),
        )
        await asyncio.sleep(0.01)
        assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
        assert queue.empty()
    finally:
        gpio.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_sequence_wrap_is_not_an_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    _, write_fd = _edge_pipe(monkeypatch)
    gpio = GpioUiInput()
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio.start(queue, asyncio.get_running_loop())
    gpio._sequence = 0xFFFFFFFF
    try:
        os.write(write_fd, _event(21, 0))
        await asyncio.sleep(0.01)
        assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
        assert gpio._discard_events_until_ns == 0
    finally:
        gpio.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_interrupted_edge_read_retains_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    read_fd, write_fd = _edge_pipe(monkeypatch)
    gpio = GpioUiInput()
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio.start(queue, asyncio.get_running_loop())

    def interrupted(_fd: int, _size: int) -> bytes:
        raise InterruptedError

    try:
        with monkeypatch.context() as patch:
            patch.setattr("instantlink_bridge.ui.input.os.read", interrupted)
            gpio._read_edges()
        assert gpio._edge_fd == read_fd
        os.write(write_fd, _event(21, 1))
        await asyncio.sleep(0.01)
        assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
    finally:
        gpio.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_failed_initial_level_read_closes_owned_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = _edge_pipe(monkeypatch)

    def fail(*_args: object) -> int:
        raise OSError("level read failed")

    monkeypatch.setattr(gpio_edges, "read_levels", fail)
    gpio = GpioUiInput()
    try:
        with pytest.raises(OSError, match="level read failed"):
            gpio._start_edges(asyncio.Queue(), asyncio.get_running_loop())
        assert gpio._edge_fd is None
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        gpio.close()
        os.close(write_fd)


def test_failed_reader_registration_releases_request(monkeypatch: pytest.MonkeyPatch) -> None:
    read_fd, write_fd = _edge_pipe(monkeypatch)
    removed: list[int] = []

    def fail(_fd: int, _callback: object) -> None:
        raise NotImplementedError("no fd reader")

    loop = cast(
        asyncio.AbstractEventLoop,
        SimpleNamespace(add_reader=fail, remove_reader=removed.append),
    )
    gpio = GpioUiInput()
    try:
        with pytest.raises(NotImplementedError):
            gpio._start_edges(asyncio.Queue(), loop)
        assert removed == [read_fd]
        assert gpio._edge_fd is None
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        gpio.close()
        os.close(write_fd)


def _gpiozero(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shared: bool = True,
    fail_pin: int | None = None,
) -> tuple[SimpleNamespace, list[SimpleNamespace], list[object]]:
    closed_factories: list[object] = []
    buttons: list[SimpleNamespace] = []

    class Factory:
        def close(self) -> None:
            closed_factories.append(self)

    original_factory = Factory() if shared else object()
    device = SimpleNamespace(pin_factory=original_factory)

    def button(pin: int, **kwargs: object) -> SimpleNamespace:
        if pin == fail_pin:
            raise OSError("button setup failed")
        instance = SimpleNamespace(
            pin=pin,
            kwargs=kwargs,
            when_pressed=None,
            when_released=None,
            when_held=None,
            closed=False,
        )
        instance.close = lambda: setattr(instance, "closed", True)
        buttons.append(instance)
        return instance

    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(Button=button, Device=device))
    monkeypatch.setitem(sys.modules, "gpiozero.pins.lgpio", SimpleNamespace(LGPIOFactory=Factory))
    return device, buttons, closed_factories


@pytest.mark.asyncio
async def test_unsupported_kernel_uses_legacy_debounce_and_preserves_shared_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported() -> Path:
        raise OSError("unsupported kernel")

    monkeypatch.setattr(gpio_edges, "button_chip", unsupported)
    device, buttons, factories = _gpiozero(monkeypatch)
    original_factory = device.pin_factory
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio = GpioUiInput()
    gpio.start(queue, asyncio.get_running_loop())
    for button in buttons:
        assert button.kwargs == {
            "pull_up": True,
            "bounce_time": 0.05,
            "pin_factory": original_factory,
        }
        assert button.when_released is None
        assert button.when_held is None
        button.when_pressed()
    await asyncio.sleep(0)
    assert [queue.get_nowait() for _ in buttons] == [
        UiButtonPress(ACTION_PINS[button.pin], f"gpio:{button.pin}") for button in buttons
    ]
    gpio.close()
    gpio.close()
    assert all(button.closed for button in buttons)
    assert not factories
    assert device.pin_factory is original_factory


@pytest.mark.asyncio
async def test_partial_fallback_start_closes_buttons_and_owned_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, buttons, factories = _gpiozero(monkeypatch, shared=False, fail_pin=5)
    original_factory = device.pin_factory
    gpio = GpioUiInput()
    with pytest.raises(OSError, match="button setup failed"):
        gpio._start_gpiozero(asyncio.Queue(), asyncio.get_running_loop())
    assert len(buttons) == 2
    assert all(button.closed for button in buttons)
    assert len(factories) == 1
    assert not gpio._buttons
    assert gpio._owned_factory is None
    assert device.pin_factory is original_factory


@pytest.mark.asyncio
async def test_callback_assignment_failure_closes_newly_constructed_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gpiozero(monkeypatch)
    closed: list[int] = []

    class FailedButton:
        when_held = None
        when_released = None

        @property
        def when_pressed(self) -> object:
            return None

        @when_pressed.setter
        def when_pressed(self, _callback: object) -> None:
            raise RuntimeError("callback assignment failed")

        def close(self) -> None:
            closed.append(1)

    def button(_pin: int, **_kwargs: object) -> FailedButton:
        return FailedButton()

    monkeypatch.setattr(sys.modules["gpiozero"], "Button", button)
    gpio = GpioUiInput()
    with pytest.raises(RuntimeError, match="callback assignment failed"):
        gpio._start_gpiozero(asyncio.Queue(), asyncio.get_running_loop())
    assert closed == [1]
    assert not gpio._buttons


@pytest.mark.asyncio
async def test_fallback_close_detaches_pin_callback_before_button_thread_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, buttons, factories = _gpiozero(monkeypatch)
    gpio = GpioUiInput()
    gpio._start_gpiozero(asyncio.Queue(), asyncio.get_running_loop())
    closed: list[int] = []
    for button in buttons:
        button.pin = SimpleNamespace(when_changed=lambda *_args: None)

        def close(item: SimpleNamespace = button) -> None:
            assert item.pin.when_changed is None
            item.closed = True
            closed.append(item.pin)

        button.close = close
    gpio.close()
    assert len(closed) == 8
    assert all(button.closed for button in buttons)
    assert not factories  # Shared display factory remains available.


@pytest.mark.asyncio
async def test_old_native_callback_cannot_press_after_close_and_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, buttons, _ = _gpiozero(monkeypatch)
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio = GpioUiInput()
    gpio._start_gpiozero(queue, asyncio.get_running_loop())
    old_callback = buttons[5].when_pressed
    old_callback()  # Scheduled before close; must not enter the reopened queue.
    gpio.close()
    gpio._start_gpiozero(queue, asyncio.get_running_loop())
    old_callback()
    buttons[-3].when_pressed()
    await asyncio.sleep(0)
    assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
    assert queue.empty()
    gpio.close()


@pytest.mark.asyncio
async def test_edge_eof_closes_request_and_recovers_legacy_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = _edge_pipe(monkeypatch)
    _, buttons, _ = _gpiozero(monkeypatch)
    gpio = GpioUiInput()
    queue: asyncio.Queue[UiAction | UiButtonPress] = asyncio.Queue()
    gpio.start(queue, asyncio.get_running_loop())
    os.close(write_fd)
    await asyncio.sleep(0.01)
    assert gpio._edge_fd is None
    with pytest.raises(OSError):
        os.fstat(read_fd)
    assert len(buttons) == 8
    buttons[5].when_pressed()
    await asyncio.sleep(0)
    assert queue.get_nowait() == UiButtonPress(UiAction.SELECT, "gpio:21")
    gpio.close()


def test_callback_after_loop_shutdown_is_harmless() -> None:
    loop = asyncio.new_event_loop()
    callback = _enqueue(asyncio.Queue(), loop, UiAction.SELECT, button_id="gpio:21")
    loop.close()
    callback()


def test_linux_gpio_v2_abi_matches_kernel_layout() -> None:
    assert ctypes.sizeof(gpio_edges._LineAttribute) == 16
    assert ctypes.sizeof(gpio_edges._ConfigAttribute) == 24
    assert ctypes.sizeof(gpio_edges._LineConfig) == 272
    assert ctypes.sizeof(gpio_edges._LineRequest) == 592
    assert gpio_edges._LineRequest.config.offset == 288
    assert gpio_edges._LineRequest.num_lines.offset == 560
    assert gpio_edges._LineRequest.event_buffer_size.offset == 564
    assert gpio_edges._LineRequest.fd.offset == 588
    assert gpio_edges.GPIO_EVENT.size == 48


@pytest.mark.parametrize("fail_nonblocking", [False, True])
def test_request_config_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    fail_nonblocking: bool,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(os, "open", lambda *_args: 10)
    monkeypatch.setattr(os, "close", closed.append)
    monkeypatch.setattr(os, "set_inheritable", lambda *_args: None)

    def set_blocking(_fd: int, _blocking: bool) -> None:
        if fail_nonblocking:
            raise OSError("nonblocking failed")

    monkeypatch.setattr(os, "set_blocking", set_blocking)

    def ioctl(fd: int, command: int, payload: bytearray, mutate: bool) -> int:
        assert fd == 10
        assert command == gpio_edges.GPIO_V2_GET_LINE_IOCTL
        assert mutate
        request = gpio_edges._LineRequest.from_buffer(payload)
        assert request.fd == -1
        assert request.num_lines == 8
        assert request.event_buffer_size == 128
        assert request.config.flags == 0x134
        assert request.config.num_attrs == 1
        assert request.config.attrs[0].mask == 255
        assert request.config.attrs[0].attribute.id == 3
        assert request.config.attrs[0].attribute.value.debounce_period_us == 50_000
        assert tuple(request.offsets[:8]) == tuple(ACTION_PINS)
        request.fd = 20
        return 0

    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    if fail_nonblocking:
        with pytest.raises(OSError, match="nonblocking failed"):
            gpio_edges.request_edges(tuple(ACTION_PINS), chip=Path("/dev/gpiochip0"))
        assert closed == [20, 10]
    else:
        assert gpio_edges.request_edges(tuple(ACTION_PINS), chip=Path("/dev/gpiochip0")) == 20
        assert closed == [10]


def test_chip_discovery_deduplicates_aliases_and_excludes_other_controllers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chip = tmp_path / "gpiochip0"
    chip.touch()
    (tmp_path / "gpiochip4").symlink_to(chip)
    other = tmp_path / "gpiochip1"
    other.touch()
    opened: list[Path] = []

    def open_chip(path: Path, _flags: int) -> int:
        opened.append(path)
        return 10 if path == chip else 11

    def ioctl(fd: int, command: int, payload: bytearray, _mutate: bool) -> int:
        assert command == gpio_edges.GPIO_GET_CHIPINFO_IOCTL
        label = b"pinctrl-bcm2835" if fd == 10 else b"unrelated controller"
        payload[:] = struct.pack("=32s32sI", b"gpiochip", label, 54)
        return 0

    monkeypatch.setattr(os, "open", open_chip)
    monkeypatch.setattr(os, "close", lambda _fd: None)
    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    assert gpio_edges.button_chip(device_dir=tmp_path) == chip
    assert opened == [chip, other]


def test_level_mask_uses_request_order(monkeypatch: pytest.MonkeyPatch) -> None:
    def ioctl(fd: int, command: int, payload: bytearray, _mutate: bool) -> int:
        assert fd == 20
        assert command == gpio_edges.GPIO_V2_LINE_GET_VALUES_IOCTL
        assert struct.unpack("=QQ", payload) == (0, 255)
        payload[:] = struct.pack("=QQ", 0b11011111, 255)
        return 0

    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    assert gpio_edges.read_levels(20, 8) == 0b11011111
