from __future__ import annotations

from pathlib import Path

import pytest

from instantlink_bridge.ui.display import (
    FramebufferBacklightError,
    FramebufferDisplay,
    _st7789_framebuffer,
)
from instantlink_bridge.ui.models import UiMode, UiSnapshot


def test_st7789_framebuffer_discovers_matching_fb_without_hardcoded_number(
    tmp_path: Path,
) -> None:
    sysfs_root = tmp_path / "sys"
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    _write_text(sysfs_root / "class" / "graphics" / "fb0" / "name", "other_fb\n")
    _write_text(sysfs_root / "class" / "graphics" / "fb1" / "name", "fb_st7789v\n")
    (dev_root / "fb1").write_bytes(b"")

    framebuffer = _st7789_framebuffer(sysfs_root=sysfs_root, dev_root=dev_root)

    assert framebuffer == dev_root / "fb1"


def test_framebuffer_render_turns_on_matching_backlight_and_writes_frame(
    tmp_path: Path,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))

    assert (backlight / "brightness").read_text(encoding="ascii") == "7\n"
    assert len(framebuffer.read_bytes()) == 4


def test_framebuffer_screen_off_blanks_frame_and_turns_backlight_off(
    tmp_path: Path,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(
        tmp_path,
        brightness="7\n",
    )
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    display.set_idle_stage("screen_off")

    assert (backlight / "brightness").read_text(encoding="ascii") == "0\n"
    assert framebuffer.read_bytes() == b"\x00\x00\x00\x00"


def test_framebuffer_non_off_idle_stage_turns_backlight_on_without_blanking(
    tmp_path: Path,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(tmp_path)
    existing_frame = b"\x01\x02\x03\x04"
    framebuffer.write_bytes(existing_frame)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    display.set_idle_stage("dim")

    assert (backlight / "brightness").read_text(encoding="ascii") == "7\n"
    assert framebuffer.read_bytes() == existing_frame


def test_framebuffer_uses_power_control_when_backlight_is_not_dimmable(
    tmp_path: Path,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(
        tmp_path,
        max_brightness="0\n",
        bl_power="4\n",
    )
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
    assert (backlight / "brightness").read_text(encoding="ascii") == "0\n"
    assert (backlight / "bl_power").read_text(encoding="ascii") == "0\n"

    display.set_idle_stage("screen_off")
    assert (backlight / "bl_power").read_text(encoding="ascii") == "4\n"


def test_framebuffer_power_only_backlight_write_failure_does_not_break_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(
        tmp_path,
        max_brightness="0\n",
        bl_power="0\n",
    )
    bl_power_path = backlight / "bl_power"
    original_write_text = Path.write_text

    def fail_bl_power_write(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if path == bl_power_path:
            raise PermissionError("root-only sysfs node")
        return original_write_text(
            path,
            data,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    monkeypatch.setattr(Path, "write_text", fail_bl_power_write)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))

    assert len(framebuffer.read_bytes()) == 4


def test_framebuffer_render_respects_off_idle_stage(
    tmp_path: Path,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(
        tmp_path,
        brightness="7\n",
    )
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    display.render(
        UiSnapshot(
            mode=UiMode.READY,
            ftp_host="192.168.7.1",
            idle_stage="screen_off",
        )
    )

    assert (backlight / "brightness").read_text(encoding="ascii") == "0\n"
    assert len(framebuffer.read_bytes()) == 4


def test_framebuffer_render_raises_when_backlight_brightness_stays_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(tmp_path)
    brightness_path = backlight / "brightness"
    original_write_text = Path.write_text

    def write_text_without_updating_brightness(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if path == brightness_path:
            return len(data)
        return original_write_text(
            path,
            data,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    monkeypatch.setattr(Path, "write_text", write_text_without_updating_brightness)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    with pytest.raises(FramebufferBacklightError, match="remained off"):
        display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))


def _fake_st7789_framebuffer(
    tmp_path: Path,
    *,
    brightness: str = "0\n",
    max_brightness: str = "7\n",
    bl_power: str | None = None,
) -> tuple[Path, Path, Path]:
    sysfs_root = tmp_path / "sys"
    dev_root = tmp_path / "dev"
    framebuffer = dev_root / "fb1"
    backlight = sysfs_root / "class" / "backlight" / "fb_st7789v"
    dev_root.mkdir()
    framebuffer.write_bytes(b"")
    _write_text(sysfs_root / "class" / "graphics" / "fb1" / "name", "fb_st7789v\n")
    _write_text(sysfs_root / "class" / "graphics" / "fb1" / "virtual_size", "2,1\n")
    _write_text(backlight / "brightness", brightness)
    _write_text(backlight / "max_brightness", max_brightness)
    if bl_power is not None:
        _write_text(backlight / "bl_power", bl_power)
    return sysfs_root, framebuffer, backlight


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")
