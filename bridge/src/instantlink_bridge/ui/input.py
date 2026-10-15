"""GPIO input bindings for the Waveshare LCD HAT."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol, cast

from instantlink_bridge.config import UiSurface
from instantlink_bridge.ui import gpio_edges
from instantlink_bridge.ui.models import UiAction, UiButtonPress, UiInputEvent, UiInputGap

LOGGER = logging.getLogger(__name__)

JOYSTICK_UP = 6
JOYSTICK_DOWN = 19
JOYSTICK_LEFT = 5
JOYSTICK_RIGHT = 26
JOYSTICK_PRESS = 13
KEY1 = 21
KEY2 = 20
KEY3 = 16
ACTION_PINS = {
    JOYSTICK_UP: UiAction.UP,
    JOYSTICK_DOWN: UiAction.DOWN,
    JOYSTICK_LEFT: UiAction.LEFT,
    JOYSTICK_RIGHT: UiAction.RIGHT,
    JOYSTICK_PRESS: UiAction.SELECT,
    KEY1: UiAction.SELECT,
    KEY2: UiAction.BACK,
    KEY3: UiAction.HELP,
}
_EVENT_BATCH_SIZE = 128


def reset_input_queue(queue: asyncio.Queue[UiInputEvent]) -> None:
    """Discard uncertain buffered input and notify its consumer of the discontinuity.

    Runs on the event loop, including GPIO callbacks marshalled onto it. The
    gap precedes every subsequent accepted press, even when the queue was full.
    Keep queue accounting balanced for discarded events and an in-flight consumer.
    """
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        queue.task_done()
    queue.put_nowait(UiInputGap())


def enqueue_input(queue: asyncio.Queue[UiInputEvent], event: UiInputEvent) -> bool:
    """Enqueue one event, resetting buffered input if its bounded queue overflows."""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        reset_input_queue(queue)
        return False
    return True


class _PinFactory(Protocol):
    def close(self) -> None:
        """Release owned GPIO resources."""


class _ButtonPin(Protocol):
    when_changed: Callable[..., None] | None


class _ButtonDevice(Protocol):
    when_pressed: Callable[[], None] | None
    when_released: Callable[[], None] | None
    when_held: Callable[[], None] | None

    def close(self) -> None:
        """Release the GPIO pin."""


class NullInput:
    """No-op input for local development."""

    def start(
        self,
        queue: asyncio.Queue[UiInputEvent],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        return

    def close(self) -> None:
        return


class GpioUiInput:
    """Map joystick and KEY1-KEY3 to UI actions."""

    def __init__(self) -> None:
        self._buttons: list[_ButtonDevice] = []
        self._owned_factory: _PinFactory | None = None
        self._edge_fd: int | None = None
        self._edge_loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[UiInputEvent] | None = None
        self._pressed: set[int] = set()
        self._sequence = 0
        self._discard_events_until_ns = 0
        self._callback_generation = 0

    def start(
        self,
        queue: asyncio.Queue[UiInputEvent],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        if self._edge_fd is not None or self._buttons:
            return
        try:
            self._start_edges(queue, loop)
        except Exception:
            LOGGER.info("ui.input_gpiozero_fallback", exc_info=True)
            self._start_gpiozero(queue, loop)

    def _start_edges(
        self,
        queue: asyncio.Queue[UiInputEvent],
        loop: asyncio.AbstractEventLoop,
        *,
        chip: Path | None = None,
    ) -> None:
        pins = tuple(ACTION_PINS)
        event_fd = gpio_edges.request_edges(pins, chip=chip or gpio_edges.button_chip())
        self._edge_fd = event_fd
        self._edge_loop = loop
        try:
            levels = gpio_edges.read_levels(event_fd, len(pins))
            self._pressed = {pin for index, pin in enumerate(pins) if not levels & (1 << index)}
            self._sequence = 0
            self._discard_events_until_ns = 0
            self._queue = queue
            loop.add_reader(event_fd, self._read_edges)
        except BaseException:
            self._close_edges()
            raise
        LOGGER.info(
            "ui.input_edges_started backend=linux_gpio_v2 debounce_ms=50 lines=%s", len(pins)
        )

    def _read_edges(self) -> None:
        event_fd = self._edge_fd
        queue = self._queue
        loop = self._edge_loop
        if event_fd is None or queue is None or loop is None:
            return
        try:
            payload = os.read(event_fd, gpio_edges.GPIO_EVENT.size * _EVENT_BATCH_SIZE)
            if not payload or len(payload) % gpio_edges.GPIO_EVENT.size:
                raise OSError("incomplete Linux GPIO edge event")
            for values in gpio_edges.GPIO_EVENT.iter_unpack(payload):
                timestamp, edge, pin, sequence, *_ = values
                expected = (self._sequence + 1) & 0xFFFFFFFF
                self._sequence = sequence
                if sequence != expected:
                    # Overflow can hide release edges. Resync and discard older
                    # queued edges instead of counting an uncertain unlock press.
                    reset_input_queue(queue)
                    self._discard_events_until_ns = time.monotonic_ns()
                    levels = gpio_edges.read_levels(event_fd, len(ACTION_PINS))
                    self._pressed = {
                        offset
                        for index, offset in enumerate(ACTION_PINS)
                        if not levels & (1 << index)
                    }
                    LOGGER.warning("ui.input_edge_gap expected=%s received=%s", expected, sequence)
                if timestamp <= self._discard_events_until_ns or pin not in ACTION_PINS:
                    continue
                if edge == gpio_edges.GPIO_V2_LINE_EVENT_RISING_EDGE:
                    self._pressed.discard(pin)
                elif (
                    edge == gpio_edges.GPIO_V2_LINE_EVENT_FALLING_EDGE and pin not in self._pressed
                ):
                    self._pressed.add(pin)
                    enqueue_input(queue, UiButtonPress(ACTION_PINS[pin], f"gpio:{pin}"))
        except (BlockingIOError, InterruptedError):
            return
        except Exception:
            LOGGER.exception("ui.input_edges_failed")
            reset_input_queue(queue)
            self._close_edges()
            try:
                self._start_gpiozero(queue, loop)
            except Exception:
                LOGGER.exception("ui.input_fallback_failed")

    def _start_gpiozero(
        self,
        queue: asyncio.Queue[UiInputEvent],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        from gpiozero import Button, Device
        from gpiozero.pins.lgpio import LGPIOFactory

        factory = Device.pin_factory
        if not isinstance(factory, LGPIOFactory):
            factory = LGPIOFactory()
            self._owned_factory = cast(_PinFactory, factory)
        self._callback_generation += 1
        generation = self._callback_generation
        try:
            for pin, action in ACTION_PINS.items():
                button = cast(
                    _ButtonDevice,
                    Button(pin, pull_up=True, bounce_time=0.05, pin_factory=factory),
                )
                self._buttons.append(button)
                # Holding or releasing a key never emits a hidden operation.
                button.when_pressed = _enqueue(
                    queue,
                    loop,
                    action,
                    button_id=f"gpio:{pin}",
                    is_active=lambda: self._callback_generation == generation,
                )
        except BaseException:
            self.close()
            raise

    def _close_edges(self) -> None:
        event_fd = self._edge_fd
        loop = self._edge_loop
        self._edge_fd = None
        self._edge_loop = None
        self._queue = None
        self._pressed.clear()
        if event_fd is not None:
            if loop is not None:
                with suppress(Exception):
                    loop.remove_reader(event_fd)
            os.close(event_fd)

    def close(self) -> None:
        self._callback_generation += 1
        self._close_edges()
        for button in self._buttons:
            # GPIO Zero's LGPIOPin.close resets the line without cancelling
            # its native callback. Detach before closing the held-button thread
            # so a later edge/reopen cannot call into the closed Button.
            with suppress(Exception):
                pin = cast(_ButtonPin | None, getattr(button, "pin", None))
                if pin is not None:
                    pin.when_changed = None
            with suppress(Exception):
                button.close()
        self._buttons.clear()
        if self._owned_factory is not None:
            with suppress(Exception):
                self._owned_factory.close()
            self._owned_factory = None


def create_input(surface: UiSurface | None = None) -> GpioUiInput | NullInput:
    """Create GPIO input, falling back to no-op input if unavailable.

    When *surface* is ``UiSurface.HEADLESS`` the GPIO probe is skipped entirely
    and a ``NullInput`` is returned immediately.
    """

    if surface is UiSurface.HEADLESS:
        return NullInput()
    try:
        gpio_input = GpioUiInput()
        return gpio_input
    except Exception:
        LOGGER.exception("ui.input_unavailable")
        return NullInput()


def _enqueue(
    queue: asyncio.Queue[UiInputEvent],
    loop: asyncio.AbstractEventLoop,
    action: UiAction,
    *,
    button_id: str,
    is_active: Callable[[], bool] | None = None,
) -> Callable[[], None]:
    def callback() -> None:
        LOGGER.debug("ui.input_press action=%s", action)

        def put_action() -> None:
            if is_active is not None and not is_active():
                return
            enqueue_input(queue, UiButtonPress(action, button_id))

        # A late native callback can race orderly event-loop shutdown.
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(put_action)

    return callback
