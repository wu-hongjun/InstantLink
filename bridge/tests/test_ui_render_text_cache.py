"""Exact glyph-cache equivalence and bounded retention, without LCD hardware."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from instantlink_bridge.ui import render
from instantlink_bridge.ui.models import SettingsRow, UiMode, UiSnapshot


@pytest.fixture(autouse=True)
def clear_text_caches() -> None:
    render._cached_text_mask.cache_clear()
    render._cached_text_bbox.cache_clear()
    render._has_font_variations.cache_clear()


@pytest.mark.parametrize("anchor", [None, "rm", "mm", "la", "rt", "ls"])
@pytest.mark.parametrize("xy", [(8, 12), (-17, -4), (225, 230)])
@pytest.mark.parametrize("text", ["jÁg £ 0/10", "中文 English", "", "   "])
def test_cached_mask_is_exact_on_coloured_background(
    anchor: str | None, xy: tuple[int, int], text: str
) -> None:
    font = render._font(20, prefer_cjk=True)
    expected = Image.new("RGB", (240, 240), "#176e8f")
    ImageDraw.Draw(expected).text(xy, text, font=font, fill="#b9d143", anchor=anchor)
    for _ in range(2):  # both a fresh raster and a cached raster
        actual = Image.new("RGB", expected.size, "#176e8f")
        render._draw_text(
            ImageDraw.Draw(actual), xy, text, font=font, fill="#b9d143", anchor=anchor
        )
        assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "1"])
@pytest.mark.parametrize("text", ["two\nlines", "x" * 300, "Plain"])
def test_fallback_modes_and_multiline_preserve_pillow(mode: str, text: str) -> None:
    font = render._font(16)
    expected = Image.new(mode, (240, 240))
    actual = expected.copy()
    # White converts identically for every tested image mode.
    ImageDraw.Draw(expected).text((3, 4), text, font=font, fill="white")
    render._draw_text(ImageDraw.Draw(actual), (3, 4), text, font=font, fill="white")
    assert actual.tobytes() == expected.tobytes()
    if mode != "RGB" or text != "Plain":
        assert render._cached_text_mask.cache_info().currsize == 0


def test_fractional_coordinate_uses_original_raster_origin() -> None:
    font = render._font(17)
    expected = Image.new("RGB", (240, 240))
    actual = expected.copy()
    ImageDraw.Draw(expected).text((-1.25, 6.75), "Fraction", font=font, fill="white")
    render._draw_text(ImageDraw.Draw(actual), (-1.25, 6.75), "Fraction", font=font, fill="white")  # type: ignore[arg-type]
    assert actual.tobytes() == expected.tobytes()
    assert render._cached_text_mask.cache_info().currsize == 0


def test_font_core_replacement_invalidates_metrics_and_mask() -> None:
    original = render._font(14).font_variant(size=14)
    replacement = original.font_variant(size=26)
    draw = ImageDraw.Draw(Image.new("RGB", (240, 240)))
    text = "Width and glyphs"
    before = render._text_bbox(draw, text, original)
    render._draw_text(draw, (0, 0), text, font=original, fill="white")
    original.font = replacement.font
    after = render._text_bbox(draw, text, original)
    expected = Image.new("RGB", (240, 240))
    ImageDraw.Draw(expected).text((0, 0), text, font=original, fill="white")
    actual = Image.new("RGB", expected.size)
    render._draw_text(ImageDraw.Draw(actual), (0, 0), text, font=original, fill="white")
    assert after == tuple(int(v) for v in draw.textbbox((0, 0), text, font=original))
    assert before != after
    assert actual.tobytes() == expected.tobytes()
    assert render._cached_text_mask.cache_info().currsize == 2


def test_variable_fonts_bypass_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    font = render._font(14).font_variant(size=14)
    monkeypatch.setattr(font, "get_variation_axes", lambda: [])
    draw = ImageDraw.Draw(Image.new("RGB", (240, 240)))
    assert render._text_bbox(draw, "Variable", font) == draw.textbbox((0, 0), "Variable", font=font)
    render._draw_text(draw, (0, 0), "Variable", font=font, fill="white")
    assert render._cached_text_bbox.cache_info().currsize == 0
    assert render._cached_text_mask.cache_info().currsize == 0


def test_cjk_sibling_change_resolves_actual_font_before_cache() -> None:
    primary = render._font(14).font_variant(size=14)
    for size in (14, 22):
        sibling = render._font(size, prefer_cjk=True)
        primary.cjk_sibling = sibling
        expected = Image.new("RGB", (240, 240), "#b34d89")
        ImageDraw.Draw(expected).text((10, 12), "中文 English", font=sibling, fill="white")
        actual = Image.new("RGB", expected.size, "#b34d89")
        draw = ImageDraw.Draw(actual)
        render._text(draw, 10, 12, "中文 English", primary, "white")
        assert actual.tobytes() == expected.tobytes()
        bbox = draw.textbbox((0, 0), "中文 English", font=sibling)
        assert render._text_width(draw, "中文 English", primary) == int(bbox[2] - bbox[0])


def test_cache_entry_and_mask_dimensions_are_bounded() -> None:
    font = render._font(10)
    draw = ImageDraw.Draw(Image.new("RGB", (240, 240)))
    for index in range(600):
        text = f"Changing {index}"
        render._text_bbox(draw, text, font)
        render._draw_text(draw, (0, 0), text, font=font, fill="white")
    assert render._cached_text_bbox.cache_info().currsize == 512
    assert render._cached_text_mask.cache_info().currsize == 256
    oversized = render._cached_text_mask("W" * 100, font, font.font, None)
    assert oversized is None
    oversized_height = render._font(80)
    assert render._cached_text_mask("M", oversized_height, oversized_height.font, None) is None
    long_text = "x" * 10000
    bbox_info = render._cached_text_bbox.cache_info()
    render._text_bbox(draw, long_text, font)
    assert render._cached_text_bbox.cache_info() == bbox_info


@pytest.mark.parametrize("appearance", ["light", "dark"])
@pytest.mark.parametrize("language", ["en", "zh-Hans"])
@pytest.mark.parametrize("font_size", ["small", "medium", "large"])
def test_all_modes_cold_and_warm_exact_against_uncached_drawing(
    monkeypatch: pytest.MonkeyPatch, appearance: str, language: str, font_size: str
) -> None:
    base = UiSnapshot(
        mode=UiMode.READY,
        ftp_host="192.168.8.1",
        appearance=appearance,
        language=language,
        font_size=font_size,
        printer_status_fresh=True,
        film_remaining=4,
        camera_receive_ready=True,
        settings_rows=(SettingsRow("Post", "Correction"), SettingsRow("Lock", "3 presses")),
        preview_image=Image.new("RGB", (80, 100), "#6381a4"),
        adjustment_edit_key="adjust_saturation",
        unlock_presses=2,
        print_progress_percent=40,
    )
    preview_before = base.preview_image.tobytes() if base.preview_image is not None else None
    for mode in UiMode:
        snapshot = replace(base, mode=mode)
        render._cached_text_bbox.cache_clear()
        render._cached_text_mask.cache_clear()
        with monkeypatch.context() as patch:
            patch.setattr(render, "_cacheable_text_font", lambda text, font: False)
            expected = render.render_snapshot(snapshot, now=1.25).tobytes()
        actual = render.render_snapshot(snapshot, now=1.25)
        assert actual.tobytes() == expected, mode
        # Caller mutation cannot poison glyph stamps or the next output frame.
        actual.paste("red", (0, 0, 240, 240))
        assert render.render_snapshot(snapshot, now=2.5).tobytes() == expected, mode
    assert base.preview_image is not None
    assert base.preview_image.tobytes() == preview_before
