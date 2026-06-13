"""LCD display adapters."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from PIL import Image

from instantlink_bridge.config import UiSurface
from instantlink_bridge.ui.models import UiSnapshot
from instantlink_bridge.ui.render import render_snapshot

LOGGER = logging.getLogger(__name__)
ST7789_FRAMEBUFFER_NAME = "fb_st7789v"
BACKLIGHT_OFF_STAGES = {"screen_off", "deep_idle", "poweroff"}


class _BacklightDevice(Protocol):
    def on(self) -> None:
        """Turn the backlight on."""

    def off(self) -> None:
        """Turn the backlight off."""

    def close(self) -> None:
        """Release the GPIO pin."""


class _ScreenDevice(Protocol):
    def display(self, image: Image.Image) -> None:
        """Display one frame."""


class Display(Protocol):
    """Something that can render UI snapshots."""

    def render(self, snapshot: UiSnapshot) -> None:
        """Render a snapshot."""

    def set_idle_stage(self, stage: str) -> None:
        """Apply an idle power stage."""

    def close(self) -> None:
        """Release hardware resources."""


class FramebufferBacklightError(RuntimeError):
    """Raised when a framebuffer backlight cannot be controlled."""


class NullDisplay:
    """No-op display for non-Pi development and hardware failures."""

    def render(self, snapshot: UiSnapshot) -> None:
        LOGGER.info("ui.render mode=%s message=%s", snapshot.mode, snapshot.message)

    def set_idle_stage(self, stage: str) -> None:
        LOGGER.debug("ui.display_idle_stage stage=%s", stage)

    def close(self) -> None:
        return


class LumaSt7789Display:
    """Waveshare 1.3 inch ST7789 display."""

    def __init__(self) -> None:
        self._backlight: _BacklightDevice | None = None
        self._device = self._create_device()

    def render(self, snapshot: UiSnapshot) -> None:
        self._device.display(render_snapshot(snapshot))

    def set_idle_stage(self, stage: str) -> None:
        if self._backlight is None:
            return
        if stage in BACKLIGHT_OFF_STAGES:
            self._backlight.off()
        else:
            self._backlight.on()

    def close(self) -> None:
        if self._backlight is not None:
            self._backlight.close()

    def _create_device(self) -> _ScreenDevice:
        from gpiozero import OutputDevice
        from luma.core.interface.serial import spi
        from luma.lcd.device import st7789

        self._backlight = OutputDevice(24, active_high=True, initial_value=True)
        serial = spi(port=0, device=0, gpio_DC=25, gpio_RST=27, bus_speed_hz=40_000_000)
        return cast(_ScreenDevice, st7789(serial, width=240, height=240, rotate=0))


class FramebufferDisplay:
    """Linux framebuffer display for kernel-owned ST7789 devices."""

    def __init__(self, path: Path = Path("/dev/fb0"), *, sysfs_root: Path = Path("/sys")) -> None:
        self._path = path
        self._sysfs_root = sysfs_root
        self._size = _framebuffer_size(path, sysfs_root=sysfs_root)
        self._framebuffer_name = _framebuffer_name(path, sysfs_root=sysfs_root)
        self._backlight: _FramebufferBacklight | _GpioBacklight | None = (
            _framebuffer_backlight(
                path,
                framebuffer_name=self._framebuffer_name,
                sysfs_root=sysfs_root,
            )
        )
        if self._framebuffer_name == ST7789_FRAMEBUFFER_NAME and self._backlight is None:
            # The kernel ST7789v driver doesn't always expose a sysfs
            # backlight node — depends on the device-tree overlay and
            # the kernel build. Fall back to driving the Waveshare LCD
            # HAT's hardware backlight pin (BCM 24) over GPIO so screen
            # off actually goes dark, instead of just writing a black
            # frame while the panel stays lit. Without this fallback
            # the screen-off idle stage drew zero power benefit and
            # users saw a faint black-screen glow defeating the purpose.
            LOGGER.warning(
                "ui.framebuffer_backlight_unavailable path=%s name=%s falling_back=gpio_24",
                path,
                self._framebuffer_name,
            )
            self._backlight = _GpioBacklight.try_open()

    def render(self, snapshot: UiSnapshot) -> None:
        image = render_snapshot(snapshot)
        if image.size != self._size:
            image = image.resize(self._size)
        self._path.write_bytes(_rgb565_bytes(image))
        if snapshot.idle_stage in BACKLIGHT_OFF_STAGES:
            self._turn_backlight_off()
        else:
            self._turn_backlight_on()

    def set_idle_stage(self, stage: str) -> None:
        if stage in BACKLIGHT_OFF_STAGES:
            self._path.write_bytes(_rgb565_bytes(Image.new("RGB", self._size, "black")))
            self._turn_backlight_off()
        else:
            self._turn_backlight_on()

    def close(self) -> None:
        return

    def _turn_backlight_on(self) -> None:
        if self._backlight is None:
            return
        self._backlight.turn_on()

    def _turn_backlight_off(self) -> None:
        if self._backlight is None:
            return
        self._backlight.turn_off()


@dataclass(frozen=True, slots=True)
class _FramebufferBacklight:
    path: Path

    @property
    def brightness_path(self) -> Path:
        return self.path / "brightness"

    @property
    def max_brightness_path(self) -> Path:
        return self.path / "max_brightness"

    @property
    def bl_power_path(self) -> Path:
        return self.path / "bl_power"

    def turn_on(self) -> None:
        if self._supports_brightness_control():
            self._write_brightness(self._on_brightness())
            brightness = self._read_brightness()
            if brightness <= 0:
                raise FramebufferBacklightError(
                    "framebuffer backlight remained off "
                    f"brightness_path={self.brightness_path} brightness={brightness}"
                )
            return
        self._write_bl_power(0)

    def turn_off(self) -> None:
        if self._supports_brightness_control():
            self._write_brightness(0)
            return
        self._write_bl_power(4)

    def _on_brightness(self) -> int:
        try:
            max_brightness = _read_sysfs_int(self.max_brightness_path)
        except (OSError, ValueError):
            return 1
        return max(1, max_brightness)

    def _supports_brightness_control(self) -> bool:
        try:
            return _read_sysfs_int(self.max_brightness_path) > 0
        except (OSError, ValueError):
            return True

    def _read_brightness(self) -> int:
        try:
            return _read_sysfs_int(self.brightness_path)
        except (OSError, ValueError) as exc:
            raise FramebufferBacklightError(
                f"could not read framebuffer backlight brightness_path={self.brightness_path}"
            ) from exc

    def _write_brightness(self, value: int) -> None:
        try:
            self.brightness_path.write_text(f"{value}\n", encoding="ascii")
        except OSError as exc:
            raise FramebufferBacklightError(
                "could not set framebuffer backlight "
                f"brightness_path={self.brightness_path} value={value}; "
                "check sysfs permissions and video group membership"
            ) from exc

    def _write_bl_power(self, value: int) -> None:
        try:
            self.bl_power_path.write_text(f"{value}\n", encoding="ascii")
        except OSError:
            # WARNING, not DEBUG: this path is what physically gates the
            # ST7789v backlight when max_brightness=0, and a silent
            # PermissionError here was why screen_off left the panel lit.
            # If the bl_power write keeps failing in journalctl, the udev
            # rule that chmods bl_power g+w for the video group (see
            # bridge/udev/60-instantlink-bridge-backlight.rules) is the
            # likely culprit — check that it shipped and udev reloaded.
            LOGGER.warning(
                "ui.framebuffer_backlight_power_unavailable bl_power_path=%s value=%s",
                self.bl_power_path,
                value,
                exc_info=True,
            )


class _GpioBacklight:
    """Waveshare LCD HAT backlight on BCM GPIO 24.

    Fallback path for :class:`FramebufferDisplay` when the kernel
    ST7789v driver doesn't expose a sysfs backlight class. The HAT
    wires the LED's enable line straight to BCM 24, so toggling the
    pin LOW physically kills the panel illumination — what the user
    actually wants when they enable "Screen off after N minutes".

    Construction is via ``try_open`` so an import or pin-bind error
    on a non-Pi dev box returns ``None`` instead of crashing the
    framebuffer-display path; the caller falls back to the no-op
    behaviour the original code already had.
    """

    BL_GPIO_PIN = 24

    def __init__(self, device: object) -> None:
        # Stored as ``object`` so the gpiozero import stays lazy and
        # mypy doesn't need a gpiozero stub on the dev box.
        self._device = device

    @classmethod
    def try_open(cls) -> _GpioBacklight | None:
        try:
            from gpiozero import OutputDevice
        except Exception:
            LOGGER.debug("ui.gpio_backlight_unavailable_import", exc_info=True)
            return None
        try:
            device = OutputDevice(cls.BL_GPIO_PIN, active_high=True, initial_value=True)
        except Exception:
            LOGGER.warning(
                "ui.gpio_backlight_open_failed pin=%s", cls.BL_GPIO_PIN, exc_info=True
            )
            return None
        return cls(device)

    def turn_on(self) -> None:
        # Cast for mypy: ``object`` doesn't expose ``on``; we know it's
        # an ``OutputDevice`` because that's all ``try_open`` instantiates.
        on = getattr(self._device, "on", None)
        if callable(on):
            on()

    def turn_off(self) -> None:
        off = getattr(self._device, "off", None)
        if callable(off):
            off()

    def close(self) -> None:
        close = getattr(self._device, "close", None)
        if callable(close):
            close()


def create_display(surface: UiSurface | None = None) -> Display:
    """Create the hardware display, falling back to logs if unavailable.

    When *surface* is ``UiSurface.HEADLESS`` the probe chain is skipped entirely
    and a ``NullDisplay`` is returned immediately, avoiding the ~0.5 s cold-boot
    cost of probing framebuffers and importing ``luma.lcd`` / ``gpiozero``.
    """

    if surface is UiSurface.HEADLESS:
        return NullDisplay()
    framebuffer = _st7789_framebuffer()
    if framebuffer is not None:
        try:
            return FramebufferDisplay(framebuffer)
        except Exception:
            LOGGER.exception("ui.framebuffer_unavailable path=%s", framebuffer)
    try:
        return LumaSt7789Display()
    except Exception:
        LOGGER.exception("ui.display_unavailable")
        return NullDisplay()


def _st7789_framebuffer(
    *,
    sysfs_root: Path = Path("/sys"),
    dev_root: Path = Path("/dev"),
) -> Path | None:
    for name_path in sorted((sysfs_root / "class" / "graphics").glob("fb*/name")):
        try:
            name = name_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name != ST7789_FRAMEBUFFER_NAME:
            continue
        framebuffer = dev_root / name_path.parent.name
        if framebuffer.exists():
            return framebuffer
    return None


def _framebuffer_name(path: Path, *, sysfs_root: Path = Path("/sys")) -> str | None:
    sysfs = sysfs_root / "class" / "graphics" / path.name / "name"
    try:
        return sysfs.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _framebuffer_size(path: Path, *, sysfs_root: Path = Path("/sys")) -> tuple[int, int]:
    sysfs = sysfs_root / "class" / "graphics" / path.name / "virtual_size"
    try:
        width, height = sysfs.read_text(encoding="utf-8").strip().split(",", maxsplit=1)
        return (int(width), int(height))
    except (OSError, ValueError):
        return (240, 240)


def _framebuffer_backlight(
    path: Path,
    *,
    framebuffer_name: str | None = None,
    sysfs_root: Path = Path("/sys"),
) -> _FramebufferBacklight | None:
    name = framebuffer_name or _framebuffer_name(path, sysfs_root=sysfs_root)
    if name is None:
        return None

    device_backlight = sysfs_root / "class" / "graphics" / path.name / "device" / "backlight"
    candidates = (
        device_backlight / name,
        sysfs_root / "class" / "backlight" / name,
    )
    for candidate in candidates:
        if _is_backlight_device(candidate):
            return _FramebufferBacklight(candidate)

    for candidate in sorted(device_backlight.glob("*")):
        if _is_backlight_device(candidate):
            return _FramebufferBacklight(candidate)
    return None


def _is_backlight_device(path: Path) -> bool:
    return path.is_dir() and (path / "brightness").exists()


def _read_sysfs_int(path: Path) -> int:
    return int(path.read_text(encoding="ascii").strip())


def _rgb565_bytes(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    output = bytearray(rgb.width * rgb.height * 2)
    index = 0
    for red, green, blue in cast(Iterable[tuple[int, int, int]], rgb.getdata()):
        value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        output[index] = value & 0xFF
        output[index + 1] = value >> 8
        index += 2
    return bytes(output)
