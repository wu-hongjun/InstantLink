"""Adjustment stage between source decode and model-aware transform.

Operates at full source resolution so RAW/HIF benefit from the high-fidelity
colour space; the model-size JPEG encode is the last step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from instantlink_bridge.config import AdjustmentsConfig  # pragma: no cover

__all__ = ["AdjustmentProfile", "apply_adjustments"]

# The five discrete picker values exposed in UI (-100, -50, 0, +50, +100).
ADJUSTMENT_PICKER_VALUES: tuple[int, ...] = (-100, -50, 0, 50, 100)


@dataclass(frozen=True, slots=True)
class AdjustmentProfile:
    """Immutable description of all colour and overlay adjustments.

    All defaults are pass-through identity values — an ``AdjustmentProfile()``
    with no arguments applied via :func:`apply_adjustments` leaves every pixel
    unchanged.

    Internal float representation
    ------------------------------
    * ``saturation``: PIL ``ImageEnhance.Color`` factor. 1.0 = unchanged;
      0.0 = greyscale; 2.0 = double saturation.
    * ``exposure``: brightness factor derived from EV stops as
      ``2 ** (ev_stops / 1.0)`` where ev_stops in [-1, +1]. 1.0 = unchanged.
      Range: 0.5 (-1 EV) ... 2.0 (+1 EV), capped by design so Instax prints
      survive extreme inputs.
    * ``sharpness``: PIL ``ImageEnhance.Sharpness`` factor. 1.0 = unchanged;
      0.0 = blurred; 2.0 = double sharpness.
    * ``hue``: degrees of HSV hue rotation. 0 = unchanged; ±180 = full invert.
    """

    saturation: float = 1.0
    """PIL ``ImageEnhance.Color`` factor. 1.0 = unchanged."""

    exposure: float = 1.0
    """Brightness multiplicative factor. 1.0 = unchanged."""

    sharpness: float = 1.0
    """PIL ``ImageEnhance.Sharpness`` factor. 1.0 = unchanged."""

    hue: int = 0
    """Degrees of HSV hue rotation. 0 = unchanged."""

    datestamp: bool = False
    """Overlay flag. Renders EXIF DateTimeOriginal in the bottom-right corner."""

    watermark: bool = False
    """Overlay flag. Configurable text and position lands in phase 4."""

    @classmethod
    def from_config(cls, config: AdjustmentsConfig) -> AdjustmentProfile:
        """Build a profile from user-facing -100...+100 integer config values.

        Mapping:
        * saturation: ``factor = 1.0 + value / 100.0``
          -100 => 0.0 (greyscale), 0 => 1.0, +100 => 2.0.
        * exposure: ``factor = 2 ** (value / 100.0)``
          -100 => 0.5 (~-1 EV), 0 => 1.0, +100 => 2.0 (+1 EV).
        * sharpness: ``factor = 1.0 + value / 100.0``
          -100 => 0.0 (blurred), 0 => 1.0, +100 => 2.0.
        * hue: ``degrees = value * 1.8``
          -100 => -180 deg, 0 => 0 deg, +100 => +180 deg.
        """
        return cls(
            saturation=1.0 + config.saturation / 100.0,
            exposure=2.0 ** (config.exposure / 100.0),
            sharpness=1.0 + config.sharpness / 100.0,
            hue=int(config.hue * 1.8),
        )


_IDENTITY = AdjustmentProfile()


def apply_adjustments(image: Image.Image, profile: AdjustmentProfile) -> Image.Image:
    """Apply colour/overlay adjustments to ``image`` in place semantically.

    Application order: hue → saturation → exposure → sharpness.

    Hue is applied first because it operates on the original colour space;
    the subsequent saturation, exposure, and sharpness adjustments are linear
    and commutative with each other but not with hue rotation. Applying hue
    last would interact with any saturation shift applied before it and
    produce slightly different results for combined profiles.

    Each axis short-circuits when the value equals the identity so a mixed
    profile (e.g. only saturation changed) pays only for the operations
    it actually needs.

    An identity profile (all defaults) returns the input image object
    unchanged — no copy, no PIL call.

    Datestamp and watermark overlays land in phase 4.

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
    if profile == _IDENTITY:
        return image  # identity profile: fast path, no copy

    out = image

    # --- Hue rotation (NumPy RGB→HSV channel roll→RGB) -------------------
    if profile.hue != 0:
        out = _apply_hue(out, profile.hue)

    # --- Saturation (PIL ImageEnhance.Color) ------------------------------
    if profile.saturation != 1.0:
        from PIL import ImageEnhance

        out = ImageEnhance.Color(out).enhance(profile.saturation)

    # --- Exposure (PIL ImageEnhance.Brightness) ---------------------------
    if profile.exposure != 1.0:
        from PIL import ImageEnhance

        out = ImageEnhance.Brightness(out).enhance(profile.exposure)

    # --- Sharpness (PIL ImageEnhance.Sharpness) ---------------------------
    if profile.sharpness != 1.0:
        from PIL import ImageEnhance

        out = ImageEnhance.Sharpness(out).enhance(profile.sharpness)

    return out


def _apply_hue(image: Image.Image, degrees: int) -> Image.Image:
    """Rotate the HSV hue channel by ``degrees`` using NumPy array math.

    Converts RGB → HSV, shifts H by ``degrees / 360.0`` (wrapping [0, 1)),
    converts back to RGB. Uses only NumPy ufuncs — no per-pixel Python
    loops, no ``colorsys``.
    """
    import numpy as np  # lazy import keeps module load cheap

    arr = np.asarray(image, dtype=np.float32) / 255.0  # H×W×3, range [0,1]

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    c_max = np.maximum(np.maximum(r, g), b)
    c_min = np.minimum(np.minimum(r, g), b)
    delta = c_max - c_min

    # --- H channel -------------------------------------------------------
    safe_delta = np.where(delta == 0, 1.0, delta)
    h = np.where(
        delta == 0,
        0.0,
        np.where(
            c_max == r,
            ((g - b) / safe_delta) % 6.0,
            np.where(
                c_max == g,
                (b - r) / safe_delta + 2.0,
                (r - g) / safe_delta + 4.0,
            ),
        ),
    )
    h = h / 6.0  # normalise to [0, 1)

    # Apply rotation (wrap with modulo so result stays in [0, 1)).
    shift = (degrees % 360) / 360.0
    h = (h + shift) % 1.0

    # --- S channel -------------------------------------------------------
    safe_cmax = np.where(c_max == 0, 1.0, c_max)
    s = np.where(c_max == 0, 0.0, delta / safe_cmax)

    # --- V channel -------------------------------------------------------
    v = c_max

    # --- HSV → RGB -------------------------------------------------------
    h6 = h * 6.0
    i = np.floor(h6).astype(np.int32) % 6
    f = h6 - np.floor(h6)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    out = np.empty_like(arr)
    for channel, (v0, v1, v2, v3, v4, v5) in enumerate(
        [
            (v, q, p, p, t, v),
            (t, v, v, q, p, p),
            (p, p, t, v, v, q),
        ]
    ):
        out[..., channel] = np.where(
            i == 0,
            v0,
            np.where(
                i == 1,
                v1,
                np.where(
                    i == 2,
                    v2,
                    np.where(
                        i == 3,
                        v3,
                        np.where(i == 4, v4, v5),
                    ),
                ),
            ),
        )

    out_u8 = (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    result = Image.fromarray(out_u8, mode="RGB")
    return result
