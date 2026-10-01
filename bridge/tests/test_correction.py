from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.config import (
    AdjustmentsConfig,
    BridgeConfig,
    CorrectionConfig,
    load_config,
    write_config,
)
from instantlink_bridge.imaging.pipeline import (
    create_preview_from_prepared,
    prepare_for_instantlink_backend,
)
from instantlink_bridge.imaging.postprocess import (
    AdjustmentProfile,
    CorrectionProfile,
    apply_correction,
    correction_profile,
)
from instantlink_bridge.imaging.worker import prepare_for_instax_async
from instantlink_bridge.manager.config_payload import (
    ConfigValidationError,
    apply_config_diff,
    serialize_config,
)


def test_legacy_config_preserves_look_and_neutral_correction(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[adjustments]\nsaturation = 50\n")
    loaded = load_config(path)
    assert loaded.adjustments.saturation == 50
    assert loaded.correction == CorrectionConfig()
    changed = replace(loaded, correction=CorrectionConfig(saturation=20))
    write_config(changed, path)
    assert load_config(path) == changed


@pytest.mark.parametrize("value", [True, False, "20", 20.0, -101, 101])
def test_correction_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        CorrectionConfig(saturation=value)  # type: ignore[arg-type]
    with pytest.raises(ConfigValidationError) as error:
        apply_config_diff(BridgeConfig(), {"correction": {"saturation": value}})
    assert "correction.saturation" in error.value.field_errors


def test_correction_api_diff_does_not_change_look() -> None:
    original = BridgeConfig(adjustments=AdjustmentsConfig(saturation=50))
    changed = apply_config_diff(original, {"correction": {"saturation": 20}})
    assert changed.adjustments == original.adjustments
    assert serialize_config(changed)["correction"] == {"saturation": 20}
    new_look = apply_config_diff(changed, {"adjustments": {"preset": "Vivid"}})
    assert new_look.correction == changed.correction
    assert correction_profile(changed.correction) == CorrectionProfile(saturation=1.2)


def test_correction_neutral_identity_and_colour_compensation() -> None:
    image = Image.new("RGB", (5, 5), (150, 100, 80))
    assert apply_correction(image, CorrectionProfile()) is image
    corrected = apply_correction(image, CorrectionProfile(saturation=1.3))
    rgb = corrected.getpixel((0, 0))
    assert isinstance(rgb, tuple)
    assert max(rgb) - min(rgb) > 150 - 80
    assert image.getpixel((0, 0)) == (150, 100, 80)
    monochrome = Image.new("RGB", (5, 5), (100, 100, 100))
    assert apply_correction(monochrome, CorrectionProfile(saturation=1.3)).tobytes() == (
        monochrome.tobytes()
    )


@pytest.mark.asyncio
async def test_corrected_worker_matches_inline_and_lcd_preview(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (900, 900), (150, 100, 80)).save(source)
    neutral = prepare_for_instantlink_backend(source, PrinterModel.SQUARE)
    explicit_neutral = prepare_for_instantlink_backend(
        source, PrinterModel.SQUARE, correction=CorrectionProfile()
    )
    assert explicit_neutral.data == neutral.data
    profile = CorrectionProfile(saturation=1.3)
    look = AdjustmentProfile(saturation=0.8)
    expected = prepare_for_instantlink_backend(
        source, PrinterModel.SQUARE, adjustments=look, correction=profile
    )
    actual = await prepare_for_instax_async(
        source,
        PrinterModel.SQUARE,
        adjustments=look,
        correction=profile,
        apply_model_flip=False,
    )
    assert actual.data == expected.data
    with Image.open(BytesIO(actual.data)) as final:
        pixel = final.getpixel((final.width // 2, final.height // 2))
    preview = create_preview_from_prepared(actual)
    preview_pixel = preview.getpixel((preview.width // 2, preview.height // 2))
    assert preview_pixel == pixel
