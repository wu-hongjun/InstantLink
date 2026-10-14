from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from PIL import Image
from test_app import FakePairer, FakePrintUi
from test_prepared_jpeg_backend import NativeLibrary, backend
from test_preview_review import _ui
from test_ui_controller import _FakeDisplay

from instantlink_bridge import app
from instantlink_bridge.ble import instantlink
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig, CorrectionConfig
from instantlink_bridge.imaging import worker
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    PreparedImage,
    PrintEdit,
    prepare_for_instantlink_backend,
)
from instantlink_bridge.imaging.postprocess import (
    AdjustmentProfile,
    CorrectionProfile,
    correction_profile,
)
from instantlink_bridge.imaging.presets import resolve_preset
from instantlink_bridge.imaging.worker import (
    ImagePreparationWorker,
    close_default_image_preparation_worker,
)
from instantlink_bridge.ui.models import PairedPrinter


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_model", [PrinterModel.MINI, PrinterModel.SQUARE])
async def test_sender_and_model_fallback_use_the_accepted_preview_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, actual_model: PrinterModel
) -> None:
    monkeypatch.setattr(worker, "_default_worker", ImagePreparationWorker())
    path = tmp_path / "photo.jpg"
    image = Image.new("RGB", (900, 600), (40, 120, 180))
    image.paste((250, 40, 10), (0, 0, 200, 240))
    image.save(path, quality=95)
    ui = _ui(_FakeDisplay())
    dequeued = ui.config
    accepted = replace(
        dequeued,
        printer=replace(
            dequeued.printer,
            quality=90,
            fit=FitMode.CONTAIN,
            model=PrinterModel.MINI,
            print_option=7,
        ),
        correction=CorrectionConfig(saturation=-40),
    )
    ui._config = accepted
    ui._snapshot = replace(ui._snapshot, printer_model=PrinterModel.MINI)
    library = NativeLibrary()
    native = backend(monkeypatch, library, actual_model)
    monkeypatch.setattr(instantlink, "_DEFAULT_BACKEND", native)
    monkeypatch.setattr(app, "instantlink_backend_enabled", lambda: True)
    options: list[int] = []

    async def send(_address: str, source: Path, **kwargs: object) -> None:
        options.append(cast(int, kwargs["print_option"]))
        await native.print_file(
            cast(str, kwargs["name"]),
            source,
            fit=cast(FitMode, kwargs["fit"]),
            quality=cast(int, kwargs["quality"]),
            edit=cast(PrintEdit | None, kwargs["edit"]),
            print_option=cast(int, kwargs["print_option"]),
            model_override=cast(PrinterModel | None, kwargs["model"]),
            adjustments=cast(AdjustmentProfile | None, kwargs["adjustments"]),
            correction=cast(CorrectionProfile | None, kwargs["correction"]),
            prepared_image=cast(PreparedImage | None, kwargs["prepared_image"]),
        )

    monkeypatch.setattr(app, "print_file_to_printer_instantlink", send)

    class PreviewUi(FakePrintUi):
        @property
        def config(self) -> BridgeConfig:
            return ui.config

        async def await_print_confirmation(
            self, received: ReceivedImage, *, timeout_s: float | None
        ) -> PrintEdit:
            await ui._build_preview_image(received, PrintEdit())
            return PrintEdit()

        def take_prepared_print_image(
            self, received: ReceivedImage, edit: PrintEdit | None
        ) -> object:
            return ui.take_prepared_print_image(received, edit)

    try:
        await app.handle_received_image(
            ReceivedImage(path, "camera"),
            config=dequeued,
            ui=PreviewUi(should_print=True),
            pairer=FakePairer([PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-TEST")]),
        )
        expected = prepare_for_instantlink_backend(
            path,
            actual_model,
            fit=accepted.printer.fit,
            quality=accepted.printer.quality,
            edit=PrintEdit(),
            adjustments=resolve_preset(accepted.adjustments),
            correction=correction_profile(accepted.correction),
            apply_model_flip=True,
        )
        assert len(library.sent) == 1
        assert library.sent[0][0] == expected.data
        assert options == [7]
    finally:
        await close_default_image_preparation_worker()
        await ui.stop()
