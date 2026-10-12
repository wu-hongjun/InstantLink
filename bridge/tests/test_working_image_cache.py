from __future__ import annotations

import asyncio
import os
import sys
from contextlib import suppress
from pathlib import Path
from threading import Event, current_thread

import pytest
from PIL import Image

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.imaging import pipeline
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    PrintEdit,
    UnsupportedImageError,
    WorkingImageCache,
    prepare_for_instantlink_backend,
    source_identity,
)
from instantlink_bridge.imaging.postprocess import AdjustmentProfile, CorrectionProfile
from instantlink_bridge.imaging.worker import ImagePreparationWorker


def fake_hif(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    counter = tmp_path / "decode-count"
    thumbnailer = tmp_path / "heif-thumbnailer"
    thumbnailer.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys, time\n"
        "from PIL import Image, ImageDraw\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))\n"
        "source = pathlib.Path(sys.argv[-2]).read_bytes()\n"
        "if source.startswith(b'WAIT'): time.sleep(30)\n"
        "if source.startswith(b'FAIL'): sys.exit(1)\n"
        "image = Image.new('RGB', (90, 60), (source[0], 100, 170))\n"
        "ImageDraw.Draw(image).rectangle((4, 6, 40, 22), fill=(210, 110, 70))\n"
        "exif = Image.Exif(); exif[274] = 6\n"
        "image.save(sys.argv[-1], format='PNG', exif=exif)\n"
    )
    thumbnailer.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    source = tmp_path / "photo.HIF"
    source.write_bytes(b"AAAA")
    return source, counter


def decode_count(counter: Path) -> int:
    return int(counter.read_text()) if counter.exists() else 0


def test_real_lazy_heif_fallback_materializes_before_parallel_cache_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    source = tmp_path / "fallback.HIF"
    photo = Image.new("RGB", (32, 24))
    photo.putdata([(x * 7, y * 9, (x + y) * 4) for y in range(24) for x in range(32)])
    pillow_heif.from_pillow(photo).save(source, quality=95)
    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: None)
    edit = PrintEdit(zoom=1.3, offset_x=0.2)
    reference = prepare_for_instantlink_backend(source, PrinterModel.SQUARE, edit=edit)
    cache = WorkingImageCache(
        tmp_path / "working.bmp", source_identity(source), PrinterModel.SQUARE
    )
    with Image.open(source) as lazy:
        assert lazy.mode == "RGB" and lazy._heif_file is not None
        heif_image_type = type(lazy)

    preparation_thread = current_thread().name
    lazy_decode_threads: list[str] = []
    writer_entered = Event()
    foreground_loaded = Event()
    original_load = heif_image_type.load
    original_fit = pipeline._fit_image

    def controlled_load(image: Image.Image) -> object:
        is_writer = current_thread().name == "image-working-cache"
        is_lazy = image._heif_file is not None
        if is_writer:
            writer_entered.set()
        if is_lazy:
            lazy_decode_threads.append(current_thread().name)
            if is_writer:
                # Recreate the overlapping writer/fit lazy-load entry safely:
                # let foreground decode first rather than corrupting plugin state.
                assert foreground_loaded.wait(2)
        result = original_load(image)
        if not is_writer:
            foreground_loaded.set()
        return result

    def controlled_fit(image: Image.Image, width: int, height: int, fit: FitMode) -> Image.Image:
        assert writer_entered.wait(2)
        return original_fit(image, width, height, fit)

    monkeypatch.setattr(heif_image_type, "load", controlled_load)
    monkeypatch.setattr(pipeline, "_fit_image", controlled_fit)
    prepared = prepare_for_instantlink_backend(
        source, PrinterModel.SQUARE, edit=edit, working_cache=cache
    )
    assert lazy_decode_threads == [preparation_thread]
    assert cache.path.exists()
    assert prepared == reference
    assert (
        prepare_for_instantlink_backend(source, PrinterModel.SQUARE, edit=edit, working_cache=cache)
        == reference
    )
    assert lazy_decode_threads == [preparation_thread]  # BMP hit never decodes HEIF again


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [PrinterModel.SQUARE, PrinterModel.MINI_LINK3])
async def test_lossless_cache_reuses_decode_across_edits_and_preserves_exact_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: PrinterModel
) -> None:
    source, counter = fake_hif(tmp_path, monkeypatch)
    worker = ImagePreparationWorker()
    profile = AdjustmentProfile(hue=18, sharpness=1.1, vignette=15, saturation=1.2)
    correction = CorrectionProfile(saturation=1.3)
    cases = [
        (PrintEdit(), FitMode.AUTO),
        (PrintEdit(zoom=1.2, offset_x=0.2), FitMode.CROP),
        (PrintEdit(rotate_degrees=90, zoom=1.4, offset_y=-0.3), FitMode.CONTAIN),
    ]
    cached = []
    try:
        for edit, fit in cases:
            cached.append(
                await worker.prepare(
                    source,
                    model,
                    fit=fit,
                    edit=edit,
                    adjustments=profile,
                    correction=correction,
                    apply_model_flip=False,
                )
            )
        assert decode_count(counter) == 1
        cache = worker._working_cache
        assert cache is not None and cache.path.exists()
        assert cache.path.stat().st_size < 90 * 60 * 4 + 1024
        for prepared, (edit, fit) in zip(cached, cases, strict=True):
            reference = prepare_for_instantlink_backend(
                source,
                model,
                fit=fit,
                edit=edit,
                adjustments=profile,
                correction=correction,
            )
            assert prepared == reference  # bytes, quality, dimensions, framing all unchanged
        assert len({prepared.data for prepared in cached}) == len(cases)
        directory = cache.path.parent
    finally:
        await worker.aclose()
    assert not directory.exists()


@pytest.mark.asyncio
async def test_cache_invalidates_replacement_new_photo_model_and_working_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, counter = fake_hif(tmp_path, monkeypatch)
    worker = ImagePreparationWorker()
    try:
        first = await worker.prepare(source, PrinterModel.SQUARE)
        cache = worker._working_cache
        assert cache is not None
        old = cache.path.parent
        stamp = source.stat().st_mtime_ns
        replacement = tmp_path / "replace.HIF"
        replacement.write_bytes(b"BBBB")
        os.utime(replacement, ns=(stamp, stamp))
        replacement.replace(source)  # same path, size and mtime; changed inode/ctime
        changed = await worker.prepare(source, PrinterModel.SQUARE)
        assert decode_count(counter) == 2 and not old.exists()
        assert first.data != changed.data
        await worker.prepare(
            source, PrinterModel.SQUARE, quality=75, adjustments=AdjustmentProfile(saturation=1.4)
        )
        assert decode_count(counter) == 2  # Look/quality do not belong to decoded pixels
        await worker.prepare(source, PrinterModel.MINI)
        assert decode_count(counter) == 3
        await worker.prepare(source, PrinterModel.MINI_LINK3)
        assert decode_count(counter) == 4  # same working edge, different model still invalidates
        new_photo = tmp_path / "next.HIF"
        new_photo.write_bytes(b"CCCC")
        await worker.prepare(new_photo, PrinterModel.MINI_LINK3)
        assert decode_count(counter) == 5
        cache = worker._working_cache
        assert cache is not None
        only_directory = cache.path.parent
        assert len(list(only_directory.iterdir())) == 1
    finally:
        await worker.aclose()
    assert not only_directory.exists()


@pytest.mark.asyncio
async def test_cache_ttl_expiration_releases_file_and_redecodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, counter = fake_hif(tmp_path, monkeypatch)
    worker = ImagePreparationWorker(working_cache_ttl_s=0.02)
    try:
        first = await worker.prepare(source, PrinterModel.SQUARE)
        cache = worker._working_cache
        assert cache is not None
        directory = cache.path.parent
        await asyncio.sleep(0.04)
        assert worker._working_cache is None and not directory.exists()
        second = await worker.prepare(source, PrinterModel.SQUARE)
        assert second == first and decode_count(counter) == 2
    finally:
        await worker.aclose()


@pytest.mark.asyncio
async def test_cancel_cleans_cache_and_partial_write_after_decoder_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, counter = fake_hif(tmp_path, monkeypatch)
    source.write_bytes(b"WAIT")
    worker = ImagePreparationWorker(poll_interval_s=0.005, shutdown_grace_s=0.1)
    task = asyncio.create_task(worker.prepare(source, PrinterModel.SQUARE))
    try:

        async def wait_for_decoder() -> None:
            while not counter.exists():  # noqa: ASYNC110 - external decoder writes marker
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait_for_decoder(), 3)
        cache = worker._working_cache
        assert cache is not None
        directory = cache.path.parent
        cache.path.with_suffix(".pending").write_bytes(b"partial cache fixture")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert worker._working_cache is None and not directory.exists()
        source.write_bytes(b"GOOD")
        await worker.prepare(source, PrinterModel.SQUARE)
        assert decode_count(counter) == 2
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await worker.aclose()


@pytest.mark.asyncio
async def test_failed_decode_and_corrupt_cache_never_produce_stale_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, counter = fake_hif(tmp_path, monkeypatch)
    worker = ImagePreparationWorker()
    try:
        first = await worker.prepare(source, PrinterModel.SQUARE)
        cache = worker._working_cache
        assert cache is not None
        cache.path.write_bytes(b"corrupt")
        assert await worker.prepare(source, PrinterModel.SQUARE) == first
        assert decode_count(counter) == 2
        source.write_bytes(b"FAIL")
        with pytest.raises(UnsupportedImageError):
            await worker.prepare(source, PrinterModel.SQUARE)
        assert worker._working_cache is None
        source.write_bytes(b"GOOD")
        last = await worker.prepare(source, PrinterModel.SQUARE)
        assert last.data != first.data
    finally:
        await worker.aclose()


@pytest.mark.parametrize("ttl", [-1.0, float("inf"), float("nan")])
def test_working_cache_requires_bounded_lifetime(ttl: float) -> None:
    with pytest.raises(ValueError, match="finite and nonnegative"):
        ImagePreparationWorker(working_cache_ttl_s=ttl)
