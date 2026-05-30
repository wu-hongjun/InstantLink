"""Tests for instantlink_bridge.imaging.postprocess (phase 2 scaffolding)."""

from __future__ import annotations

from PIL import Image

from instantlink_bridge.imaging.postprocess import AdjustmentProfile, apply_adjustments


def _make_rgb(width: int = 64, height: int = 48) -> Image.Image:
    return Image.new("RGB", (width, height), (20, 90, 160))


def test_identity_profile_returns_same_object() -> None:
    """Fast path: a default AdjustmentProfile must return the exact same object."""
    img = _make_rgb()
    profile = AdjustmentProfile()
    result = apply_adjustments(img, profile)
    assert result is img


def test_apply_adjustments_does_not_mutate_input_metadata() -> None:
    """Size and mode must be unchanged after adjustment."""
    img = _make_rgb(100, 75)
    original_size = img.size
    original_mode = img.mode
    result = apply_adjustments(img, AdjustmentProfile())
    assert result.size == original_size
    assert result.mode == original_mode


def test_non_default_profile_still_no_op_in_phase_2() -> None:
    """Phase-2-only contract: any non-default field still produces an unmutated
    image. Phase 3 replaces this placeholder branch with real implementations."""
    img = _make_rgb()
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG")
    original_bytes = buf.getvalue()

    non_default_profile = AdjustmentProfile(
        saturation=0.5,
        exposure=1.0,
        sharpness=2.0,
        hue=45,
        datestamp=True,
        watermark=True,
    )
    result = apply_adjustments(img, non_default_profile)

    result_buf = BytesIO()
    result.save(result_buf, format="PNG")
    assert result_buf.getvalue() == original_bytes
    assert result.size == img.size
    assert result.mode == img.mode
