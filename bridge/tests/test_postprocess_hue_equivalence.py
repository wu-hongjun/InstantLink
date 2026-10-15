"""Exact pixel regression oracle for the hue allocation optimization (plan 099)."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from instantlink_bridge.imaging import postprocess


# Frozen pre-optimization implementation: keep its independent selection and
# rounding expressions so these tests detect output changes, including +/- 1.
def _reference_hue(image: Image.Image, degrees: int) -> Image.Image:
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
    result = Image.fromarray(out_u8)
    return result


def _edge_and_random_image() -> Image.Image:
    import numpy as np

    pixels = np.random.default_rng(9917).integers(0, 256, size=(32, 512, 3), dtype=np.uint8)
    # All neutral intensities (delta == 0), ties for max channel, and values
    # either side of channel boundaries exercise every HSV selection branch.
    values = np.arange(256, dtype=np.uint8)
    pixels[0, :256] = values[:, None]
    for row, channels in enumerate(((0, 1), (0, 2), (1, 2)), start=1):
        pixels[row, :256] = 0
        pixels[row, :256, channels[0]] = values
        pixels[row, :256, channels[1]] = values
        pixels[row, 256:] = 255
        pixels[row, 256:, channels[0]] = values
        pixels[row, 256:, channels[1]] = values
    return Image.fromarray(pixels)


@pytest.mark.parametrize("degrees", range(-180, 181))
def test_hue_matches_original_for_every_degree(degrees: int) -> None:
    image = _edge_and_random_image()
    original = image.tobytes()
    expected = _reference_hue(image, degrees)
    actual = postprocess._apply_hue(image, degrees)
    assert actual.mode == expected.mode == "RGB"
    assert actual.size == expected.size == image.size
    assert actual.tobytes() == expected.tobytes()
    assert image.tobytes() == original


@pytest.mark.parametrize("size", [(1, 1), (1, 37), (37, 1), (13, 29), (29, 13)])
@pytest.mark.parametrize("degrees", [-721, -360, 360, 721])
def test_hue_preserves_small_images_and_wraparound(size: tuple[int, int], degrees: int) -> None:
    image = _edge_and_random_image().resize(size)
    assert (
        postprocess._apply_hue(image, degrees).tobytes() == _reference_hue(image, degrees).tobytes()
    )


@pytest.mark.parametrize("hue", [-180, -1, 17, 90, 179])
def test_combined_profile_pixels_and_jpeg_match_original(
    hue: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _edge_and_random_image().resize((1031, 517))
    original = image.tobytes()
    profile = postprocess.AdjustmentProfile(
        hue=hue,
        saturation=1.2,
        exposure=0.85,
        sharpness=1.3,
        vignette=37,
        datestamp=True,
        datestamp_text="26.10.15",
        watermark=True,
        watermark_text="InstantLink",
    )
    with monkeypatch.context() as patch:
        patch.setattr(postprocess, "_apply_hue", _reference_hue)
        expected = postprocess.apply_adjustments(image, profile)
    actual = postprocess.apply_adjustments(image, profile)
    assert actual.tobytes() == expected.tobytes()
    assert image.tobytes() == original
    expected_jpeg, actual_jpeg = BytesIO(), BytesIO()
    expected.save(expected_jpeg, format="JPEG", quality=95)
    actual.save(actual_jpeg, format="JPEG", quality=95)
    assert actual_jpeg.getvalue() == expected_jpeg.getvalue()


@pytest.mark.parametrize(
    "size",
    [(511, 255), (512, 256), (513, 257), (1031, 517), (517, 1031), (20003, 3), (3, 20003)],
)
@pytest.mark.parametrize("degrees", [-180, -1, 17, 90, 179])
def test_hue_tiles_match_original_at_both_boundaries(size: tuple[int, int], degrees: int) -> None:
    import numpy as np

    pixels = np.random.default_rng(9918).integers(
        0, 256, size=(size[1], size[0], 3), dtype=np.uint8
    )
    image = Image.fromarray(pixels)
    original = image.tobytes()
    expected = _reference_hue(image, degrees)
    actual = postprocess._apply_hue(image, degrees)
    assert actual.mode == expected.mode == "RGB"
    assert actual.size == expected.size == size
    assert actual.tobytes() == expected.tobytes()
    assert image.tobytes() == original


@pytest.mark.parametrize("size", [(0, 0), (0, 19), (19, 0)])
def test_empty_hue_axes_preserve_original_result(size: tuple[int, int]) -> None:
    image = Image.new("RGB", size)
    expected = _reference_hue(image, 17)
    actual = postprocess._apply_hue(image, 17)
    assert actual.mode == expected.mode == "RGB"
    assert actual.size == expected.size == size
    assert actual.tobytes() == expected.tobytes() == b""


@pytest.mark.parametrize("mode", ["LA"])
def test_hue_unsupported_modes_preserve_original_error(mode: str) -> None:
    image = _edge_and_random_image().resize((513, 257)).convert(mode)
    with pytest.raises(IndexError) as original:
        _reference_hue(image, 17)
    with pytest.raises(type(original.value)):
        postprocess._apply_hue(image, 17)


@pytest.mark.parametrize("mode", ["L", "P", "RGBA", "CMYK", "HSV", "YCbCr"])
def test_non_rgb_hue_uses_original_array_boundary(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Non-RGB modes were outside the contract: RGBA/CMYK leave channel four
    # unwritten; grayscale/palette leave columns unwritten. Do not assert undefined bytes or
    # accidentally add a conversion while introducing the RGB-only tile path.
    image = _edge_and_random_image().resize((513, 257)).convert(mode)
    sentinel = Image.new("RGB", image.size)

    def helper(source: Image.Image, degrees: int) -> Image.Image:
        assert source is image
        assert degrees == 17
        return sentinel

    monkeypatch.setattr(postprocess, "_apply_hue_tile", helper)
    assert postprocess._apply_hue(image, 17) is sentinel


@pytest.mark.parametrize("source_format", ["JPEG", "PNG", "BMP", "TIFF"])
def test_decoded_rgb_formats_and_metadata_match_original(source_format: str) -> None:
    source = _edge_and_random_image().resize((1031, 517))
    buffer = BytesIO()
    source.save(buffer, format=source_format)
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        image = decoded.convert("RGB")
        image.info["example_metadata"] = "not propagated by the original hue helper"
        expected = _reference_hue(image, 17)
        actual = postprocess._apply_hue(image, 17)
    assert actual.tobytes() == expected.tobytes()
    assert actual.info == expected.info == {}
