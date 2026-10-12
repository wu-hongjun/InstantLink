from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from instantlink_bridge.ble import instantlink
from instantlink_bridge.ble.instantlink import InstantLinkBackend
from instantlink_bridge.ble.models import PrinterModel, spec_for
from instantlink_bridge.imaging.pipeline import FitMode, PreparedImage


def prepared(model: PrinterModel) -> PreparedImage:
    spec = spec_for(model)
    return PreparedImage(
        data=model.value.encode(),
        model=model,
        width=spec.width,
        height=spec.height,
        quality=80,
        fit=FitMode.AUTO,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hint", "override", "detected", "expected_preparations"),
    [
        (PrinterModel.SQUARE, None, PrinterModel.SQUARE, [PrinterModel.SQUARE]),
        (PrinterModel.MINI, None, PrinterModel.SQUARE, [PrinterModel.MINI, PrinterModel.SQUARE]),
        (PrinterModel.MINI, PrinterModel.SQUARE, PrinterModel.SQUARE, [PrinterModel.SQUARE]),
    ],
)
async def test_immediate_preparation_overlaps_connect_and_validates_actual_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hint: PrinterModel,
    override: PrinterModel | None,
    detected: PrinterModel,
    expected_preparations: list[PrinterModel],
) -> None:
    started, connecting = threading.Event(), threading.Event()
    models: list[PrinterModel] = []
    sent: list[bytes] = []
    backend = InstantLinkBackend()

    def prepare(_path: Path, model: PrinterModel, **_kwargs: object) -> PreparedImage:
        models.append(model)
        started.set()
        assert connecting.wait(1), "preparation must overlap connection"
        return prepared(model)

    def connect(_name: str, *, scan_duration_s: int) -> None:
        _ = scan_duration_s
        assert started.wait(1), "known model must start preparation before connection finishes"
        connecting.set()

    class Library:
        def instantlink_print_with_progress(self, path: bytes, *_args: object) -> int:
            sent.append(Path(path.decode()).read_bytes())
            return 0

    monkeypatch.setattr(instantlink, "prepare_for_instantlink_backend", prepare)
    monkeypatch.setattr(backend, "_ensure_connected_blocking", connect)
    monkeypatch.setattr(backend, "_device_model_blocking", lambda: detected)
    monkeypatch.setattr(backend, "_library", Library)
    await asyncio.wait_for(
        backend.print_file(
            "INSTAX-TEST",
            tmp_path / "source.hif",
            model_override=override,
            preparation_model_hint=hint,
        ),
        2,
    )
    assert models == expected_preparations
    assert sent == [detected.value.encode()]


@pytest.mark.asyncio
async def test_preview_reuse_skips_speculative_preparation_even_with_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = InstantLinkBackend()
    sent: list[bytes] = []

    def no_prepare(*_args: object, **_kwargs: object) -> PreparedImage:
        raise AssertionError("prepared preview must not be rebuilt")

    class Library:
        def instantlink_print_with_progress(self, path: bytes, *_args: object) -> int:
            sent.append(Path(path.decode()).read_bytes())
            return 0

    monkeypatch.setattr(instantlink, "prepare_for_instantlink_backend", no_prepare)
    monkeypatch.setattr(backend, "_ensure_connected_blocking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "_device_model_blocking", lambda: PrinterModel.SQUARE)
    monkeypatch.setattr(backend, "_library", Library)
    await backend.print_file(
        "INSTAX-TEST",
        tmp_path / "source.hif",
        prepared_image=prepared(PrinterModel.SQUARE),
        preparation_model_hint=PrinterModel.MINI,
    )
    assert sent == [PrinterModel.SQUARE.value.encode()]


@pytest.mark.asyncio
async def test_immediate_dispatch_passes_cached_model_as_hint_without_forcing_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from test_app import FakePairer, FakePrintUi

    from instantlink_bridge import app
    from instantlink_bridge.camera.ftp import ReceivedImage
    from instantlink_bridge.config import BridgeConfig, WorkflowConfig
    from instantlink_bridge.ui.models import PairedPrinter, UiMode, UiSnapshot

    sent: list[dict[str, object]] = []

    async def sender(*_args: object, **kwargs: object) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(app, "instantlink_backend_enabled", lambda: True)
    monkeypatch.setattr(app, "print_file_to_printer_instantlink", sender)
    printer = PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-TEST")
    ui = FakePrintUi(should_print=True)
    monkeypatch.setattr(ui, "take_prepared_print_image", lambda *_args: None, raising=False)
    await app.dispatch_received_image(
        ReceivedImage(tmp_path / "source.hif", "camera"),
        snapshot=UiSnapshot(
            mode=UiMode.READY,
            ftp_host="192.168.8.1",
            paired_printer=printer,
            printer_model=PrinterModel.SQUARE,
        ),
        config=BridgeConfig(workflow=WorkflowConfig(auto_print_delay_s=0)),
        ui=ui,
        pairer=FakePairer([printer]),
        outbox=None,
    )
    assert len(sent) == 1
    assert sent[0]["model"] is None
    assert sent[0]["preparation_model_hint"] is PrinterModel.SQUARE
    assert sent[0]["prepared_image"] is None
    assert "confirm:0" in ui.events
