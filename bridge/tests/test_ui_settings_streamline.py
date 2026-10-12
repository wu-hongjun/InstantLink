from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_ui_controller import _FakeDisplay, _FakePairer, _FakeStatusProvider
from test_ui_render import _drawn_texts

from instantlink_bridge.config import (
    BridgeConfig,
    FontSize,
    FtpConfig,
    PowerConfig,
    UiConfig,
    WorkflowConfig,
)
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.i18n import t
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiMode
from instantlink_bridge.ui.settings import SettingKey, SettingsPage


def _ui(tmp_path: Path, config: BridgeConfig | None = None) -> BridgeUi:
    printer = PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-12345678")
    ui = BridgeUi(
        config or BridgeConfig(),
        config_path=tmp_path / "config.toml",
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([printer]),
        status_provider=_FakeStatusProvider(),
    )
    ui._camera_receive_ready = True
    ui._snapshot = ui._build_snapshot(mode=UiMode.READY, paired_printer=printer, film_remaining=7)
    return ui


@pytest.mark.asyncio
async def test_leaving_settings_preserves_home_and_background_printer_poll(tmp_path: Path) -> None:
    ui = _ui(tmp_path)
    poll = asyncio.create_task(asyncio.Event().wait())
    ui._status_task = poll
    try:
        ui._show_settings(page=SettingsPage.MAIN)
        await ui._handle_action(UiAction.BACK)
        assert ui.snapshot.mode is UiMode.READY
        assert ui.snapshot.film_remaining == 7
        assert ui._status_task is poll
        assert not poll.cancelled()
        assert ui._pairer.list_calls == 0  # type: ignore[attr-defined]
    finally:
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [SettingKey.AUTO_PRINT_DELAY, SettingKey.IMAGE_FIT])
async def test_daily_print_choices_open_directly_and_return_to_same_row(
    tmp_path: Path, key: SettingKey
) -> None:
    ui = _ui(tmp_path)
    ui._show_settings(page=SettingsPage.PRINT)
    keys = ui._visible_keys_for_page(SettingsPage.PRINT)
    while keys[ui.snapshot.selected_index] is not key:
        await ui._handle_action(UiAction.DOWN)
    selected = ui.snapshot.selected_index
    await ui._handle_action(UiAction.SELECT)
    assert ui._settings_picker_key is key
    assert ui._settings_page is SettingsPage.PRINT
    await ui._handle_action(UiAction.BACK)
    assert ui._settings_picker_key is None
    assert ui.snapshot.settings_title == "Print"
    assert ui.snapshot.selected_index == selected


@pytest.mark.parametrize("delay", [1.0, 5.0])
def test_timed_review_help_does_not_claim_manual_confirmation(tmp_path: Path, delay: float) -> None:
    ui = _ui(tmp_path, BridgeConfig(workflow=WorkflowConfig(auto_print_delay_s=delay)))
    assert ui._settings_row_help(SettingKey.AUTO_PRINT_DELAY) == (
        "Review starts when preview is ready. Editing waits for KEY1."
    )


@pytest.mark.parametrize("duration,expected", [(600, "10min"), (7200, "2h"), (375, "375s")])
def test_shutdown_copy_uses_configured_timeout_and_localizes(
    tmp_path: Path, duration: float, expected: str
) -> None:
    config = BridgeConfig(
        power=PowerConfig(idle_poweroff_enabled=True, idle_poweroff_after_s=duration)
    )
    ui = _ui(tmp_path, config)
    row = ui._settings_row_for_key(SettingKey.SYSTEM_IDLE_POWEROFF, "")
    assert row.value == f"After {expected}"
    assert ui._settings_row_help(SettingKey.SYSTEM_IDLE_POWEROFF) == (
        f"Shuts down after {expected} idle"
    )
    assert t(row.value, "zh-Hans") == f"{expected}后"
    assert t(ui._settings_row_help(SettingKey.SYSTEM_IDLE_POWEROFF), "zh-Hans") == (
        f"空闲{expected}后关机"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("font_size", list(FontSize))
async def test_credential_details_show_every_character_and_return_to_same_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, font_size: FontSize
) -> None:
    password = "ABCDEFGH" * 8
    config = BridgeConfig(ftp=FtpConfig(password=password), ui=UiConfig(font_size=font_size))
    ui = _ui(tmp_path, config)
    ui._show_settings(page=SettingsPage.NETWORK)
    keys = ui._visible_keys_for_page(SettingsPage.NETWORK)
    while keys[ui.snapshot.selected_index] is not SettingKey.FTP_PASSWORD_INFO:
        await ui._handle_action(UiAction.DOWN)
    selected = ui.snapshot.selected_index
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.HELP_DIALOG
    assert ui.snapshot.help_dialog_body == password
    drawn = _drawn_texts(monkeypatch, ui.snapshot)
    body = "".join(
        text.replace(" ", "") for text in drawn if text and set(text) <= set(password + " ")
    )
    assert body == password
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert ui.snapshot.selected_index == selected


def test_settings_explanations_live_in_help_but_saved_and_error_notices_remain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = _ui(tmp_path)
    ui._show_settings(page=SettingsPage.PRINT)
    helper = ui.snapshot.settings_rows[0].help
    assert helper
    assert helper not in _drawn_texts(monkeypatch, ui.snapshot)
    assert "Saved" in _drawn_texts(monkeypatch, replace(ui.snapshot, settings_message="Saved"))
    assert "Config not writable" in _drawn_texts(
        monkeypatch, replace(ui.snapshot, settings_message="Config not writable")
    )


@pytest.mark.asyncio
async def test_slow_preview_exif_read_does_not_block_input_or_task_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from instantlink_bridge.ble.models import PrinterModel
    from instantlink_bridge.camera.ftp import ReceivedImage
    from instantlink_bridge.config import PrinterConfig
    from instantlink_bridge.imaging.pipeline import PrintEdit

    base = BridgeConfig()
    config = replace(
        base,
        printer=PrinterConfig(model=PrinterModel.SQUARE),
        adjustments=replace(base.adjustments, datestamp=True),
    )
    ui = _ui(tmp_path, config)
    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def slow_exif(_path: Path, _language: str, *, fmt: object) -> str:
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return "2026-10-11"

    monkeypatch.setattr(
        "instantlink_bridge.imaging.postprocess.read_exif_datestamp_text", slow_exif
    )
    task = asyncio.create_task(
        ui._prepare_preview_image(ReceivedImage(tmp_path / "photo.hif", "camera"), PrintEdit())
    )
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        await asyncio.wait_for(ui._handle_action(UiAction.SELECT), 0.05)
        assert ui.snapshot.mode is UiMode.SETTINGS
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.05)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
