from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest
from test_bridge_startup import Runtime
from test_controller_concurrency import make_ui

from instantlink_bridge import app
from instantlink_bridge.camera import ftp
from instantlink_bridge.camera.ftp import FtpReceiveService, ReceivedImage
from instantlink_bridge.config import FtpConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_runtime", [False, True])
async def test_ftp_admission_closes_before_active_photo_cancellation_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cancel_runtime: bool
) -> None:
    runtime = Runtime(monkeypatch)
    runtime.switch_to_sync = True
    services: list[FtpReceiveService] = []
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SilentFtp(FtpReceiveService):
        def __init__(
            self,
            config: FtpConfig,
            queue: asyncio.Queue[ReceivedImage],
            loop: asyncio.AbstractEventLoop,
            **kwargs: object,
        ) -> None:
            super().__init__(
                replace(config, incoming_dir=tmp_path / "incoming"), queue, loop, **kwargs
            )
            services.append(self)

        def start(self) -> None:
            self.config.incoming_dir.mkdir(parents=True)

    async def held_photo(*_args: object, **_kwargs: object) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            raise

    monkeypatch.setattr(ftp, "FtpReceiveService", SilentFtp)
    monkeypatch.setattr(app, "dispatch_received_image", held_photo)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(runtime.ready.wait(), 1)
        service = services[0]
        first = service.config.incoming_dir / "first.hif"
        first.write_bytes(b"first")
        service._handle_received_file(str(first), "192.168.8.10")
        await asyncio.wait_for(entered.wait(), 1)
        queued = service.config.incoming_dir / "queued.hif"
        queued.write_bytes(b"queued")
        service._handle_received_file(str(queued), "192.168.8.10")
        await asyncio.sleep(0)
        if cancel_runtime:
            task.cancel()
        else:
            runtime.stop.set()
        await asyncio.wait_for(cleaning.wait(), 1)
        late = service.config.incoming_dir / "late.hif"
        reply = service._ftp_preflight_reply(path=late)
        assert reply is not None and reply.startswith("451")
        assert not service._reserve_upload(late, object())
        assert service._received_path_is_owned(first)
        assert service._received_path_is_owned(queued)
        assert not task.done()
        release.set()
        if cancel_runtime:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        else:
            await asyncio.wait_for(task, 2)
        assert not service._pending_paths
        assert not service._upload_owners
        await asyncio.wait_for(service._queue.join(), 0.1)
        assert first.read_bytes() == b"first"
        assert queued.read_bytes() == b"queued"
    finally:
        release.set()
        runtime.stop.set()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", ["cached_printer", "cpu", "backend", "image_worker"])
async def test_shutdown_error_finishes_every_later_resource_and_stays_observable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failing: str
) -> None:
    runtime = Runtime(monkeypatch)
    started, release = asyncio.Event(), asyncio.Event()
    real_ui = make_ui()

    async def fail() -> None:
        started.set()
        await release.wait()
        raise OSError(f"{failing} close failed")

    async def close_backend() -> None:
        runtime.events.append("backend-close")
        if failing == "backend":
            await fail()

    async def close_ble() -> None:
        runtime.events.append("ble-close")

    async def close_worker() -> None:
        runtime.events.append("image-worker-close")
        if failing == "image_worker":
            await fail()

    class Cpu:
        async def start(self) -> None:
            runtime.events.append("cpu-start")

        async def close(self) -> None:
            runtime.events.append("cpu-close")
            if failing == "cpu":
                await fail()

    monkeypatch.setattr(app, "CpuPerformanceController", Cpu)
    monkeypatch.setattr(app, "close_default_instantlink_backend", close_backend)
    monkeypatch.setattr(app, "close_default_ble_session_manager", close_ble)
    monkeypatch.setattr(app, "close_default_image_preparation_worker", close_worker)
    if failing == "cached_printer":
        # Exercise the actual UI close path and the cached Printer disconnect
        # boundary, including its input/status/display finally cleanup.
        monkeypatch.setattr(real_ui._status_provider, "close_cached_session", fail)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(runtime.ready.wait(), 1)
        if failing == "cached_printer":
            runtime.ui.stop = real_ui.stop
        runtime.stop.set()
        await asyncio.wait_for(started.wait(), 2)
        assert not task.done(), "owned resource cleanup must finish before runtime returns"
        release.set()
        with pytest.raises(OSError, match=f"{failing} close failed"):
            await asyncio.wait_for(task, 2)
        assert "agent-cancel" in runtime.events
        assert "cpu-close" in runtime.events
        assert "backend-close" in runtime.events
        assert "ble-close" in runtime.events
        assert "image-worker-close" in runtime.events
        assert "ftp-stop" in runtime.events
        assert runtime.events.index("ble-close") < runtime.events.index("image-worker-close")
        assert runtime.events.index("image-worker-close") < runtime.events.index("ftp-stop")
        assert "bridge.shutdown_resource_failed" in caplog.text
    finally:
        release.set()
        runtime.stop.set()
        with suppress(OSError):
            await task
