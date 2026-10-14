"""Lightweight image contracts shared by configuration, UI and preparation workers.

Importing these values must not load Pillow or image decoders. Pixel transforms
remain in the preparation pipeline and postprocessing modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from instantlink_bridge.ble.models import PrinterModel

if TYPE_CHECKING:
    from instantlink_bridge.config import AdjustmentsConfig, CorrectionConfig

SourceIdentity = tuple[str, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class WorkingImageCache:
    """One parent's ephemeral, lossless normalized source for repeated photo edits."""

    path: Path
    source_identity: SourceIdentity
    model: PrinterModel


def source_identity(path: Path) -> SourceIdentity:
    """Include replacement and same-size edits, without hashing or decoding the source."""
    resolved = path.resolve()
    info = resolved.stat()
    return (
        str(resolved),
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class ImagePipelineError(RuntimeError):
    """Base image pipeline error."""


class ImagePreparationTimeoutError(ImagePipelineError):
    """Raised when image preparation exceeds its deadline."""


class UnsupportedImageError(ImagePipelineError):
    """Raised when the source is not a supported camera still image."""


class ImageTooLargeError(ImagePipelineError):
    """Raised when an image exceeds an encoded or decoded safety limit."""

    def __init__(self, size: int, maximum: int, unit: str = "bytes") -> None:
        super().__init__(f"image too large: {size} {unit} (max {maximum} {unit})")
        self.size = size
        self.maximum = maximum
        self.unit = unit

    def __reduce__(self) -> tuple[type[ImageTooLargeError], tuple[int, int, str]]:
        return (self.__class__, (self.size, self.maximum, self.unit))


class FitMode(StrEnum):
    """How to fit source pixels to the printer aspect ratio."""

    AUTO = "auto"
    CROP = "crop"
    CONTAIN = "contain"
    STRETCH = "stretch"


@dataclass(frozen=True, slots=True)
class PrintEdit:
    """Per-photo preview edits chosen on the LCD before printing."""

    rotate_degrees: int = 0
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """Prepared JPEG for a specific Instax printer model."""

    data: bytes
    model: PrinterModel
    width: int
    height: int
    quality: int
    fit: FitMode
    transport_flip_applied: bool = False


def parse_fit_mode(value: str) -> FitMode:
    """Parse a user/config fit mode value."""

    normalized = value.strip().lower()
    try:
        return FitMode(normalized)
    except ValueError as error:
        supported = ", ".join(mode.value for mode in FitMode)
        raise ValueError(f"unsupported fit mode {value!r}; expected one of {supported}") from error


def _working_size_for_model(width: int, height: int) -> tuple[int, int]:
    if (width, height) == (600, 800):
        return (MINI_WORKING_EDGE, MINI_WORKING_EDGE)
    return (max(width, DEFAULT_WORKING_EDGE), max(height, DEFAULT_WORKING_EDGE))


HEIF_SUFFIXES = {".hif", ".heif", ".heic"}

MINI_WORKING_EDGE = 1200

DEFAULT_WORKING_EDGE = 1600


@dataclass(frozen=True, slots=True)
class CorrectionProfile:
    """Printer compensation applied after the creative Look at print resolution."""

    saturation: float = 1.0


def correction_profile(config: CorrectionConfig) -> CorrectionProfile:
    """Resolve the persistent correction without changing Look values or presets."""
    return CorrectionProfile(saturation=1.0 + config.saturation / 100.0)


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

    vignette: int = 0
    """Corner-darkening strength. 0 = off (identity), 100 = heavy. One-sided: no negative values."""

    datestamp: bool = False
    """Overlay flag. When True and datestamp_text is non-empty, renders it bottom-right."""

    watermark: bool = False
    """Overlay flag. When True and watermark_text is non-empty, renders it bottom-left."""

    datestamp_text: str = ""
    """Pre-formatted datestamp string. Empty string disables the overlay even if datestamp=True.

    The controller formats EXIF DateTimeOriginal + locale before building the profile so
    apply_adjustments stays locale-agnostic.
    """

    watermark_text: str = ""
    """Watermark label to stamp. Empty string disables the overlay even if watermark=True."""

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

        Note: datestamp_text is NOT set here — the caller (controller / app.py)
        must read EXIF and format the date, then pass datestamp_text explicitly.
        watermark_text is taken from config.watermark_text.
        """
        return cls(
            saturation=1.0 + config.saturation / 100.0,
            exposure=2.0 ** (config.exposure / 100.0),
            sharpness=1.0 + config.sharpness / 100.0,
            hue=int(config.hue * 1.8),
            vignette=config.vignette,
            datestamp=config.datestamp,
            watermark=config.watermark,
            datestamp_text="",  # caller fills this in after reading EXIF
            watermark_text=config.watermark_text if config.watermark else "",
        )
