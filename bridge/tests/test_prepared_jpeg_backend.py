from __future__ import annotations

import ctypes
import hashlib
from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from PIL import Image, ImageChops, ImageOps
from test_ui_controller import _FakeDisplay, _FakePairer, _unused_wifi_mode_setter

from instantlink_bridge.ble import instantlink
from instantlink_bridge.ble.instantlink import PREPARED_MODEL_CODES, InstantLinkBackend
from instantlink_bridge.ble.models import PrinterModel, spec_for
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig, PrinterConfig
from instantlink_bridge.imaging.pipeline import (
    PreparedImage,
    PrintEdit,
    _film_preview_for_model,
    create_preview_from_prepared,
    prepare_for_instantlink_backend,
)
from instantlink_bridge.printing import PrintProgress
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.jpg"
    image = Image.new("RGB", (900, 600), (35, 90, 170))
    image.paste((225, 65, 35), (0, 0, 300, 200))
    image.save(path, quality=95)
    return path


class NativeLibrary:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, int, bool, int]] = []

    def instantlink_print_prepared_jpeg_with_progress(
        self,
        buffer: object,
        length: ctypes.c_uint32,
        model: ctypes.c_uint8,
        flipped: ctypes.c_uint8,
        option: ctypes.c_uint8,
        callback: Callable[[int, int], None],
    ) -> int:
        data = ctypes.string_at(buffer, length.value)
        self.sent.append((data, model.value, bool(flipped.value), option.value))
        callback(0, length.value)
        callback(length.value, length.value)
        assert ctypes.string_at(buffer, length.value) == data
        return 0

    def instantlink_print_with_progress(self, *_args: object) -> int:
        raise AssertionError("capable libraries must send prepared bytes directly")


class LegacyLibrary:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, int, int]] = []
        self.paths: list[Path] = []

    def instantlink_print_with_progress(
        self,
        path: bytes,
        quality: ctypes.c_uint8,
        fit: ctypes.c_uint8,
        option: ctypes.c_uint8,
        callback: Callable[[int, int], None],
    ) -> int:
        actual = Path(path.decode())
        self.paths.append(actual)
        data = actual.read_bytes()
        self.sent.append((data, quality.value, fit.value))
        assert option.value == 7
        callback(len(data), len(data))
        return 0


def backend(
    monkeypatch: pytest.MonkeyPatch, library: NativeLibrary | LegacyLibrary, model: PrinterModel
) -> InstantLinkBackend:
    instance = InstantLinkBackend()
    instance._lib = cast(ctypes.CDLL, library)
    monkeypatch.setattr(instance, "_ensure_connected_blocking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(instance, "_device_model_blocking", lambda: model)
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(PrinterModel))
async def test_native_preserves_prepared_jpeg_bytes_quality_orientation_and_progress(
    monkeypatch: pytest.MonkeyPatch, source: Path, model: PrinterModel
) -> None:
    prepared = prepare_for_instantlink_backend(source, model, apply_model_flip=True)
    library = NativeLibrary()
    instance = backend(monkeypatch, library, model)
    progress: list[PrintProgress] = []

    def forbidden(*_args: object, **_kwargs: object) -> PreparedImage:
        raise AssertionError("a matching preview must never decode or encode again")

    monkeypatch.setattr(instantlink, "prepare_for_instantlink_backend", forbidden)
    monkeypatch.setattr(instantlink.tempfile, "NamedTemporaryFile", forbidden)
    await instance.print_file(
        "INSTAX-TEST", source, prepared_image=prepared, print_option=7, progress=progress.append
    )
    sent, code, flipped, option = library.sent[0]
    assert sent == prepared.data
    assert hashlib.sha256(sent).digest() == hashlib.sha256(prepared.data).digest()
    assert code == PREPARED_MODEL_CODES[model]
    assert flipped is spec_for(model).flip_vertical
    assert option == 7
    assert progress[-2].percent == 100
    assert progress[-1].title == "Finishing"
    # The encoded quality remains the caller's one preparation, with no native
    # quality argument, fit transform or second generation of JPEG loss.
    with Image.open(BytesIO(sent)) as image:
        assert image.size == (prepared.width, prepared.height)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(PrinterModel))
async def test_inline_native_preparation_uses_connected_model_and_orients_once(
    monkeypatch: pytest.MonkeyPatch, source: Path, model: PrinterModel
) -> None:
    expected = prepare_for_instantlink_backend(source, model, apply_model_flip=True)
    library = NativeLibrary()
    instance = backend(monkeypatch, library, model)
    await instance.print_file("INSTAX-TEST", source, print_option=7)
    assert library.sent == [
        (expected.data, PREPARED_MODEL_CODES[model], spec_for(model).flip_vertical, 7)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(PrinterModel))
async def test_old_library_keeps_logical_jpeg_and_legacy_quality(
    monkeypatch: pytest.MonkeyPatch, source: Path, model: PrinterModel
) -> None:
    expected = prepare_for_instantlink_backend(source, model)
    library = LegacyLibrary()
    instance = backend(monkeypatch, library, model)
    # An oriented Link3 preview from a newer artifact must be discarded and
    # rebuilt from the source, never silently double-flipped by the old API.
    prepared = prepare_for_instantlink_backend(source, model, apply_model_flip=True)
    await instance.print_file("INSTAX-TEST", source, prepared_image=prepared, print_option=7)
    assert library.sent == [(expected.data, expected.quality, instantlink.INSTANTLINK_FIT_STRETCH)]
    assert all(not path.exists() for path in library.paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["model", "orientation", "dimensions"])
async def test_native_discards_stale_prepared_metadata(
    monkeypatch: pytest.MonkeyPatch, source: Path, stale: str
) -> None:
    model = PrinterModel.MINI_LINK3
    expected = prepare_for_instantlink_backend(source, model, apply_model_flip=True)
    wrong = {
        "model": replace(expected, model=PrinterModel.MINI),
        "orientation": replace(expected, transport_flip_applied=False),
        "dimensions": replace(expected, width=800),
    }[stale]
    library = NativeLibrary()
    instance = backend(monkeypatch, library, model)
    await instance.print_file(
        "INSTAX-TEST",
        source,
        prepared_image=wrong,
        model_override=PrinterModel.MINI,
        print_option=7,
    )
    assert library.sent == [(expected.data, PREPARED_MODEL_CODES[model], True, 7)]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(PrinterModel))
async def test_native_ui_prepares_transport_jpeg_but_lcd_shows_logical_orientation(
    monkeypatch: pytest.MonkeyPatch, source: Path, model: PrinterModel
) -> None:
    library = NativeLibrary()
    instance = backend(monkeypatch, library, model)
    monkeypatch.setattr(instantlink, "_DEFAULT_BACKEND", instance)
    ui = BridgeUi(
        BridgeConfig(printer=PrinterConfig(model=model)),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([]),
        wifi_mode_setter=_unused_wifi_mode_setter,
    )
    received = ReceivedImage(source, "camera")
    preview = await ui._build_preview_image(received, PrintEdit())
    prepared = ui.take_prepared_print_image(received, PrintEdit())
    assert prepared is not None and preview is not None
    assert prepared.transport_flip_applied is spec_for(model).flip_vertical
    with Image.open(BytesIO(prepared.data)) as encoded:
        logical = encoded.convert("RGB")
        if spec_for(model).flip_vertical:
            logical = ImageOps.flip(logical)
        expected = _film_preview_for_model(logical, model, (172, 112))
    assert ImageChops.difference(preview, expected).getbbox() is None
    assert ImageChops.difference(create_preview_from_prepared(prepared), expected).getbbox() is None
    if spec_for(model).flip_vertical:
        with Image.open(BytesIO(prepared.data)) as encoded:
            wrong = _film_preview_for_model(encoded.convert("RGB"), model, (172, 112))
        assert ImageChops.difference(preview, wrong).getbbox() is not None


def test_capability_query_never_loads_native_library_on_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = InstantLinkBackend()
    monkeypatch.setattr(instantlink, "_DEFAULT_BACKEND", instance)

    def forbidden() -> ctypes.CDLL:
        raise AssertionError("capability inspection must not load or initialize native code")

    monkeypatch.setattr(instance, "_library", forbidden)
    assert not instantlink.prepared_jpeg_available()
    instance._lib = cast(ctypes.CDLL, NativeLibrary())
    assert instantlink.prepared_jpeg_available()
    instance._lib = cast(ctypes.CDLL, LegacyLibrary())
    assert not instantlink.prepared_jpeg_available()
