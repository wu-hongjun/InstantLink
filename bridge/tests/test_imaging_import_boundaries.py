"""Keep image decoding outside startup and the async input/network loop."""

from __future__ import annotations

import asyncio
import os
import pickle
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.imaging import models, pipeline, postprocess, worker
from instantlink_bridge.ui import controller
from instantlink_bridge.ui.models import UiAction, UiMode
from instantlink_bridge.ui.settings import SettingKey, SettingsPage


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", [None, "back", "lock", "photo", "stop", "cancel"])
async def test_editor_import_does_not_block_loop_or_publish_after_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: str | None
) -> None:
    from test_ui_settings_streamline import _ui

    ui = _ui(tmp_path)
    ui._show_settings(page=SettingsPage.ADJUSTMENTS)
    key = SettingKey.ADJUST_SATURATION
    index = ui._visible_keys_for_page(SettingsPage.ADJUSTMENTS).index(key)
    ui._snapshot = replace(ui.snapshot, selected_index=index)
    ui._settings_indices[SettingsPage.ADJUSTMENTS] = index
    entered, release = threading.Event(), threading.Event()

    def load() -> None:
        assert threading.current_thread() is not threading.main_thread()
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(controller, "_load_adjustment_renderer", load)
    activation = asyncio.create_task(ui._handle_action(UiAction.SELECT))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        # The event loop stays responsive. Direct handler calls below simulate state
        # changes; the real serial input queue consumes its next action after SELECT.
        assert ui.snapshot.mode is UiMode.SETTINGS
        if interrupt == "back":
            await ui._handle_action(UiAction.BACK)
        elif interrupt == "lock":
            ui._lock_screen()
        elif interrupt == "photo":
            ui._snapshot = replace(ui.snapshot, mode=UiMode.IMAGE_RECEIVED)
        elif interrupt == "stop":
            ui._stopping = True
        elif interrupt == "cancel":
            activation.cancel()
        release.set()
        if interrupt == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await activation
        else:
            await activation
        if interrupt is None:
            assert ui.snapshot.mode is UiMode.ADJUSTMENT_EDIT
            await ui._handle_action(UiAction.BACK)
            assert ui.snapshot.mode is UiMode.SETTINGS
            assert ui._settings_page is SettingsPage.ADJUSTMENTS
            assert ui.snapshot.selected_index == index
        else:
            assert ui.snapshot.mode is not UiMode.ADJUSTMENT_EDIT
    finally:
        release.set()
        await asyncio.gather(activation, return_exceptions=True)


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("instantlink_bridge.config", ["PIL", "instantlink_bridge.imaging.pipeline"]),
        ("instantlink_bridge.manager.config_payload", ["PIL"]),
        (
            "instantlink_bridge.app",
            ["instantlink_bridge.imaging.pipeline", "instantlink_bridge.imaging.postprocess"],
        ),
    ],
)
def test_startup_does_not_import_image_preparation(module: str, forbidden: list[str]) -> None:
    script = (
        "import importlib, sys; "
        f"importlib.import_module({module!r}); "
        f"assert not set({forbidden!r}) & sys.modules.keys(), "
        f"set({forbidden!r}) & sys.modules.keys()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "FitMode",
        "PrintEdit",
        "PreparedImage",
        "WorkingImageCache",
        "ImagePipelineError",
        "ImageTooLargeError",
        "UnsupportedImageError",
        "source_identity",
        "parse_fit_mode",
    ],
)
def test_pipeline_keeps_original_contract_aliases(name: str) -> None:
    assert getattr(pipeline, name) is getattr(models, name)


@pytest.mark.parametrize("name", ["AdjustmentProfile", "CorrectionProfile", "correction_profile"])
def test_postprocess_keeps_original_contract_aliases(name: str) -> None:
    assert getattr(postprocess, name) is getattr(models, name)


def test_image_contracts_cross_worker_pickle_boundary() -> None:
    prepared = models.PreparedImage(
        data=b"jpeg bytes",
        model=PrinterModel.MINI_LINK3,
        width=600,
        height=800,
        quality=100,
        fit=models.FitMode.CONTAIN,
        transport_flip_applied=True,
    )
    request = worker.ImagePreparationRequest(
        source_path=Path("photo.hif"),
        model=PrinterModel.MINI_LINK3,
        edit=models.PrintEdit(rotate_degrees=90, zoom=1.25),
        adjustments=models.AdjustmentProfile(saturation=1.1, hue=8),
        correction=models.CorrectionProfile(saturation=1.2),
        working_cache=models.WorkingImageCache(
            Path("working.bmp"), ("photo.hif", 1, 2, 3, 4, 5), PrinterModel.MINI_LINK3
        ),
        apply_model_flip=True,
    )
    assert pickle.loads(pickle.dumps(prepared)) == prepared
    assert pickle.loads(pickle.dumps(request)) == request
    error = pickle.loads(pickle.dumps(models.ImageTooLargeError(30, 20, "pixels")))
    assert (error.size, error.maximum, error.unit) == (30, 20, "pixels")
    # Already retained legacy GLOBAL references still resolve to the same types.
    assert pickle.loads(b"cinstantlink_bridge.imaging.pipeline\nPrintEdit\n.") is models.PrintEdit
    assert (
        pickle.loads(b"cinstantlink_bridge.imaging.postprocess\nAdjustmentProfile\n.")
        is models.AdjustmentProfile
    )
    assert worker.ImagePreparationTimeoutError is models.ImagePreparationTimeoutError


def test_first_preview_and_metadata_imports_run_in_worker_threads() -> None:
    script = r"""
import asyncio
import builtins
import io
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.config import DatestampFormat
from instantlink_bridge.imaging.models import FitMode, PreparedImage
from instantlink_bridge.ui import controller

original_import = builtins.__import__
imports = set()
def checked_import(name, *args, **kwargs):
    if name in {"instantlink_bridge.imaging.pipeline", "instantlink_bridge.imaging.postprocess"}:
        assert threading.current_thread() is not threading.main_thread(), name
        imports.add(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import

async def main():
    encoded = io.BytesIO()
    Image.new("RGB", (600, 800), (40, 90, 180)).save(encoded, format="JPEG")
    prepared = PreparedImage(encoded.getvalue(), PrinterModel.MINI, 600, 800, 100, FitMode.AUTO)
    preview = await asyncio.to_thread(controller.create_preview_from_prepared, prepared)
    try:
        assert preview.size[0] <= 172 and preview.size[1] <= 112
    finally:
        preview.close()
    with TemporaryDirectory() as directory:
        photo = Path(directory) / "photo.jpg"
        photo.write_bytes(encoded.getvalue())
        value = await asyncio.to_thread(
            controller.read_exif_datestamp_text, photo, "en", fmt=DatestampFormat.MODERN
        )
        assert value == ""
    assert imports == {
        "instantlink_bridge.imaging.pipeline", "instantlink_bridge.imaging.postprocess"
    }
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("key_name", ["ADJUST_SATURATION", "ADJUST_DATESTAMP", "ADJUST_WATERMARK"])
def test_cold_editor_import_finishes_off_loop_before_first_render(key_name: str) -> None:
    script = r"""
import asyncio
import sys
import threading
from dataclasses import replace
from instantlink_bridge.config import BridgeConfig
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.display import NullDisplay
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import UiAction, UiMode
from instantlink_bridge.ui.render import render_snapshot
from instantlink_bridge.ui.settings import SettingsPage, SettingKey

seen = []
class ImportObserver:
    def find_spec(self, fullname, path, target=None):
        if fullname == "instantlink_bridge.imaging.postprocess":
            assert threading.current_thread() is not threading.main_thread()
            seen.append(fullname)
        return None

class Display(NullDisplay):
    def render(self, snapshot):
        if snapshot.mode is UiMode.ADJUSTMENT_EDIT:
            assert seen == ["instantlink_bridge.imaging.postprocess"]
            image = render_snapshot(snapshot)
            image.close()

async def main():
    assert "instantlink_bridge.imaging.postprocess" not in sys.modules
    sys.meta_path.insert(0, ImportObserver())
    ui = BridgeUi(BridgeConfig(), display=Display(), input_device=NullInput())
    ui._show_settings(page=SettingsPage.ADJUSTMENTS)
    index = ui._visible_keys_for_page(SettingsPage.ADJUSTMENTS).index(SettingKey.COLD_EDITOR_KEY)
    ui._snapshot = replace(ui.snapshot, selected_index=index)
    await ui._handle_action(UiAction.SELECT)
    assert ui.snapshot.mode is UiMode.ADJUSTMENT_EDIT
    await ui._handle_action(UiAction.BACK)
    assert ui.snapshot.mode is UiMode.SETTINGS
    assert ui.snapshot.selected_index == index
asyncio.run(main())
"""
    script = script.replace("SettingKey.COLD_EDITOR_KEY", f"SettingKey.{key_name}")
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 0, result.stderr
