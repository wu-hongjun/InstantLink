"""Tests for plan 036 phase 2: draw_slider primitive.

Pixel-level assertions use the default track_height=6, thumb_width=8, so
the track occupies rows y .. y+5 and the thumb occupies rows y-3 .. y+8
(track_cy = y+3, thumb extends ±6 from there).
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from instantlink_bridge.ui.render import draw_slider
from instantlink_bridge.ui.theme import theme_for

# Use light theme for pixel assertions (colours are well-defined).
THEME = theme_for("light")

# Helper: pixel at (px, py) in a fresh image rendered by draw_slider.
def _render(
    value: int,
    min_value: int = -100,
    max_value: int = 100,
    w: int = 100,
    x: int = 10,
    y: int = 20,
    symmetric: bool = True,
) -> tuple[Image.Image, int]:
    """Return (image, thumb_cx) for the given slider parameters."""
    img = Image.new("RGB", (240, 240), THEME.bg)
    draw = ImageDraw.Draw(img)
    thumb_cx = draw_slider(
        draw,
        x,
        y,
        w,
        value,
        min_value,
        max_value,
        theme=THEME,
        symmetric=symmetric,
    )
    return img, thumb_cx


def _pixel(img: Image.Image, px: int, py: int) -> tuple[int, int, int]:
    r, g, b = img.getpixel((px, py))  # type: ignore[misc]
    return (r, g, b)


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------------------------
# test_slider_value_zero_centres_thumb_on_zero_line
# ---------------------------------------------------------------------------


def test_slider_value_zero_centres_thumb_on_zero_line() -> None:
    """Symmetric range [-100, +100], value=0: thumb_cx should be x + w//2 = 60."""
    _, thumb_cx = _render(value=0, min_value=-100, max_value=100, w=100, x=10)
    # zero_x for [-100,+100] range: 10 + int(100 * (0 - (-100)) / 200) = 10 + 50 = 60
    assert thumb_cx == 60, f"Expected thumb_cx=60, got {thumb_cx}"


# ---------------------------------------------------------------------------
# test_slider_value_positive_fills_right_half
# ---------------------------------------------------------------------------


def test_slider_value_positive_fills_right_half() -> None:
    """value=+50 → fill covers zero_x..thumb_cx; pixel at x+60 should be accent_blue."""
    # zero_x = 10 + 50 = 60; thumb_cx = 10 + int(100 * 150/200) = 10 + 75 = 85
    img, _thumb_cx = _render(value=50, min_value=-100, max_value=100, w=100, x=10, y=20)

    accent_blue = _hex_to_rgb(THEME.accent_blue)
    surface_elevated = _hex_to_rgb(THEME.surface_elevated)

    # A pixel between zero_x (60) and thumb_cx (85) should be accent_blue.
    # Use track_cy = y + 3 = 23 for a pixel that's strictly inside the fill.
    fill_pixel = _pixel(img, 70, 23)
    assert fill_pixel == accent_blue, (
        f"Expected accent_blue {accent_blue} at fill zone, got {fill_pixel}"
    )

    # A pixel left of zero_x (e.g. x+45=55) should be surface_elevated (unfilled track).
    unfilled_pixel = _pixel(img, 55, 23)
    assert unfilled_pixel == surface_elevated, (
        f"Expected surface_elevated {surface_elevated} left of zero, got {unfilled_pixel}"
    )


# ---------------------------------------------------------------------------
# test_slider_value_negative_fills_left_half
# ---------------------------------------------------------------------------


def test_slider_value_negative_fills_left_half() -> None:
    """value=-50 → fill covers thumb_cx..zero_x; pixel at x+40 should be accent_blue."""
    # zero_x = 60; thumb_cx = 10 + int(100 * 50/200) = 10 + 25 = 35
    img, _thumb_cx = _render(value=-50, min_value=-100, max_value=100, w=100, x=10, y=20)

    accent_blue = _hex_to_rgb(THEME.accent_blue)
    surface_elevated = _hex_to_rgb(THEME.surface_elevated)

    # A pixel between thumb_cx (35) and zero_x (60): x+45=55, track_cy=23
    fill_pixel = _pixel(img, 45, 23)
    assert fill_pixel == accent_blue, (
        f"Expected accent_blue {accent_blue} in fill zone, got {fill_pixel}"
    )

    # A pixel right of zero_x: x+70=80, should be surface_elevated
    unfilled_pixel = _pixel(img, 80, 23)
    assert unfilled_pixel == surface_elevated, (
        f"Expected surface_elevated {surface_elevated} right of zero, got {unfilled_pixel}"
    )


# ---------------------------------------------------------------------------
# test_slider_asymmetric_fills_from_left
# ---------------------------------------------------------------------------


def test_slider_asymmetric_fills_from_left() -> None:
    """symmetric=False, range [0,100], value=75 → left ~3/4 filled."""
    # thumb_cx = 10 + int(100 * 75/100) = 10 + 75 = 85
    # Fill region: x=10 .. thumb_cx=85, track_cy = 20+3 = 23
    img, _thumb_cx = _render(
        value=75, min_value=0, max_value=100, w=100, x=10, y=20, symmetric=False
    )

    accent_blue = _hex_to_rgb(THEME.accent_blue)
    surface_elevated = _hex_to_rgb(THEME.surface_elevated)

    # Pixel at x+30=40, track_cy=23 → inside fill
    fill_pixel = _pixel(img, 40, 23)
    assert fill_pixel == accent_blue, (
        f"Expected accent_blue {accent_blue} in asymmetric fill, got {fill_pixel}"
    )

    # Pixel at x+95=105, track_cy=23 → outside fill (beyond thumb)
    unfilled_pixel = _pixel(img, 105, 23)
    assert unfilled_pixel == surface_elevated, (
        f"Expected surface_elevated {surface_elevated} beyond thumb, got {unfilled_pixel}"
    )


# ---------------------------------------------------------------------------
# test_slider_thumb_clamps_inside_track
# ---------------------------------------------------------------------------


def test_slider_thumb_clamps_inside_track() -> None:
    """value=+100 → thumb_cx clamped to x + w - thumb_width//2 = 10+100-4 = 106."""
    _, thumb_cx = _render(value=100, min_value=-100, max_value=100, w=100, x=10)
    # raw_cx = 10 + int(100 * 200/200) = 10 + 100 = 110
    # clamped: x + w - thumb_width//2 = 10 + 100 - 4 = 106
    assert thumb_cx == 106, f"Expected clamped thumb_cx=106, got {thumb_cx}"


def test_slider_thumb_clamps_min_inside_track() -> None:
    """value=-100 → thumb_cx clamped to x + thumb_width//2 = 10+4 = 14."""
    _, thumb_cx = _render(value=-100, min_value=-100, max_value=100, w=100, x=10)
    # raw_cx = 10 + int(100 * 0/200) = 10
    # clamped: x + thumb_width//2 = 10 + 4 = 14
    assert thumb_cx == 14, f"Expected clamped thumb_cx=14, got {thumb_cx}"


# ---------------------------------------------------------------------------
# test_slider_returns_thumb_cx
# ---------------------------------------------------------------------------


def test_slider_returns_thumb_cx() -> None:
    """Confirm return value matches the expected formula for an unclamped position."""
    # value=25, range [-100,+100], w=100, x=10
    # raw_cx = 10 + int(100 * (25 - (-100)) / 200) = 10 + int(100 * 125/200) = 10 + 62 = 72
    # Not clamped (14 <= 72 <= 106).
    _, thumb_cx = _render(value=25, min_value=-100, max_value=100, w=100, x=10)
    assert thumb_cx == 72, f"Expected thumb_cx=72, got {thumb_cx}"


# ---------------------------------------------------------------------------
# test_slider_degenerate_range
# ---------------------------------------------------------------------------


def test_slider_degenerate_range() -> None:
    """min_value == max_value → thumb centred, no crash."""
    img, thumb_cx = _render(value=0, min_value=50, max_value=50, w=100, x=10)
    assert thumb_cx == 60, f"Expected degenerate thumb_cx=60, got {thumb_cx}"
    assert img.size == (240, 240)
