"""GPIO input bindings for the Waveshare LCD HAT."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol, cast

from instantlink_bridge.config import UiSurface
from instantlink_bridge.ui.models import UiAction, UiButtonPress

LOGGER = logging.getLogger(__name__)

JOYSTICK_UP = 6
JOYSTICK_DOWN = 19
JOYSTICK_LEFT = 5
JOYSTICK_RIGHT = 26
JOYSTICK_PRESS = 13
KEY1 = 21
KEY2 = 20
KEY3 = 16


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
        queue: asyncio.Queue[UiAction | UiButtonPress],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        return

    def close(self) -> None:
        return


class GpioUiInput:
    """Map joystick and KEY1-KEY3 to UI actions."""

    def __init__(self) -> None:
        self._buttons: list[_ButtonDevice] = []

    def start(
        self,
        queue: asyncio.Queue[UiAction | UiButtonPress],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        from gpiozero import Button, Device
        from gpiozero.pins.lgpio import LGPIOFactory

        if not isinstance(Device.pin_factory, LGPIOFactory):
            Device.pin_factory = LGPIOFactory()

        action_pins = {
            JOYSTICK_UP: UiAction.UP,
            JOYSTICK_DOWN: UiAction.DOWN,
            JOYSTICK_LEFT: UiAction.LEFT,
            JOYSTICK_RIGHT: UiAction.RIGHT,
            JOYSTICK_PRESS: UiAction.SELECT,
            KEY1: UiAction.SELECT,
            KEY2: UiAction.BACK,
        }
        for pin, action in action_pins.items():
            button = cast(_ButtonDevice, Button(pin, pull_up=True, bounce_time=0.05))
            button.when_pressed = _enqueue(queue, loop, action, button_id=f"gpio:{pin}")
            self._buttons.append(button)

        # KEY3 is a single contextual action on press. Holding it does not
        # emit a second, hidden operation when the button is released.
        context_button = cast(_ButtonDevice, Button(KEY3, pull_up=True, bounce_time=0.05))
        context_button.when_pressed = _enqueue(queue, loop, UiAction.HELP, button_id=f"gpio:{KEY3}")
        self._buttons.append(context_button)

    def close(self) -> None:
        for button in self._buttons:
            with suppress(Exception):
                button.close()
        self._buttons.clear()


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
    queue: asyncio.Queue[UiAction | UiButtonPress],
    loop: asyncio.AbstractEventLoop,
    action: UiAction,
    *,
    button_id: str,
) -> Callable[[], None]:
    def callback() -> None:
        LOGGER.debug("ui.input_press action=%s", action)

        def put_action() -> None:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(UiButtonPress(action, button_id))

        loop.call_soon_threadsafe(put_action)

    return callback
