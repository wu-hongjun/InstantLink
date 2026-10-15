from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from random import Random
from threading import Event
from types import ModuleType

import pytest
from PIL import Image

from instantlink_bridge.ui import display as display_module
from instantlink_bridge.ui.display import (
    FramebufferBacklightError,
    FramebufferDisplay,
    _rgb565_bytes,
    _st7789_framebuffer,
)
from instantlink_bridge.ui.models import UiMode, UiSnapshot


@pytest.fixture(params=["numpy", "pillow"])
def rgb565_backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.param == "numpy":
        pytest.importorskip("numpy")
        packer = display_module._rgb565_bytes_numpy
    else:
        packer = display_module._rgb565_bytes_pillow
    monkeypatch.setattr(display_module, "_rgb565_packer", lambda: packer)


def _reference_rgb565(image: Image.Image) -> bytes:
    """Independent scalar oracle for the framebuffer's existing pixel format."""
    rgb = image.convert("RGB").tobytes()
    output = bytearray()
    for index in range(0, len(rgb), 3):
        red, green, blue = rgb[index : index + 3]
        value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        output.extend(value.to_bytes(2, "little"))
    return bytes(output)


def test_rgb565_known_colors_preserve_channel_order_and_little_endian(rgb565_backend: None) -> None:
    image = Image.new("RGB", (6, 1))
    image.putdata([(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (8, 4, 8)])

    assert _rgb565_bytes(image) == bytes.fromhex("0000 ffff 00f8 e007 1f00 2108")


def test_rgb565_matches_oracle_at_every_channel_value_and_quantization_boundary(
    rgb565_backend: None,
) -> None:
    boundaries = (0, 3, 4, 7, 8, 31, 32, 127, 128, 248, 252, 255)
    pixels = [
        pixel
        for value in range(256)
        for fixed in boundaries
        for pixel in ((value, fixed, fixed), (fixed, value, fixed), (fixed, fixed, value))
    ]
    image = Image.new("RGB", (len(pixels), 1))
    image.putdata(pixels)

    assert _rgb565_bytes(image) == _reference_rgb565(image)


@pytest.mark.parametrize("size", [(0, 0), (0, 3), (3, 0), (1, 1), (3, 5), (240, 240), (321, 241)])
def test_rgb565_matches_oracle_for_arbitrary_sizes_and_pixel_combinations(
    size: tuple[int, int],
    rgb565_backend: None,
) -> None:
    random = Random(565)
    image = Image.frombytes("RGB", size, random.randbytes(size[0] * size[1] * 3))
    original = image.tobytes()

    assert _rgb565_bytes(image) == _reference_rgb565(image)
    assert image.tobytes() == original


@pytest.mark.parametrize("mode", ["1", "L", "LA", "P", "RGBA", "CMYK", "YCbCr", "I", "F"])
def test_rgb565_preserves_conversion_from_non_rgb_modes(mode: str, rgb565_backend: None) -> None:
    random = Random(565)
    image = Image.frombytes("RGB", (13, 7), random.randbytes(13 * 7 * 3)).convert(mode)
    if mode in {"LA", "RGBA"}:
        image.putalpha(Image.frombytes("L", image.size, random.randbytes(13 * 7)))
    elif mode == "P":
        image.info["transparency"] = 0
    original = image.tobytes()

    assert _rgb565_bytes(image) == _reference_rgb565(image)
    assert image.mode == mode
    assert image.tobytes() == original


def test_rgb565_concurrent_frames_have_independent_buffers(rgb565_backend: None) -> None:
    random = Random(565)
    images = [Image.frombytes("RGB", (13, 7), random.randbytes(13 * 7 * 3)) for _ in range(24)]
    originals = [image.tobytes() for image in images]
    expected = [_reference_rgb565(image) for image in images]

    with ThreadPoolExecutor(max_workers=4) as executor:
        actual = list(executor.map(_rgb565_bytes, images))

    assert actual == expected
    assert [image.tobytes() for image in images] == originals


@pytest.mark.parametrize("available", [True, False])
def test_rgb565_selects_lazy_backend_once_and_preserves_missing_numpy_fallback(
    monkeypatch: pytest.MonkeyPatch,
    available: bool,
) -> None:
    imports: list[str] = []

    def load(name: str) -> ModuleType:
        imports.append(name)
        if not available:
            raise ImportError("NumPy is not installed")
        return ModuleType(name)

    monkeypatch.setattr(display_module, "import_module", load)
    display_module._rgb565_packer.cache_clear()
    try:
        expected = (
            display_module._rgb565_bytes_numpy if available else display_module._rgb565_bytes_pillow
        )
        assert imports == []
        assert display_module._rgb565_packer() is expected
        assert display_module._rgb565_packer() is expected
        assert imports == ["numpy"]
        if not available:
            image = Image.new("RGB", (3, 5), (31, 128, 248))
            assert _rgb565_bytes(image) == _reference_rgb565(image)
            assert imports == ["numpy"]
    finally:
        display_module._rgb565_packer.cache_clear()


def test_framebuffer_without_event_loop_does_not_load_numpy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_load() -> object:
        raise AssertionError("boot splash must not load NumPy")

    monkeypatch.setattr(display_module, "_rgb565_packer", unexpected_load)
    sysfs_root, framebuffer, _ = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
    display.set_idle_stage("screen_off")

    assert display._packer_task is None
    assert framebuffer.read_bytes() == b"\0\0\0\0"
    display.close()


@pytest.mark.asyncio
async def test_framebuffer_renders_and_handles_idle_while_backend_load_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = Event(), Event()
    calls = 0

    def load() -> object:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5)
        return display_module._rgb565_bytes_numpy

    monkeypatch.setattr(display_module, "_rgb565_packer", load)
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    try:
        assert display._packer_task is None
        await asyncio.sleep(0)
        assert calls == 0
        snapshot = UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1")
        display.render(snapshot)
        assert not started.is_set()
        assert (backlight / "brightness").read_text(encoding="ascii") == "7\n"
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 2), 3)
        original = framebuffer.read_bytes()
        expected = _reference_rgb565(display_module.render_snapshot(snapshot).resize((2, 1)))
        assert original == expected
        display.set_idle_stage("screen_off")
        display.set_idle_stage("active")
        assert framebuffer.read_bytes() == original
        assert (backlight / "brightness").read_text(encoding="ascii") == "7\n"
        assert display._packer is display_module._rgb565_bytes_pillow
        assert calls == 1
        release.set()
        assert display._packer_task is not None
        await asyncio.wait_for(display._packer_task, 3)
        assert display._packer is display_module._rgb565_bytes_numpy
        display.render(snapshot)
        assert framebuffer.read_bytes() == expected
    finally:
        release.set()
        display.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "backlight"])
async def test_framebuffer_failed_first_frame_does_not_start_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    sysfs_root, framebuffer, _ = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)

    def fail_write(path: Path, frame: bytes) -> int:
        raise OSError("framebuffer write failed")

    def fail_backlight() -> None:
        raise FramebufferBacklightError("backlight failed")

    if failure == "write":
        monkeypatch.setattr(Path, "write_bytes", fail_write)
    else:
        monkeypatch.setattr(display, "_turn_backlight_on", fail_backlight)
    try:
        with pytest.raises((OSError, FramebufferBacklightError)):
            display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
        assert display._packer_task is None
        await asyncio.sleep(0)
        assert display._packer_task is None
    finally:
        display.close()


@pytest.mark.asyncio
async def test_framebuffer_close_cancels_loading_and_never_switches_closed_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release, finished = Event(), Event(), Event()

    def load() -> object:
        started.set()
        assert release.wait(5)
        finished.set()
        return display_module._rgb565_bytes_numpy

    monkeypatch.setattr(display_module, "_rgb565_packer", load)
    sysfs_root, framebuffer, _ = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    try:
        display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 2), 3)
        display.close()
        display.close()
        assert display._packer_task is not None
        with pytest.raises(asyncio.CancelledError):
            await display._packer_task
        release.set()
        assert await asyncio.wait_for(asyncio.to_thread(finished.wait, 2), 3)
        await asyncio.sleep(0)
        assert display._packer is display_module._rgb565_bytes_pillow
        assert display._packer_task.cancelled()
    finally:
        release.set()
        display.close()


@pytest.mark.asyncio
async def test_framebuffer_close_before_loader_runs_does_not_start_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_load() -> object:
        raise AssertionError("closed display must not start loading")

    monkeypatch.setattr(display_module, "_rgb565_packer", unexpected_load)
    sysfs_root, framebuffer, _ = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
    display.close()
    assert display._packer_task is not None
    with pytest.raises(asyncio.CancelledError):
        await display._packer_task
    assert display._packer is display_module._rgb565_bytes_pillow


@pytest.mark.asyncio
async def test_framebuffer_missing_numpy_loads_fallback_without_warnings_or_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def missing(name: str) -> ModuleType:
        nonlocal calls
        calls += 1
        raise ImportError("optional NumPy unavailable")

    monkeypatch.setattr(display_module, "import_module", missing)
    display_module._rgb565_packer.cache_clear()
    sysfs_root, framebuffer, _ = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    try:
        display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
        assert display._packer_task is not None
        await display._packer_task
        display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
        display.set_idle_stage("screen_off")
        display.set_idle_stage("active")
        assert display._packer is display_module._rgb565_bytes_pillow
        assert calls == 1
        assert not any("ui.framebuffer_packer_unavailable" in r.message for r in caplog.records)
    finally:
        display.close()
        display_module._rgb565_packer.cache_clear()


@pytest.mark.asyncio
async def test_framebuffer_loader_failure_keeps_pillow_and_logs_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def load() -> object:
        raise RuntimeError("native dependency cannot load")

    monkeypatch.setattr(display_module, "_rgb565_packer", load)
    sysfs_root, framebuffer, _ = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    try:
        display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
        assert display._packer_task is not None
        await display._packer_task
        display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.7.1"))
        display.render(UiSnapshot(mode=UiMode.READY, ftp_host="192.168.7.1"))
        assert display._packer is display_module._rgb565_bytes_pillow
        assert len(framebuffer.read_bytes()) == 4
        assert sum("ui.framebuffer_packer_unavailable" in r.message for r in caplog.records) == 1
    finally:
        display.close()


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


@pytest.mark.parametrize("off_stage", ["screen_off", "deep_idle", "poweroff"])
@pytest.mark.parametrize("power_only", [False, True])
def test_framebuffer_wake_restores_pixels_before_backlight_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, off_stage: str, power_only: bool
) -> None:
    sysfs_root, framebuffer, backlight = _fake_st7789_framebuffer(
        tmp_path, max_brightness="0\n" if power_only else "7\n", bl_power="0\n"
    )
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    display.render(UiSnapshot(mode=UiMode.PRINTER_SEARCHING, ftp_host="192.168.8.1"))
    expected_frame = framebuffer.read_bytes()
    assert any(expected_frame)
    display.set_idle_stage(off_stage)
    assert not any(framebuffer.read_bytes())
    original_write_text = Path.write_text

    def check_pixels_before_backlight(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        enables_brightness = path == backlight / "brightness" and data.strip() != "0"
        enables_power = path == backlight / "bl_power" and data.strip() == "0"
        if enables_brightness or enables_power:
            assert framebuffer.read_bytes() == expected_frame
        return original_write_text(path, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", check_pixels_before_backlight)
    display.set_idle_stage("active")
    assert framebuffer.read_bytes() == expected_frame
    if power_only:
        assert (backlight / "bl_power").read_text() == "0\n"
    else:
        assert (backlight / "brightness").read_text() == "7\n"


def test_framebuffer_repeated_active_stage_does_not_restore_stale_pixels(tmp_path: Path) -> None:
    sysfs_root, framebuffer, _backlight = _fake_st7789_framebuffer(tmp_path)
    display = FramebufferDisplay(framebuffer, sysfs_root=sysfs_root)
    display.render(UiSnapshot(mode=UiMode.BOOTING, ftp_host="192.168.8.1"))
    display.set_idle_stage("screen_off")
    display.set_idle_stage("active")
    latest_pixels = b"\x01\x02\x03\x04"
    framebuffer.write_bytes(latest_pixels)
    display.set_idle_stage("active")
    assert framebuffer.read_bytes() == latest_pixels
