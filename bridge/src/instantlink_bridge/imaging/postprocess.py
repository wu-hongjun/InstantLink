"""Adjustment stage between source decode and model-aware transform.

Operates at full source resolution so RAW/HIF benefit from the high-fidelity
colour space; the model-size JPEG encode is the last step.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

__all__ = ["AdjustmentProfile", "apply_adjustments"]


@dataclass(frozen=True, slots=True)
class AdjustmentProfile:
    """Immutable description of all colour and overlay adjustments.

    All defaults are pass-through identity values — an ``AdjustmentProfile()``
    with no arguments applied via :func:`apply_adjustments` leaves every pixel
    unchanged.
    """

    saturation: float = 1.0
    """PIL ``ImageEnhance.Color`` factor. 1.0 = unchanged."""

    exposure: float = 0.0
    """EV stops. 0.0 = unchanged. Translates to ``2 ** (exposure / 2.0)``
    brightness factor in phase 3."""

    sharpness: float = 1.0
    """PIL ``ImageEnhance.Sharpness`` factor. 1.0 = unchanged."""

    hue: int = 0
    """Degrees of HSV hue rotation. 0 = unchanged."""

    datestamp: bool = False
    """Overlay flag. Renders EXIF DateTimeOriginal in the bottom-right corner."""

    watermark: bool = False
    """Overlay flag. Configurable text and position lands in phase 4."""


def apply_adjustments(image: Image.Image, profile: AdjustmentProfile) -> Image.Image:
    """Apply colour/overlay adjustments to ``image`` in place semantically.

    An identity profile returns the input image unchanged (same object
    or a byte-identical clone — see implementation note).

    Parameters
    ----------
    image:
        Source RGB image at full decode resolution.
    profile:
        Describes which adjustments to apply. An ``AdjustmentProfile()`` with
        all defaults is a fast-path no-op.

    Returns
    -------
    Image.Image
        Adjusted image. May be the same object as ``image`` when the profile
        is identity.
    """
    if profile == AdjustmentProfile():
        return image  # identity profile is a no-op fast path
    # All adjustments are implemented in later phases. For now any non-
    # default profile is also a no-op — phase 3 wires saturation/exposure/
    # sharpness/hue, phase 4 wires datestamp/watermark.
    return image
