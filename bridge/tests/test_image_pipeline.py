from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from typing import cast

import pytest
from PIL import Image

from instantlink_bridge.ble.models import PrinterModel, spec_for
from instantlink_bridge.imaging import pipeline
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    ImageTooLargeError,
    PrintEdit,
    UnsupportedImageError,
    chunk_image_data,
    create_preview_image,
    prepare_for_instantlink_backend,
    prepare_for_instax,
)
from instantlink_bridge.imaging.postprocess import AdjustmentProfile, apply_adjustments


@pytest.fixture
def source_jpeg(tmp_path: Path) -> Path:
    path = tmp_path / "source.jpg"
    Image.new("RGB", (1200, 900), (20, 90, 160)).save(path, format="JPEG", quality=95)
    return path


@pytest.mark.parametrize(
    "model",
    [PrinterModel.MINI, PrinterModel.MINI_LINK3, PrinterModel.SQUARE, PrinterModel.WIDE],
)
def test_prepare_for_instax_uses_model_dimensions(source_jpeg: Path, model: PrinterModel) -> None:
    prepared = prepare_for_instax(source_jpeg, model, fit=FitMode.CROP, quality=90)
    spec = spec_for(model)
    assert prepared.model == model
    assert prepared.width == spec.width
    assert prepared.height == spec.height
    assert len(prepared.data) <= spec.max_image_size

    image = Image.open(BytesIO(prepared.data))
    assert image.size == (spec.width, spec.height)


def test_prepare_for_instax_defaults_to_auto_fit(source_jpeg: Path) -> None:
    prepared = prepare_for_instax(source_jpeg, PrinterModel.MINI)

    assert prepared.fit is FitMode.AUTO


def test_auto_fit_rotates_landscape_for_mini_frame() -> None:
    image = Image.new("RGB", (1200, 800), (20, 90, 160))

    oriented = pipeline._auto_orient_for_target(image, 600, 800)

    assert oriented.size == (800, 1200)


def test_auto_fit_rotates_portrait_for_wide_frame() -> None:
    image = Image.new("RGB", (800, 1200), (20, 90, 160))

    oriented = pipeline._auto_orient_for_target(image, 1260, 840)

    assert oriented.size == (1200, 800)


def test_auto_fit_keeps_square_center_crop_unrotated() -> None:
    image = Image.new("RGB", (1200, 800), (20, 90, 160))

    oriented = pipeline._auto_orient_for_target(image, 800, 800)

    assert oriented is image


def test_print_edit_rotates_and_zooms_before_fit(source_jpeg: Path) -> None:
    edit = PrintEdit(rotate_degrees=90, zoom=1.5, offset_x=0.4, offset_y=-0.2)

    prepared = prepare_for_instax(source_jpeg, PrinterModel.MINI, edit=edit)

    assert prepared.model is PrinterModel.MINI
    assert prepared.width == 600
    assert prepared.height == 800


def test_instantlink_backend_preparation_leaves_model_flip_to_instantlink(tmp_path: Path) -> None:
    source = tmp_path / "bands.jpg"
    image = Image.new("RGB", (600, 800), (0, 0, 255))
    for y in range(400):
        for x in range(600):
            image.putpixel((x, y), (255, 0, 0))
    image.save(source, format="JPEG", quality=100)

    python_prepared = prepare_for_instax(source, PrinterModel.MINI_LINK3, fit=FitMode.STRETCH)
    instantlink_input = prepare_for_instantlink_backend(
        source,
        PrinterModel.MINI_LINK3,
        fit=FitMode.STRETCH,
    )

    with Image.open(BytesIO(python_prepared.data)) as python_image:
        python_top = python_image.convert("RGB").getpixel((300, 80))
    with Image.open(BytesIO(instantlink_input.data)) as instantlink_image:
        instantlink_top = instantlink_image.convert("RGB").getpixel((300, 80))

    assert python_top[2] > python_top[0]
    assert instantlink_top[0] > instantlink_top[2]


def test_create_preview_image_uses_lcd_bounds(source_jpeg: Path) -> None:
    preview = create_preview_image(
        source_jpeg,
        PrinterModel.WIDE,
        edit=PrintEdit(rotate_degrees=90, zoom=1.25),
        max_size=(120, 80),
    )

    assert preview.width <= 120
    assert preview.height <= 80
    assert preview.getpixel((0, 0)) == (252, 252, 247)


@pytest.mark.parametrize(
    ("model", "expected_landscape"),
    [
        (PrinterModel.MINI, False),
        (PrinterModel.MINI_LINK3, False),
        (PrinterModel.SQUARE, False),
        (PrinterModel.WIDE, True),
    ],
)
def test_create_preview_image_uses_instax_film_shape(
    source_jpeg: Path,
    model: PrinterModel,
    expected_landscape: bool,
) -> None:
    preview = create_preview_image(source_jpeg, model)

    assert (preview.width > preview.height) is expected_landscape
    assert preview.getpixel((0, preview.height - 1)) == (252, 252, 247)


def test_chunk_image_data_pads_final_chunk() -> None:
    chunks = chunk_image_data(b"x" * 5000, PrinterModel.SQUARE)
    assert len(chunks) == 3
    assert all(len(chunk) == spec_for(PrinterModel.SQUARE).chunk_size for chunk in chunks)


def test_hif_suffix_uses_heif_opener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_jpeg: Path,
) -> None:
    calls: list[bool] = []
    hif_path = tmp_path / "source.hif"
    hif_path.write_bytes(source_jpeg.read_bytes())
    monkeypatch.setitem(
        sys.modules,
        "pillow_heif",
        SimpleNamespace(register_heif_opener=lambda: calls.append(True)),
    )
    monkeypatch.setattr("instantlink_bridge.imaging.pipeline._HEIF_OPENER_REGISTERED", False)

    prepared = prepare_for_instax(hif_path, PrinterModel.MINI)

    assert calls == [True]
    assert prepared.model is PrinterModel.MINI


def test_hif_uses_thumbnailer_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_jpeg: Path,
) -> None:
    calls: list[list[str]] = []
    hif_path = tmp_path / "source.hif"
    hif_path.write_bytes(b"fake hif")

    def fake_run(
        args: list[str],
        *,
        check: bool,
        capture_output: bool,
        timeout: int,
    ) -> CompletedProcess[str]:
        calls.append(args)
        Path(args[-1]).write_bytes(source_jpeg.read_bytes())
        return CompletedProcess(args, 0)

    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.shutil.which", lambda _: "/bin/heif")
    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.subprocess.run", fake_run)

    prepared = prepare_for_instax(hif_path, PrinterModel.MINI)

    assert len(calls) == 1
    assert calls[0][:4] == ["/bin/heif", "-s", "1200", str(hif_path)]
    assert prepared.model is PrinterModel.MINI


def test_hif_square_keeps_conservative_thumbnailer_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_jpeg: Path,
) -> None:
    calls: list[list[str]] = []
    hif_path = tmp_path / "source.hif"
    hif_path.write_bytes(b"fake hif")

    def fake_run(
        args: list[str],
        *,
        check: bool,
        capture_output: bool,
        timeout: int,
    ) -> CompletedProcess[str]:
        calls.append(args)
        Path(args[-1]).write_bytes(source_jpeg.read_bytes())
        return CompletedProcess(args, 0)

    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.shutil.which", lambda _: "/bin/heif")
    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.subprocess.run", fake_run)

    prepared = prepare_for_instax(hif_path, PrinterModel.SQUARE)

    assert len(calls) == 1
    assert calls[0][:4] == ["/bin/heif", "-s", "1600", str(hif_path)]
    assert prepared.model is PrinterModel.SQUARE


def test_raw_errors_are_lcd_friendly(tmp_path: Path) -> None:
    raw_path = tmp_path / "image.arw"
    raw_path.write_bytes(b"not really raw")
    with pytest.raises(UnsupportedImageError, match="RAW"):
        prepare_for_instax(raw_path, PrinterModel.MINI)


def test_raw_uses_embedded_jpeg_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_jpeg: Path,
) -> None:
    raw_path = tmp_path / "image.arw"
    raw_path.write_bytes(b"fake raw")
    source_bytes = source_jpeg.read_bytes()

    class FakeRaw:
        sizes = SimpleNamespace(width=4000, height=3000)

        def __enter__(self) -> FakeRaw:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_thumb(self) -> SimpleNamespace:
            return SimpleNamespace(format="jpeg", data=source_bytes)

        def postprocess(self, **_kwargs: object) -> object:
            raise AssertionError("embedded JPEG preview should avoid RAW postprocess")

    fake_rawpy = SimpleNamespace(
        ThumbFormat=SimpleNamespace(JPEG="jpeg", BITMAP="bitmap"),
        imread=lambda _path: FakeRaw(),
    )
    monkeypatch.setitem(sys.modules, "rawpy", fake_rawpy)

    prepared = prepare_for_instax(raw_path, PrinterModel.MINI)

    assert prepared.model is PrinterModel.MINI


def test_raw_tiny_preview_falls_back_to_half_size_postprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "image.arw"
    raw_path.write_bytes(b"fake raw")
    tiny_preview = BytesIO()
    Image.new("RGB", (160, 120), (1, 2, 3)).save(tiny_preview, format="JPEG")
    calls: list[dict[str, object]] = []

    class FakeRaw:
        sizes = SimpleNamespace(width=4000, height=3000)

        def __enter__(self) -> FakeRaw:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_thumb(self) -> SimpleNamespace:
            return SimpleNamespace(format="jpeg", data=tiny_preview.getvalue())

        def postprocess(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return object()

    def fake_fromarray(_data: object) -> Image.Image:
        return Image.new("RGB", (2200, 1600), (20, 90, 160))

    fake_rawpy = SimpleNamespace(
        ThumbFormat=SimpleNamespace(JPEG="jpeg", BITMAP="bitmap"),
        imread=lambda _path: FakeRaw(),
    )
    monkeypatch.setitem(sys.modules, "rawpy", fake_rawpy)
    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.Image.fromarray", fake_fromarray)

    prepared = prepare_for_instax(raw_path, PrinterModel.MINI)

    assert calls
    assert calls[0]["half_size"] is True
    assert prepared.model is PrinterModel.MINI


def test_hif_fallback_rejects_large_image_without_thumbnailer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hif_path = tmp_path / "source.hif"
    hif_path.write_bytes(b"fake hif")

    class LargeHeifHeader:
        size = (9_000, 7_000)

    def fake_open(_path: Path) -> Image.Image:
        return cast(Image.Image, LargeHeifHeader())

    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.shutil.which", lambda _: None)
    monkeypatch.setattr("instantlink_bridge.imaging.pipeline._register_heif_opener", lambda: None)
    monkeypatch.setattr("instantlink_bridge.imaging.pipeline.Image.open", fake_open)

    with pytest.raises(ImageTooLargeError) as error:
        prepare_for_instax(hif_path, PrinterModel.MINI)

    assert error.value.unit == "pixels per edge"


def test_raw_large_fallback_rejects_before_postprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "image.arw"
    raw_path.write_bytes(b"fake raw")
    tiny_preview = BytesIO()
    Image.new("RGB", (160, 120), (1, 2, 3)).save(tiny_preview, format="JPEG")

    class FakeRaw:
        sizes = SimpleNamespace(width=9_000, height=7_000)

        def __enter__(self) -> FakeRaw:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_thumb(self) -> SimpleNamespace:
            return SimpleNamespace(format="jpeg", data=tiny_preview.getvalue())

        def postprocess(self, **_kwargs: object) -> object:
            raise AssertionError("large RAW fallback should fail before postprocess")

    fake_rawpy = SimpleNamespace(
        ThumbFormat=SimpleNamespace(JPEG="jpeg", BITMAP="bitmap"),
        imread=lambda _path: FakeRaw(),
    )
    monkeypatch.setitem(sys.modules, "rawpy", fake_rawpy)

    with pytest.raises(ImageTooLargeError) as error:
        prepare_for_instax(raw_path, PrinterModel.MINI)

    assert error.value.unit == "pixels per edge"


def test_identity_profile_does_not_change_pipeline_output(source_jpeg: Path) -> None:
    """Integration: calling prepare_for_instax twice with an identity profile
    must produce byte-identical output."""
    first = prepare_for_instax(source_jpeg, PrinterModel.MINI, fit=FitMode.CROP, quality=95)
    second = prepare_for_instax(source_jpeg, PrinterModel.MINI, fit=FitMode.CROP, quality=95)
    assert first.data == second.data


def test_apply_adjustments_identity_does_not_alter_pixels(source_jpeg: Path) -> None:
    """Integration: apply_adjustments with a default profile leaves pixel data
    unchanged — the postprocess stage is a no-op for the identity profile."""
    from PIL import Image as _Image

    with _Image.open(source_jpeg) as raw_img:
        rgb = raw_img.convert("RGB")

    result = apply_adjustments(rgb, AdjustmentProfile())
    assert result is rgb


def test_non_identity_adjustments_change_pipeline_output(source_jpeg: Path) -> None:
    """Integration (phase 3): a BridgeConfig with non-default adjustments produces
    output bytes that differ from the identity-profile output for the same fixture."""
    from instantlink_bridge.config import AdjustmentsConfig
    from instantlink_bridge.imaging.postprocess import AdjustmentProfile

    identity = prepare_for_instax(
        source_jpeg,
        PrinterModel.MINI,
        fit=FitMode.CROP,
        quality=95,
        adjustments=AdjustmentProfile(),
    )
    # Saturation=2.0 is a visible change on the non-grey fixture (20, 90, 160).
    adjusted = prepare_for_instax(
        source_jpeg,
        PrinterModel.MINI,
        fit=FitMode.CROP,
        quality=95,
        adjustments=AdjustmentProfile.from_config(AdjustmentsConfig(saturation=100)),
    )
    assert identity.data != adjusted.data, "Expected adjusted output to differ from identity output"
