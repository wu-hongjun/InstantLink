from __future__ import annotations

import asyncio
import ctypes
import gc
import threading
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageOps

from instantlink_bridge.ble.instantlink import InstantLinkBackend
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.imaging.pipeline import (
    ImagePipelineError,
    create_preview_from_prepared,
    prepare_for_instantlink_backend,
)
from instantlink_bridge.printing import PrintProgress


def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.jpg"
    image = Image.new("RGB", (600, 800), (30, 100, 180))
    image.paste((210, 40, 70), (0, 0, 200, 200))
    image.save(path, quality=100)
    return path


class LegacyLibrary:
    def __init__(self) -> None:
        self.legacy: list[bytes] = []
        self.paths: list[Path] = []

    def instantlink_print_with_progress(
        self,
        path: bytes,
        _quality: ctypes.c_uint8,
        _fit: ctypes.c_uint8,
        _option: ctypes.c_uint8,
        callback: Callable[[int, int], None],
    ) -> int:
        _ = _quality, _fit, _option
        self.paths.append(Path(path.decode()))
        self.legacy.append(self.paths[-1].read_bytes())
        callback(1, 1)
        return 0


class PreparedLibrary(LegacyLibrary):
    def __init__(self, *, result: int = 0) -> None:
        super().__init__()
        self.result = result
        self.native: list[tuple[bytes, int, int]] = []
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()

    def instantlink_print_prepared_jpeg_with_progress(
        self,
        buffer: ctypes.Array[ctypes.c_uint8],
        length: ctypes.c_uint32,
        model: ctypes.c_uint8,
        flip: ctypes.c_uint8,
        _option: ctypes.c_uint8,
        callback: Callable[[int, int], None],
    ) -> int:
        _ = _option
        expected = ctypes.string_at(buffer, length.value)
        self.entered.set()
        assert self.release.wait(2)
        gc.collect()
        assert ctypes.string_at(buffer, length.value) == expected
        callback(1, 2)
        callback(2, 2)
        self.native.append((expected, model.value, flip.value))
        return self.result


def backend(
    monkeypatch: pytest.MonkeyPatch, library: LegacyLibrary, model: PrinterModel
) -> InstantLinkBackend:
    result = InstantLinkBackend()
    monkeypatch.setattr(result, "_library", lambda: library)
    monkeypatch.setattr(result, "_ensure_connected_blocking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(result, "_device_model_blocking", lambda: model)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prepared_model", "detected", "override", "expected_code", "expected_flip"),
    [
        (PrinterModel.MINI, PrinterModel.MINI_LINK3, PrinterModel.MINI, 1, 1),
        (PrinterModel.MINI_LINK3, PrinterModel.MINI, PrinterModel.MINI_LINK3, 0, 0),
    ],
)
async def test_equal_dimension_model_mismatch_rebuilds_for_actual_native_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    prepared_model: PrinterModel,
    detected: PrinterModel,
    override: PrinterModel,
    expected_code: int,
    expected_flip: int,
) -> None:
    path = source(tmp_path)
    cached = prepare_for_instantlink_backend(path, prepared_model, apply_model_flip=True)
    library = PreparedLibrary()
    printer = backend(monkeypatch, library, detected)
    await printer.print_file("INSTAX-TEST", path, model_override=override, prepared_image=cached)
    expected = prepare_for_instantlink_backend(path, detected, apply_model_flip=True)
    assert library.native == [(expected.data, expected_code, expected_flip)]
    assert not library.legacy


@pytest.mark.asyncio
async def test_native_jpeg_rejection_never_retries_legacy_or_consumes_second_print(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = source(tmp_path)
    prepared = prepare_for_instantlink_backend(path, PrinterModel.MINI)
    library = PreparedLibrary(result=-6)
    printer = backend(monkeypatch, library, PrinterModel.MINI)
    with pytest.raises(ImagePipelineError):
        await printer.print_file("INSTAX-TEST", path, prepared_image=prepared)
    assert len(library.native) == 1
    assert library.native[0][0] == prepared.data
    assert not library.legacy


@pytest.mark.asyncio
async def test_old_library_rebuilds_flipped_bytes_before_legacy_core_applies_flip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = source(tmp_path)
    flipped = prepare_for_instantlink_backend(path, PrinterModel.MINI_LINK3, apply_model_flip=True)
    logical = prepare_for_instantlink_backend(path, PrinterModel.MINI_LINK3)
    library = LegacyLibrary()
    printer = backend(monkeypatch, library, PrinterModel.MINI_LINK3)
    await printer.print_file("INSTAX-TEST", path, prepared_image=flipped)
    assert library.legacy == [logical.data]
    assert all(not path.exists() for path in library.paths)
    with (
        Image.open(BytesIO(library.legacy[0])) as legacy,
        Image.open(BytesIO(flipped.data)) as direct,
    ):
        difference = ImageChops.difference(
            ImageOps.flip(legacy.convert("RGB")), direct.convert("RGB")
        )
        assert max(high for _low, high in difference.getextrema()) <= 4


def test_lcd_preview_unflips_transport_jpeg_without_changing_transport_bytes(
    tmp_path: Path,
) -> None:
    path = source(tmp_path)
    logical = prepare_for_instantlink_backend(path, PrinterModel.MINI_LINK3)
    transport = prepare_for_instantlink_backend(
        path, PrinterModel.MINI_LINK3, apply_model_flip=True
    )
    original_bytes = transport.data
    difference = ImageChops.difference(
        create_preview_from_prepared(logical), create_preview_from_prepared(transport)
    )
    assert max(high for _low, high in difference.getextrema()) <= 4
    assert transport.data == original_bytes
    assert transport.transport_flip_applied


@pytest.mark.asyncio
async def test_cancelled_native_call_retains_buffer_callback_and_serialization_until_return(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = source(tmp_path)
    prepared = prepare_for_instantlink_backend(path, PrinterModel.SQUARE)
    library = PreparedLibrary()
    library.release.clear()
    printer = backend(monkeypatch, library, PrinterModel.SQUARE)
    progress: list[PrintProgress] = []
    next_started = threading.Event()
    first = asyncio.create_task(
        printer.print_file("INSTAX-TEST", path, prepared_image=prepared, progress=progress.append)
    )
    second: asyncio.Task[None] | None = None
    try:
        assert await asyncio.to_thread(library.entered.wait, 1)
        first.cancel()
        second = asyncio.create_task(
            printer._run_blocking_serialized("next", lambda: next_started.set())
        )
        first.cancel()
        await asyncio.sleep(0)
        gc.collect()
        assert not first.done()
        assert printer._lock.locked()
        assert not next_started.is_set()
        library.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 1)
        await asyncio.wait_for(second, 1)
        assert library.native == [(prepared.data, 2, 0)]
        assert any(item.percent == 100 for item in progress)
        assert not library.legacy
    finally:
        library.release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
