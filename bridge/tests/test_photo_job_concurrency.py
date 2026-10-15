from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from test_app import FakePairer, FakePrintUi
from test_bridge_startup import Runtime

from instantlink_bridge import app
from instantlink_bridge.camera import ftp
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig
from instantlink_bridge.imaging.pipeline import PrintEdit
from instantlink_bridge.power.performance import CpuPerformanceController
from instantlink_bridge.printing import PrintProgress, PrintProgressCallback
from instantlink_bridge.sync import outbox as outbox_module
from instantlink_bridge.sync.outbox import SyncOutbox
from instantlink_bridge.ui.models import PairedPrinter


@pytest.mark.asyncio
@pytest.mark.parametrize("after_slow_notice", [False, True])
async def test_cancelled_sender_cleanup_finishes_before_idle_clock_or_terminal_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_slow_notice: bool
) -> None:
    started, cleaning, release, slow_notice = (asyncio.Event() for _ in range(4))
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)

    class Ui(FakePrintUi):
        async def print_progress(self, progress: PrintProgress) -> None:
            await super().print_progress(progress)
            if progress.title == "Still printing":
                slow_notice.set()

    async def sender(
        _printer: PairedPrinter,
        _received: ReceivedImage,
        _config: BridgeConfig,
        _edit: PrintEdit,
        _progress: PrintProgressCallback,
    ) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            raise

    async def target(printer: PairedPrinter) -> PairedPrinter:
        return printer

    monkeypatch.setattr(app, "resolve_print_target", target)
    monkeypatch.setattr(app, "PRINT_JOB_TIMEOUT_S", 0.001 if after_slow_notice else None)
    cpu = CpuPerformanceController(setter)
    cpu.set_power_saving(True)
    await cpu.start()
    ui = Ui(should_print=True)
    task = asyncio.create_task(
        app.handle_received_image(
            ReceivedImage(tmp_path / "photo.jpg", "camera"),
            config=BridgeConfig(),
            ui=ui,
            pairer=FakePairer([PairedPrinter("AA:BB:CC:DD:EE:FF", "INSTAX-12345678")]),
            printer_sender=sender,
            cpu_performance=cpu,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        if after_slow_notice:
            await asyncio.wait_for(slow_notice.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        assert not task.done()
        assert modes[-1] == "performance"
        task.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert not task.done()
        assert modes[-1] == "performance"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert modes == ["powersave", "performance", "powersave"]
        assert not any(e.startswith(("complete:", "failed:")) for e in ui.events)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await cpu.close()


@pytest.mark.asyncio
async def test_spool_cancellation_waits_for_filesystem_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    hash_file = outbox_module._hash_file

    def gated_hash(path: Path) -> str:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        return hash_file(path)

    source = tmp_path / "photo.jpg"
    source.write_bytes(b"original camera photo")
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=10)
    monkeypatch.setattr(outbox_module, "_hash_file", gated_hash)
    task = asyncio.create_task(
        app.spool_image_to_sync_outbox(
            ReceivedImage(source, "camera"), ui=FakePrintUi(should_print=False), outbox=outbox
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert not task.done()
        assert outbox.depth() == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert outbox.depth() == 1
        assert SyncOutbox(tmp_path / "outbox", budget_mb=10).depth() == 1
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_service_stop_reaches_active_photo_and_joins_it_before_closing_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch, upload=True)
    started, cleaning, release = (asyncio.Event() for _ in range(3))

    async def dispatch(*_args: object, **_kwargs: object) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            runtime.events.append("photo-cleaned")
            raise

    monkeypatch.setattr(app, "dispatch_received_image", dispatch)
    runtime.bluetooth_release.set()
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(started.wait(), 1)
        runtime.stop.set()
        await asyncio.wait_for(cleaning.wait(), 1)
        assert not task.done()
        assert "ui-stop" not in runtime.events
        task.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert "ui-stop" not in runtime.events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert runtime.events.index("photo-cleaned") < runtime.events.index("ui-stop")
        assert "ftp-stop" in runtime.events
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cpu_helper_ftp_and_bluetooth_start_together_but_ui_waits_for_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch)
    cpu_started, release = asyncio.Event(), asyncio.Event()

    class Cpu:
        async def start(self) -> None:
            cpu_started.set()
            await release.wait()
            runtime.events.append("cpu-applied")

        async def close(self) -> None:
            runtime.events.append("cpu-close")

    monkeypatch.setattr(app, "CpuPerformanceController", Cpu)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(cpu_started.wait(), 1)
        await asyncio.wait_for(runtime.bluetooth_started.wait(), 1)
        for _ in range(100):
            if "ftp-start" in runtime.events:
                break
            await asyncio.sleep(0.001)
        assert "ftp-start" in runtime.events
        assert "ui-start" not in runtime.events
        assert not runtime.ready.is_set()
        release.set()
        await asyncio.wait_for(runtime.ready.wait(), 1)
        assert runtime.events.index("cpu-applied") < runtime.events.index("ui-start")
        runtime.stop.set()
        await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_startup_joins_ftp_binding_thread_and_stops_its_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch)
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    base = ftp.FtpReceiveService

    class GatedFtp(base):
        def start(self) -> None:
            super().start()
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2)

    monkeypatch.setattr(ftp, "FtpReceiveService", GatedFtp)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert not task.done()
        assert "ftp-stop" not in runtime.events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert runtime.events.count("ftp-stop") == 1
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
