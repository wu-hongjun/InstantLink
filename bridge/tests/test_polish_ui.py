from __future__ import annotations

import asyncio
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image
from test_preview_review import _ui as preview_ui
from test_ui_about_concurrency import INFO, STATS, _ui
from test_ui_controller import _FakeDisplay

from instantlink_bridge import app
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import AdjustmentsConfig, BridgeConfig
from instantlink_bridge.imaging.pipeline import PrintEdit
from instantlink_bridge.ui import display as display_module
from instantlink_bridge.ui.display import FramebufferDisplay
from instantlink_bridge.ui.models import PairedPrinter, UiMode, UiSnapshot
from instantlink_bridge.ui.render import _footer_label_lines
from instantlink_bridge.ui.settings import SettingKey, SettingsPage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        SettingKey.SYSTEM_CPU,
        SettingKey.SYSTEM_RAM,
        SettingKey.SYSTEM_STORAGE,
        SettingKey.SYSTEM_TEMPERATURE,
    ],
)
async def test_loading_about_detail_updates_by_key_and_preserves_explanation(
    monkeypatch: pytest.MonkeyPatch, key: SettingKey
) -> None:
    ui = _ui()
    ui._system_info = INFO
    started, release = asyncio.Event(), asyncio.Event()

    async def metrics() -> object:
        started.set()
        await release.wait()
        return STATS

    monkeypatch.setattr(ui, "_collect_about_metrics", metrics)
    ui._show_settings(page=SettingsPage.ABOUT)
    await asyncio.wait_for(started.wait(), 1)
    collector = ui._about_load_task
    assert collector is not None
    try:
        await ui._activate_setting(key)
        assert ui.snapshot.help_dialog_body == "—"
        release.set()
        await collector
        assert ui.snapshot.help_dialog_body == ui._settings_row_for_key(key, "").value
        ui._dismiss_help_dialog()
        ui._show_help_dialog(title="CPU", body="Explanation")
        await ui._collect_about_information()
        assert ui.snapshot.help_dialog_body == "Explanation"
    finally:
        release.set()
        await ui.stop()


@pytest.mark.asyncio
async def test_unlock_overlay_does_not_collect_about_until_fully_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = _ui()
    monkeypatch.setattr(ui, "_schedule_about_collection", lambda: None)
    ui._show_settings(page=SettingsPage.ABOUT)
    monkeypatch.undo()
    starts = 0

    async def collect() -> None:
        nonlocal starts
        starts += 1

    monkeypatch.setattr(ui, "_collect_about_information", collect)
    ui._lock_screen()
    await ui._begin_unlock("gpio:21")
    ui._system_info_snapshot()
    ui._system_stats_snapshot()
    await asyncio.sleep(0)
    assert ui._screen_locked and ui.snapshot.mode is UiMode.UNLOCKING
    assert starts == 0
    ui._advance_unlock("gpio:21")
    ui._advance_unlock("gpio:21")
    ui._system_info_snapshot()
    ui._system_stats_snapshot()
    await asyncio.sleep(0)
    assert starts == 1
    await ui.stop()


@pytest.mark.asyncio
async def test_review_duration_includes_full_interval_after_first_timed_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ui = preview_ui(_FakeDisplay())
    visible_at: float | None = None
    show = ui._show_print_preview

    def slow_render(
        received: ReceivedImage, remaining: float | None, timeout: float | None, **kwargs: object
    ) -> None:
        nonlocal visible_at
        show(received, remaining, timeout, **kwargs)
        if remaining is not None and ui._preview_image is not None and visible_at is None:
            time.sleep(0.06)
            visible_at = asyncio.get_running_loop().time()

    async def build(*_args: object) -> Image.Image:
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(ui, "_show_print_preview", slow_render)
    monkeypatch.setattr(ui, "_build_preview_image", build)
    try:
        edit = await ui.await_print_confirmation(
            ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=0.15
        )
        assert edit is not None and visible_at is not None
        assert asyncio.get_running_loop().time() - visible_at >= 0.14
    finally:
        await ui.stop()


def test_error_footer_describes_sync_action() -> None:
    sync = UiSnapshot(mode=UiMode.ERROR, ftp_host="", sync_destination="iphone")
    printing = UiSnapshot(mode=UiMode.ERROR, ftp_host="", sync_destination="printer")
    assert _footer_label_lines(sync)[0][2] == "KEY3 iPhone"
    assert _footer_label_lines(printing)[0][2] == "KEY3 Check"


def test_framebuffer_closes_owned_gpio_backlight_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    closed: list[bool] = []
    backlight = display_module._GpioBacklight(SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(
        display_module, "_framebuffer_name", lambda *_, **__: display_module.ST7789_FRAMEBUFFER_NAME
    )
    monkeypatch.setattr(display_module, "_framebuffer_backlight", lambda *_, **__: None)
    monkeypatch.setattr(display_module._GpioBacklight, "try_open", lambda: backlight)
    display = FramebufferDisplay(tmp_path / "fb", sysfs_root=tmp_path)
    display.close()
    display.close()
    assert closed == [True]


@pytest.mark.asyncio
async def test_failed_input_close_still_closes_printer_provider_and_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = _ui()
    closed: list[str] = []

    def fail() -> None:
        raise OSError("GPIO close failed")

    async def close_printer() -> None:
        closed.append("printer")

    async def close_provider() -> None:
        closed.append("provider")

    monkeypatch.setattr(ui._input, "close", fail)
    monkeypatch.setattr(ui, "_close_cached_printer_session", close_printer)
    monkeypatch.setattr(ui._status_provider, "close", close_provider)
    monkeypatch.setattr(ui._display, "close", lambda: closed.append("display"))
    with pytest.raises(OSError, match="GPIO close failed"):
        await ui.stop()
    assert closed == ["printer", "provider", "display"]


@pytest.mark.asyncio
async def test_cancelled_sender_joins_metadata_before_releasing_photo_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"original")
    started, release, finished = Event(), Event(), Event()

    def read(path: Path, *_args: object, **_kwargs: object) -> str:
        started.set()
        assert release.wait(2)
        assert path.read_bytes() == b"original"
        finished.set()
        return "date"

    monkeypatch.setattr("instantlink_bridge.imaging.postprocess.read_exif_datestamp_text", read)
    owner = asyncio.create_task(
        app.send_print_to_printer(
            PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-TEST"),
            ReceivedImage(source, "camera"),
            BridgeConfig(adjustments=AdjustmentsConfig(datestamp=True)),
            PrintEdit(),
            lambda _progress: None,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        for _ in range(2):
            owner.cancel()
            await asyncio.sleep(0)
            assert not owner.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, 1)
        assert finished.is_set()
        source.unlink()
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)
