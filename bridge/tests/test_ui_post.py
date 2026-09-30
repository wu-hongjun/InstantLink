"""Post settings remain independent and readable on the native LCD."""

from dataclasses import replace

import pytest
from PIL import ImageDraw

from instantlink_bridge.config import BridgeConfig, CorrectionConfig
from instantlink_bridge.ui import render
from instantlink_bridge.ui.models import PairedPrinter, SettingsRow, UiMode, UiSnapshot
from instantlink_bridge.ui.settings import (
    SETTINGS_BY_PAGE,
    SETTINGS_PARENT_PAGE,
    SettingKey,
    SettingsPage,
    config_with_setting_value,
    setting_options,
    workflow_label,
)


def test_correction_survives_look_changes_and_look_survives_correction() -> None:
    config = BridgeConfig(correction=CorrectionConfig(saturation=50))
    vivid = config_with_setting_value(config, SettingKey.ADJUST_PRESET, "Vivid")
    assert vivid.correction.saturation == 50
    corrected = config_with_setting_value(vivid, SettingKey.CORRECTION_SATURATION, 30)
    assert corrected.adjustments == vivid.adjustments
    assert corrected.correction.saturation == 30
    assert SETTINGS_PARENT_PAGE[SettingsPage.CORRECTION] is SettingsPage.POST
    assert SETTINGS_PARENT_PAGE[SettingsPage.ADJUSTMENTS] is SettingsPage.POST
    assert SETTINGS_BY_PAGE[SettingsPage.POST] == (
        SettingKey.OPEN_ADJUSTMENTS,
        SettingKey.OPEN_CORRECTION,
    )


def test_workflow_names_describe_preserved_values() -> None:
    assert [(o.label, o.value) for o in setting_options(SettingKey.AUTO_PRINT_DELAY)] == [
        ("Confirm each", None),
        ("Print immediately", 0.0),
        ("Review 5s", 5.0),
    ]
    assert workflow_label(8.0) == "Review 8s"
    keys = SETTINGS_BY_PAGE[SettingsPage.AUTO_PRINT]
    assert keys.index(SettingKey.ALLOW_PRINT_WITHOUT_FILM) > keys.index(
        SettingKey.PRINT_ADVANCED_HEADER
    )


@pytest.mark.parametrize("size", ["small", "medium", "large"])
@pytest.mark.parametrize("language", ["en", "zh-Hans"])
def test_settings_title_never_overlaps_status_or_counter(
    monkeypatch: pytest.MonkeyPatch,
    size: str,
    language: str,
) -> None:
    texts: list[tuple[float, float]] = []
    dots: list[tuple[float, float]] = []
    original_text = render._text
    original_ellipse = ImageDraw.ImageDraw.ellipse

    def text_spy(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        text: str,
        font: render.Font,
        fill: str,
    ) -> None:
        if y < render.STATUS_BAR_H:
            texts.append((x, x + render._text_width(draw, text, font)))
        return original_text(draw, x, y, text, font, fill)

    def ellipse_spy(
        self: ImageDraw.ImageDraw,
        xy: tuple[int, int, int, int],
        fill: str | None = None,
        outline: str | None = None,
        width: int = 1,
    ) -> None:
        dots.append((xy[0], xy[2]))
        return original_ellipse(self, xy, fill=fill, outline=outline, width=width)

    monkeypatch.setattr(render, "_text", text_spy)
    monkeypatch.setattr(ImageDraw.ImageDraw, "ellipse", ellipse_spy)
    render.render_snapshot(
        UiSnapshot(
            mode=UiMode.SETTINGS,
            ftp_host="192.168.8.1",
            language=language,
            font_size=size,
            settings_title="A very long post processing title",
            settings_rows=tuple(SettingsRow("Row", "") for _ in range(100)),
            selected_index=99,
        )
    )
    assert len(texts) == 2
    assert len(dots) == 1
    assert texts[0][1] + 8 <= dots[0][0]
    assert dots[0][1] + 8 <= texts[1][0]
    assert texts[1][1] <= 232


def test_ready_copy_identifies_printer_battery_and_post_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copy: list[str] = []
    original = render._text

    def spy(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        text: str,
        font: render.Font,
        fill: str,
    ) -> None:
        copy.append(text)
        return original(draw, x, y, text, font, fill)

    monkeypatch.setattr(render, "_text", spy)
    snapshot = UiSnapshot(
        mode=UiMode.READY,
        ftp_host="192.168.8.1",
        camera_receive_ready=True,
        printer_status_fresh=True,
        film_remaining=7,
        printer_battery=80,
        paired_printer=PairedPrinter(address="AA", name="INSTAX-12345678"),
        look_name="Default",
        workflow_label="Confirm each",
        correction_saturation=50,
    )
    render.render_snapshot(snapshot)
    assert "Printer battery: " in copy
    assert "Confirm each" in copy
    assert "+50%" in copy
    assert "Host: " not in copy
    copy.clear()
    render.render_snapshot(replace(snapshot, mode=UiMode.PRINT_COMPLETE))
    assert "Print complete" in copy
    assert "Film ejecting" not in copy


@pytest.mark.asyncio
async def test_correction_editor_previews_commits_and_cancels_independently() -> None:
    from instantlink_bridge.ui.controller import BridgeUi
    from instantlink_bridge.ui.display import NullDisplay
    from instantlink_bridge.ui.input import NullInput
    from instantlink_bridge.ui.models import UiAction

    config = BridgeConfig(correction=CorrectionConfig(saturation=50))
    ui = BridgeUi(config, display=NullDisplay(), input_device=NullInput())
    ui._show_settings(page=SettingsPage.CORRECTION)
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.ADJUSTMENT_EDIT
    await ui._handle_action(UiAction.UP)
    assert ui.snapshot.correction_saturation == 60
    assert ui._config.correction.saturation == 50
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.settings_title == "Correction"
    assert ui.snapshot.correction_saturation == 50
    assert ui._config.adjustments == config.adjustments
    await ui._handle_action(UiAction.SELECT)
    await ui._handle_action(UiAction.UP)
    await ui._handle_action(UiAction.SELECT)
    assert ui._config.correction.saturation == 60
    assert ui._config.adjustments == config.adjustments
    assert ui.snapshot.settings_title == "Correction"
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.settings_title == "Post"


@pytest.mark.parametrize("size", ["small", "medium", "large"])
@pytest.mark.parametrize("mode", [UiMode.AWAITING_CONFIRM, UiMode.PRINTING, UiMode.ADJUSTMENT_EDIT])
def test_photo_screen_text_fits_above_footer(
    monkeypatch: pytest.MonkeyPatch,
    size: str,
    mode: UiMode,
) -> None:
    from PIL import Image

    body_bounds: list[tuple[int, int, int, int]] = []
    original = render._text

    def spy(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        text: str,
        font: render.Font,
        fill: str,
    ) -> None:
        if render.STATUS_BAR_H <= y < render.HINT_BAR_Y:
            bounds = draw.textbbox((x, y), text, font=font)
            body_bounds.append(tuple(int(v) for v in bounds))
        original(draw, x, y, text, font, fill)

    monkeypatch.setattr(render, "_text", spy)
    render.render_snapshot(
        UiSnapshot(
            mode=mode,
            ftp_host="192.168.8.1",
            font_size=size,
            print_title="Sending to printer" if mode is UiMode.PRINTING else "Print in 5s",
            preview_image=Image.new("RGB", (112, 112)),
            preview_tool="crop",
            adjustment_edit_key="correction_saturation",
            adjustment_edit_value=50,
        )
    )
    assert body_bounds
    assert all(0 <= x0 < x1 <= 240 and y1 <= render.HINT_BAR_Y for x0, _, x1, y1 in body_bounds)
