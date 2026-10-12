from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from instantlink_bridge import app
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import AdjustmentsConfig, BridgeConfig
from instantlink_bridge.imaging import postprocess
from instantlink_bridge.imaging.pipeline import PrintEdit
from instantlink_bridge.imaging.postprocess import AdjustmentProfile
from instantlink_bridge.ui.models import PairedPrinter


@pytest.mark.asyncio
@pytest.mark.parametrize("instantlink", [False, True])
async def test_print_metadata_read_does_not_block_other_bridge_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, instantlink: bool
) -> None:
    started = threading.Event()
    release = threading.Event()
    sent: list[AdjustmentProfile] = []

    def read(*args: object, **kwargs: object) -> str:
        started.set()
        if not release.wait(timeout=2):
            raise AssertionError("metadata read blocked event loop")
        return "26.10.11"

    async def send(*args: object, **kwargs: object) -> None:
        profile = kwargs["adjustments"]
        assert isinstance(profile, AdjustmentProfile)
        sent.append(profile)

    monkeypatch.setattr(postprocess, "read_exif_datestamp_text", read)
    monkeypatch.setattr(app, "instantlink_backend_enabled", lambda: instantlink)
    monkeypatch.setattr(app, "print_file_to_printer_instantlink", send)
    monkeypatch.setattr(app, "print_file_to_printer_bleak", send)
    task = asyncio.create_task(
        app.send_print_to_printer(
            PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-12345678"),
            ReceivedImage(tmp_path / "photo.hif", "camera"),
            BridgeConfig(adjustments=AdjustmentsConfig(datestamp=True, saturation=20)),
            PrintEdit(),
            lambda _: None,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        # Another event-loop task can run while the filesystem/Pillow read waits.
        serviced = asyncio.Event()
        asyncio.get_running_loop().call_soon(serviced.set)
        await asyncio.wait_for(serviced.wait(), 0.2)
        assert not task.done()
        assert sent == []
        release.set()
        await asyncio.wait_for(task, 1)
        assert len(sent) == 1
        assert sent[0].datestamp_text == "26.10.11"
        assert sent[0].saturation == 1.2
    finally:
        release.set()
        await task
