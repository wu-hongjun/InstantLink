from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from instantlink_bridge.imaging.postprocess import read_exif_datestamp_text


def camera_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[34665] = {36867: "2026:10:12 14:30:00"}
    return exif


def test_camera_nested_exif_original_date_is_read(tmp_path: Path) -> None:
    path = tmp_path / "camera.jpg"
    Image.new("RGB", (16, 16)).save(path, exif=camera_exif())
    assert read_exif_datestamp_text(path, "en") == "Oct 12, 2026"


def test_hif_metadata_registers_parent_opener_and_never_decodes_pixels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from instantlink_bridge.imaging import pipeline

    registered = False

    def register() -> None:
        nonlocal registered
        registered = True

    class MetadataImage:
        def __enter__(self) -> MetadataImage:
            return self

        def __exit__(self, *_args: object) -> None:
            return

        def getexif(self) -> Image.Exif:
            assert registered, "HIF opener registration must precede Image.open"
            exif = Image.Exif()
            exif[36867] = "2026:10:12 14:30:00"
            return exif

        def load(self) -> None:
            pytest.fail("date metadata must not decode pixel data")

        def convert(self, *_args: object) -> None:
            pytest.fail("date metadata must not convert pixel data")

    monkeypatch.setattr(pipeline, "_register_heif_opener", register)
    monkeypatch.setattr(Image, "open", lambda _path: MetadataImage())
    assert read_exif_datestamp_text(tmp_path / "camera.HIF", "en") == "Oct 12, 2026"


def test_real_hif_nested_metadata_is_read_without_pixel_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    from pillow_heif.as_plugin import HeifImageFile

    path = tmp_path / "camera.hif"
    pillow_heif.from_pillow(Image.new("RGB", (16, 16))).save(path, exif=camera_exif().tobytes())

    def fail_pixel_load(_image: object) -> None:
        pytest.fail("HIF date metadata must not load full pixel data")

    monkeypatch.setattr(HeifImageFile, "load", fail_pixel_load)
    assert read_exif_datestamp_text(path, "en") == "Oct 12, 2026"
