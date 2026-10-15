"""Linux GPIO v2 edge requests without an extra userspace polling thread."""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path
from typing import ClassVar

GPIO_V2_GET_LINE_IOCTL = 0xC250B407
GPIO_GET_CHIPINFO_IOCTL = 0x8044B401
GPIO_V2_LINE_GET_VALUES_IOCTL = 0xC010B40E
GPIO_V2_LINE_FLAG_INPUT = 1 << 2
GPIO_V2_LINE_FLAG_EDGE_RISING = 1 << 4
GPIO_V2_LINE_FLAG_EDGE_FALLING = 1 << 5
GPIO_V2_LINE_FLAG_BIAS_PULL_UP = 1 << 8
GPIO_V2_LINE_ATTR_ID_DEBOUNCE = 3
GPIO_V2_LINE_EVENT_RISING_EDGE = 1
GPIO_V2_LINE_EVENT_FALLING_EDGE = 2
GPIO_EVENT = struct.Struct("=QIIII6I")
_CHIP_INFO = struct.Struct("=32s32sI")
_LINE_VALUES = struct.Struct("=QQ")
_BUTTON_CONTROLLERS = {"pinctrl-bcm2835", "pinctrl-bcm2711", "pinctrl-rp1"}


class _AttributeValue(ctypes.Union):
    _fields_: ClassVar = [("flags", ctypes.c_uint64), ("debounce_period_us", ctypes.c_uint32)]


class _LineAttribute(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("padding", ctypes.c_uint32),
        ("value", _AttributeValue),
    ]


class _ConfigAttribute(ctypes.Structure):
    _fields_ = [("attribute", _LineAttribute), ("mask", ctypes.c_uint64)]


class _LineConfig(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("num_attrs", ctypes.c_uint32),
        ("padding", ctypes.c_uint32 * 5),
        ("attrs", _ConfigAttribute * 10),
    ]


class _LineRequest(ctypes.Structure):
    _fields_ = [
        ("offsets", ctypes.c_uint32 * 64),
        ("consumer", ctypes.c_char * 32),
        ("config", _LineConfig),
        ("num_lines", ctypes.c_uint32),
        ("event_buffer_size", ctypes.c_uint32),
        ("padding", ctypes.c_uint32 * 5),
        ("fd", ctypes.c_int32),
    ]


def button_chip(*, device_dir: Path = Path("/dev")) -> Path:
    """Find a supported Raspberry Pi header controller, independent of chip number."""
    import fcntl

    matches: list[Path] = []
    for chip in sorted({path.resolve() for path in device_dir.glob("gpiochip*")}):
        chip_fd = os.open(chip, os.O_RDONLY | os.O_CLOEXEC)
        try:
            payload = bytearray(_CHIP_INFO.size)
            fcntl.ioctl(chip_fd, GPIO_GET_CHIPINFO_IOCTL, payload, True)
            _, label, lines = _CHIP_INFO.unpack(payload)
            if label.rstrip(b"\0").decode("ascii") in _BUTTON_CONTROLLERS and lines > 26:
                matches.append(chip)
        finally:
            os.close(chip_fd)
    if len(matches) != 1:
        raise OSError("no unambiguous supported Raspberry Pi button controller")
    return matches[0]


def read_levels(event_fd: int, num_lines: int) -> int:
    """Read logical levels, indexed in request order rather than GPIO offset."""
    import fcntl

    payload = bytearray(_LINE_VALUES.pack(0, (1 << num_lines) - 1))
    fcntl.ioctl(event_fd, GPIO_V2_LINE_GET_VALUES_IOCTL, payload, True)
    return int(_LINE_VALUES.unpack(payload)[0])


def request_edges(pins: tuple[int, ...], *, chip: Path, debounce_us: int = 50_000) -> int:
    """Return an owned, nonblocking GPIO request FD or leave no claimed lines.

    Both edges are needed for kernel stable-state debounce; callers emit actions
    only for falling edges. The kernel implements debounce in software when the
    GPIO controller does not support it. Unsupported requests raise for fallback.
    Layouts are the Linux UAPI from ``linux/gpio.h``; no private lgpio API is used.
    """
    import fcntl

    if not 1 <= len(pins) <= 64 or len(set(pins)) != len(pins):
        raise ValueError("GPIO request needs 1-64 distinct lines")
    if ctypes.sizeof(_LineRequest) != 592 or GPIO_EVENT.size != 48:
        raise RuntimeError("unsupported Linux GPIO v2 ABI layout")
    request = _LineRequest()
    request.fd = -1
    request.num_lines = len(pins)
    request.event_buffer_size = len(pins) * 16
    request.consumer = b"InstantLink buttons"
    for index, pin in enumerate(pins):
        request.offsets[index] = pin
    request.config.flags = (
        GPIO_V2_LINE_FLAG_INPUT
        | GPIO_V2_LINE_FLAG_EDGE_RISING
        | GPIO_V2_LINE_FLAG_EDGE_FALLING
        | GPIO_V2_LINE_FLAG_BIAS_PULL_UP
    )
    request.config.num_attrs = 1
    request.config.attrs[0].attribute.id = GPIO_V2_LINE_ATTR_ID_DEBOUNCE
    request.config.attrs[0].attribute.value.debounce_period_us = debounce_us
    request.config.attrs[0].mask = (1 << len(pins)) - 1
    payload = bytearray(bytes(request))
    chip_fd = os.open(chip, os.O_RDONLY | os.O_CLOEXEC)
    event_fd = -1
    try:
        fcntl.ioctl(chip_fd, GPIO_V2_GET_LINE_IOCTL, payload, True)
        event_fd = _LineRequest.from_buffer_copy(payload).fd
        if event_fd < 0:
            raise OSError("GPIO request did not return an event FD")
        os.set_inheritable(event_fd, False)
        os.set_blocking(event_fd, False)
        return event_fd
    except BaseException:
        if event_fd >= 0:
            os.close(event_fd)
        raise
    finally:
        os.close(chip_fd)
