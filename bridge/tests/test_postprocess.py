"""Tests for instantlink_bridge.imaging.postprocess (phase 3)."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from instantlink_bridge.imaging.postprocess import AdjustmentProfile, apply_adjustments


def _make_rgb(
    color: tuple[int, int, int] = (200, 100, 50),
    size: tuple[int, int] = (32, 32),
) -> Image.Image:
    return Image.new("RGB", size, color)


def _checkerboard(size: int = 32) -> Image.Image:
    """2-tile checkerboard: alternating black/white tiles."""
    img = Image.new("RGB", (size, size), (0, 0, 0))
    half = size // 2
    for x in range(half, size):
        for y in range(0, half):
            img.putpixel((x, y), (255, 255, 255))
    for x in range(0, half):
        for y in range(half, size):
            img.putpixel((x, y), (255, 255, 255))
    return img


def _png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Identity / fast-path tests
# ---------------------------------------------------------------------------


def test_identity_profile_returns_same_object() -> None:
    """Fast path: a default AdjustmentProfile must return the exact same object."""
    img = _make_rgb()
    result = apply_adjustments(img, AdjustmentProfile())
    assert result is img


def test_apply_adjustments_preserves_size_and_mode() -> None:
    """Size and mode must be unchanged after any adjustment."""
    img = _make_rgb(size=(100, 75))
    for profile in [
        AdjustmentProfile(),
        AdjustmentProfile(saturation=2.0),
        AdjustmentProfile(exposure=2.0),
        AdjustmentProfile(sharpness=2.0),
        AdjustmentProfile(hue=90),
    ]:
        result = apply_adjustments(img, profile)
        assert result.size == img.size
        assert result.mode == img.mode


# ---------------------------------------------------------------------------
# Saturation axis
# ---------------------------------------------------------------------------


def test_saturation_boost_moves_channels_away_from_mean() -> None:
    """saturation=2.0 on a non-grey image pushes channels away from the mean."""
    img = _make_rgb((200, 100, 50))  # clearly non-grey
    result = apply_adjustments(img, AdjustmentProfile(saturation=2.0))

    orig_px = img.getpixel((0, 0))
    new_px = result.getpixel((0, 0))
    orig_mean = sum(orig_px) / 3
    new_mean = sum(new_px) / 3

    # The dominant channel (R=200) should be even further from the mean.
    orig_r_dist = abs(orig_px[0] - orig_mean)
    new_r_dist = abs(new_px[0] - new_mean)
    assert new_r_dist > orig_r_dist, f"R channel should be further from mean: {orig_px} → {new_px}"


def test_saturation_zero_produces_greyscale() -> None:
    """saturation=0.0 desaturates the image to greyscale."""
    img = _make_rgb((200, 100, 50))
    result = apply_adjustments(img, AdjustmentProfile(saturation=0.0))
    r, g, b = result.getpixel((0, 0))
    # All channels equal (greyscale), within rounding.
    assert abs(r - g) <= 1 and abs(g - b) <= 1, f"Expected greyscale but got ({r}, {g}, {b})"


# ---------------------------------------------------------------------------
# Exposure axis
# ---------------------------------------------------------------------------


def test_exposure_boost_brightens_all_channels() -> None:
    """exposure=2.0 brightens every channel (capped at 255)."""
    img = _make_rgb((100, 80, 60))
    result = apply_adjustments(img, AdjustmentProfile(exposure=2.0))
    orig_px = img.getpixel((0, 0))
    new_px = result.getpixel((0, 0))
    assert new_px[0] >= orig_px[0]
    assert new_px[1] >= orig_px[1]
    assert new_px[2] >= orig_px[2]


def test_exposure_half_darkens_all_channels() -> None:
    """exposure=0.5 darkens every channel."""
    img = _make_rgb((200, 160, 120))
    result = apply_adjustments(img, AdjustmentProfile(exposure=0.5))
    orig_px = img.getpixel((0, 0))
    new_px = result.getpixel((0, 0))
    assert new_px[0] <= orig_px[0]
    assert new_px[1] <= orig_px[1]
    assert new_px[2] <= orig_px[2]


# ---------------------------------------------------------------------------
# Sharpness axis
# ---------------------------------------------------------------------------


def test_sharpness_changes_edge_contrast() -> None:
    """Sharpness adjustment changes edge contrast on a checkerboard."""
    img = _checkerboard(32)

    sharpened = apply_adjustments(img.copy(), AdjustmentProfile(sharpness=2.0))
    blurred = apply_adjustments(img.copy(), AdjustmentProfile(sharpness=0.0))

    # Measure edge contrast as the mean absolute difference between
    # horizontally-adjacent pixels in the first row.
    def edge_metric(image: Image.Image) -> float:
        pixels = [image.getpixel((x, 0)) for x in range(image.width)]
        diffs = [abs(pixels[i + 1][0] - pixels[i][0]) for i in range(len(pixels) - 1)]
        return sum(diffs) / len(diffs)

    sharp_metric = edge_metric(sharpened)
    blur_metric = edge_metric(blurred)
    # After sharpening, edges are crisper; after blurring, softer.
    assert sharp_metric >= blur_metric, (
        f"Expected sharpened ({sharp_metric:.1f}) >= blurred ({blur_metric:.1f})"
    )


# ---------------------------------------------------------------------------
# Hue axis
# ---------------------------------------------------------------------------


def test_hue_180_rotation_on_red_yields_cyan() -> None:
    """hue=180 on a red image should produce a cyan-ish result.

    Red (H≈0°) + 180° → cyan (H≈180°). The R channel should decrease
    and the G+B channels should increase.
    """
    img = _make_rgb((220, 20, 20))
    result = apply_adjustments(img, AdjustmentProfile(hue=180))
    orig_r, orig_g, orig_b = img.getpixel((0, 0))
    new_r, new_g, new_b = result.getpixel((0, 0))
    # R should drop; G or B should rise.
    assert new_r < orig_r, f"R should drop after 180° hue rotation: {orig_r} → {new_r}"
    assert new_g > orig_g or new_b > orig_b, (
        f"G or B should rise after 180° hue rotation: ({orig_g},{orig_b}) → ({new_g},{new_b})"
    )


def test_hue_0_returns_unchanged_image() -> None:
    """hue=0 must be the identity — same pixel values."""
    img = _make_rgb((180, 90, 45))
    result = apply_adjustments(img, AdjustmentProfile(hue=0))
    assert result is img


# ---------------------------------------------------------------------------
# from_config factory
# ---------------------------------------------------------------------------


def test_from_config_identity_maps_to_identity_profile() -> None:
    """AdjustmentProfile.from_config on all-zero config produces identity values."""
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(saturation=0, exposure=0, sharpness=0, hue=0)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile == AdjustmentProfile(), f"Expected identity profile but got {profile}"


def test_from_config_plus100_saturation_maps_to_factor_2() -> None:
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(saturation=100)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile.saturation == pytest.approx(2.0)


def test_from_config_minus100_saturation_maps_to_factor_0() -> None:
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(saturation=-100)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile.saturation == pytest.approx(0.0)


def test_from_config_plus100_exposure_maps_to_factor_2() -> None:
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(exposure=100)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile.exposure == pytest.approx(2.0)


def test_from_config_minus100_exposure_maps_to_factor_half() -> None:
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(exposure=-100)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile.exposure == pytest.approx(0.5)


def test_from_config_hue_plus100_maps_to_180_degrees() -> None:
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(hue=100)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile.hue == 180


def test_from_config_hue_minus100_maps_to_minus180_degrees() -> None:
    from instantlink_bridge.config import AdjustmentsConfig

    cfg = AdjustmentsConfig(hue=-100)
    profile = AdjustmentProfile.from_config(cfg)
    assert profile.hue == -180
