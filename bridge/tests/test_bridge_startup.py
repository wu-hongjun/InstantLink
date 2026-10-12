from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_ui_controller import (
    _FakeDisplay,
    _FakePairer,
    _FakeStatusProvider,
    _unused_wifi_mode_setter,
)

from instantlink_bridge import app
from instantlink_bridge.camera import ftp
from instantlink_bridge.camera.ftp import FtpReceiveService, ReceivedImage
from instantlink_bridge.config import BridgeConfig, FtpConfig, SyncConfig, SyncDestination
from instantlink_bridge.sync import outbox, server
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiAction, UiMode, UiSnapshot
from instantlink_bridge.ui.settings import SettingsPage


class Runtime:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, upload: bool = False) -> None:
        self.stop = asyncio.Event()
        self.ready = asyncio.Event()
        self.ui_gate = asyncio.Event()
        self.ui_gate.set()
        self.bluetooth_started = asyncio.Event()
        self.bluetooth_release = asyncio.Event()
        self.sync_started = asyncio.Event()
        self.dispatched = asyncio.Event()
        self.heartbeat = asyncio.Event()
        self.events: list[str] = []
        self.ui: Any = None
        self.queue: asyncio.Queue[ReceivedImage] | None = None
        self.switch_to_sync = False
        self.fail_ui = False
        self.fail_bluetooth = False
        runtime = self

        class Ui:
            def __init__(self, config: BridgeConfig, **kwargs: object) -> None:
                self.config = config
                self.kwargs = kwargs
                runtime.ui = self

            @property
            def live_snapshot(self) -> UiSnapshot:
                return UiSnapshot(
                    mode=UiMode.READY,
                    ftp_host="192.168.8.1",
                    sync_destination=self.config.sync.destination.value,
                )

            @property
            def snapshot(self) -> UiSnapshot:
                return self.live_snapshot

            def inject_action(self, _action: object) -> bool:
                return True

            async def start(self) -> None:
                runtime.events.append("ui-start")
                await runtime.ui_gate.wait()
                if runtime.fail_ui:
                    raise RuntimeError("UI failed")
                if runtime.switch_to_sync:
                    self.config = replace(
                        self.config, sync=SyncConfig(destination=SyncDestination.IPHONE)
                    )
                    self.kwargs["sync_config_applied_callback"](self.config.sync)

            async def stop(self) -> None:
                runtime.events.append("ui-stop")

            async def sync_service_state_changed(self, listening: bool) -> None:
                runtime.events.append(f"sync-state:{listening}")

        class Ftp:
            def __init__(
                self,
                _config: object,
                queue: asyncio.Queue[ReceivedImage],
                loop: asyncio.AbstractEventLoop,
                **_kwargs: object,
            ) -> None:
                self.queue = queue
                runtime.queue = queue
                self.loop = loop

            def start(self) -> None:
                runtime.events.append("ftp-start")
                if upload:
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait, ReceivedImage(Path("photo.jpg"), "camera")
                    )

            def begin_stopping(self) -> None:
                runtime.events.append("ftp-stopping")

            def stop(self) -> None:
                runtime.events.append("ftp-stop")

            def raise_if_failed(self) -> None:
                return

            def release_received_image(self, path: Path) -> bool:
                runtime.events.append(f"release:{path.name}")
                return True

        class Cpu:
            async def start(self) -> None:
                runtime.events.append("cpu-start")

            async def close(self) -> None:
                runtime.events.append("cpu-close")

        class Power:
            async def run(self, stop: asyncio.Event) -> None:
                await stop.wait()

            async def record_activity(self) -> None:
                return

        class Notifier:
            def ready(self) -> None:
                runtime.events.append("ready")
                runtime.ready.set()

            def stopping(self) -> None:
                runtime.events.append("stopping")

        class Agent:
            async def stop(self) -> None:
                runtime.events.append("agent-stop")

        class Outbox:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                assert runtime.ready.is_set(), "sync construction must follow core readiness"
                runtime.events.append("sync-built")

            def depth(self) -> int:
                return 0

        class Sync:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                return

            async def start(self) -> None:
                runtime.events.append("sync-start")
                runtime.sync_started.set()

            async def stop(self) -> None:
                runtime.events.append("sync-stop")

        async def start_bluetooth() -> Agent:
            runtime.bluetooth_started.set()
            try:
                await runtime.bluetooth_release.wait()
            except asyncio.CancelledError:
                runtime.events.append("agent-cancel")
                raise
            if runtime.fail_bluetooth:
                raise RuntimeError("agent failed")
            runtime.events.append("agent-ready")
            return Agent()

        async def dispatch(*_args: object, **_kwargs: object) -> None:
            runtime.events.append("dispatch")
            runtime.dispatched.set()

        async def heartbeat(stop: asyncio.Event, _notifier: object) -> None:
            runtime.heartbeat.set()
            await stop.wait()

        async def close() -> None:
            return

        monkeypatch.setattr(
            app, "load_config", lambda _: BridgeConfig(ftp=FtpConfig(password="secure"))
        )
        monkeypatch.setattr(
            app, "_install_signal_handlers", lambda stop: setattr(runtime, "stop", stop)
        )
        monkeypatch.setattr(app, "BridgeUi", Ui)
        monkeypatch.setattr(ftp, "FtpReceiveService", Ftp)
        monkeypatch.setattr(app, "CpuPerformanceController", Cpu)
        monkeypatch.setattr(app, "build_power_monitor", lambda *_args, **_kwargs: Power())
        monkeypatch.setattr(app, "WatchdogNotifier", Notifier)
        monkeypatch.setattr(app, "start_bluez_agent_if_needed", start_bluetooth)
        monkeypatch.setattr(app, "dispatch_received_image", dispatch)
        monkeypatch.setattr(app, "run_watchdog_heartbeat", heartbeat)
        monkeypatch.setattr(app, "close_default_instantlink_backend", close)
        monkeypatch.setattr(app, "close_default_ble_session_manager", close)
        monkeypatch.setattr(app, "close_default_image_preparation_worker", close)
        monkeypatch.setattr(outbox, "SyncOutbox", Outbox)
        monkeypatch.setattr(server, "SyncService", Sync)
        monkeypatch.setattr(app, "read_device_id", lambda: "IB-TEST")


@pytest.mark.asyncio
async def test_ui_ftp_and_watchdog_ready_while_agent_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch, upload=True)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(runtime.ready.wait(), 1)
        await asyncio.wait_for(runtime.heartbeat.wait(), 1)
        assert "ui-start" in runtime.events and "ftp-start" in runtime.events
        assert not runtime.ui.kwargs["bluetooth_ready_event"].is_set()
        assert not runtime.dispatched.is_set()
        runtime.bluetooth_release.set()
        await asyncio.wait_for(runtime.dispatched.wait(), 1)
        assert runtime.events.index("agent-ready") < runtime.events.index("dispatch")
    finally:
        runtime.stop.set()
        await asyncio.wait_for(task, 2)
    assert "agent-stop" in runtime.events
    assert "ui-stop" in runtime.events and "ftp-stop" in runtime.events


@pytest.mark.asyncio
async def test_core_ready_requires_ui_and_sync_honors_midboot_destination_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch)
    runtime.ui_gate.clear()
    runtime.switch_to_sync = True
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(runtime.bluetooth_started.wait(), 1)
        await asyncio.sleep(0)
        assert not runtime.ready.is_set()
        assert "sync-built" not in runtime.events
        runtime.ui_gate.set()
        await asyncio.wait_for(runtime.ready.wait(), 1)
        await asyncio.wait_for(runtime.sync_started.wait(), 1)
        assert runtime.events.index("ready") < runtime.events.index("sync-built")
        assert "sync-state:False" not in runtime.events
    finally:
        runtime.stop.set()
        await asyncio.wait_for(task, 2)
    assert "agent-cancel" in runtime.events


@pytest.mark.asyncio
async def test_agent_failure_remains_fatal_after_core_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch)
    runtime.fail_bluetooth = True
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    await asyncio.wait_for(runtime.ready.wait(), 1)
    runtime.bluetooth_release.set()
    with pytest.raises(RuntimeError, match="agent failed"):
        await asyncio.wait_for(task, 2)
    assert "stopping" in runtime.events
    assert "ftp-stop" in runtime.events


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_agent_even_when_photo_is_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(monkeypatch, upload=True)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    await asyncio.wait_for(runtime.ready.wait(), 1)
    runtime.stop.set()
    await asyncio.wait_for(task, 1)
    assert "agent-cancel" in runtime.events
    assert not runtime.dispatched.is_set()
    assert "ftp-stop" in runtime.events and "ui-stop" in runtime.events
    assert "release:photo.jpg" in runtime.events


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_photo_ownership_is_released_after_each_processing_outcome(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    runtime = Runtime(monkeypatch, upload=True)
    runtime.bluetooth_release.set()
    job_started = asyncio.Event()

    async def process(*_args: object, **_kwargs: object) -> None:
        job_started.set()
        if outcome == "failure":
            raise RuntimeError("injected photo failure")
        if outcome == "cancel":
            try:
                await asyncio.Event().wait()
            finally:
                runtime.events.append("job-cancel")

    monkeypatch.setattr(app, "dispatch_received_image", process)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    await asyncio.wait_for(job_started.wait(), 1)
    await asyncio.sleep(0)
    runtime.stop.set()
    await asyncio.wait_for(task, 2)
    assert runtime.events.count("release:photo.jpg") == 1
    if outcome == "cancel":
        assert runtime.events.index("job-cancel") < runtime.events.index("release:photo.jpg")


@pytest.mark.asyncio
async def test_failed_ui_does_not_notify_core_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = Runtime(monkeypatch)
    runtime.fail_ui = True
    with pytest.raises(RuntimeError, match="UI failed"):
        await app.run_ftp_receive_slice(Path("config.toml"))
    assert not runtime.ready.is_set()
    assert "agent-cancel" in runtime.events
    assert "ftp-stop" in runtime.events


@pytest.mark.asyncio
async def test_real_ui_start_does_not_wait_for_network_or_printer_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready, bluetooth = asyncio.Event(), asyncio.Event()
    network_started, library_started, release_network, release_library = (
        asyncio.Event() for _ in range(4)
    )
    order: list[str] = []
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([]),
        status_provider=_FakeStatusProvider(),
        wifi_mode_setter=_unused_wifi_mode_setter,
        ready_event=ready,
        bluetooth_ready_event=bluetooth,
    )

    async def network() -> None:
        network_started.set()
        await release_network.wait()

    async def configure() -> None:
        order.append("configure")
        library_started.set()
        await release_library.wait()

    async def initial() -> None:
        order.append("status")

    monkeypatch.setattr(ui, "_refresh_network_status", network)
    monkeypatch.setattr(ui, "_configure_printer_keepalive", configure)
    monkeypatch.setattr(ui, "_load_initial_printer_selection", initial)
    try:
        await asyncio.wait_for(ui.start(), 0.2)
        assert ui._action_task is not None
        await asyncio.wait_for(network_started.wait(), 0.2)
        assert not library_started.is_set()
        ready.set()
        await asyncio.sleep(0)
        assert not library_started.is_set()
        bluetooth.set()
        await asyncio.wait_for(library_started.wait(), 0.2)
        assert order == ["configure"]
        release_library.set()
        assert ui._initial_status_task is not None
        await ui._initial_status_task
        assert order == ["configure", "status"]
    finally:
        await ui.stop()


@pytest.mark.asyncio
async def test_pair_worker_waits_for_bluetooth_and_pair_can_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bluetooth = asyncio.Event()
    pairer = _FakePairer([])
    pair_called = asyncio.Event()

    async def pair() -> PairedPrinter:
        pair_called.set()
        raise AssertionError("pairing must wait for Bluetooth readiness")

    monkeypatch.setattr(pairer, "pair_first_available", pair)
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=pairer,
        status_provider=_FakeStatusProvider(),
        bluetooth_ready_event=bluetooth,
    )
    await asyncio.wait_for(ui._start_pairing(), 0.2)
    await asyncio.sleep(0)
    assert ui.live_snapshot.mode is UiMode.PAIRING
    assert not pair_called.is_set()
    await asyncio.wait_for(ui._handle_action(UiAction.BACK), 0.2)
    assert ui.live_snapshot.mode is UiMode.NEEDS_PAIRING
    assert ui._pairing_task is None
    await ui.stop()


@pytest.mark.asyncio
async def test_status_worker_does_not_fetch_before_bluetooth_registration() -> None:
    bluetooth = asyncio.Event()
    provider = _FakeStatusProvider()
    printer = PairedPrinter(address="AA:BB", name="INSTAX-TEST")
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([printer]),
        status_provider=provider,
        bluetooth_ready_event=bluetooth,
    )
    ui._snapshot = ui._build_snapshot(mode=UiMode.PRINTER_SEARCHING, paired_printer=printer)
    await ui._schedule_printer_status_refresh()
    await asyncio.sleep(0)
    assert provider.fetch_calls == 0
    bluetooth.set()
    await asyncio.wait_for(provider.fetch_started.wait(), 0.2)
    assert provider.fetch_calls == 1
    await ui.stop()


@pytest.mark.asyncio
async def test_pending_settings_refresh_is_nonblocking_and_does_not_reopen_departed_page() -> None:
    bluetooth = asyncio.Event()
    pairer = _FakePairer([])
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=pairer,
        status_provider=_FakeStatusProvider(),
        bluetooth_ready_event=bluetooth,
    )
    ui._show_settings(page=SettingsPage.SYSTEM)
    await asyncio.wait_for(ui._refresh_status_from_settings(), 0.2)
    assert ui.live_snapshot.settings_message == "Starting Bluetooth"
    assert pairer.list_calls == 0
    ui._show_cached_home_status()
    bluetooth.set()
    assert ui._settings_status_task is not None
    await ui._settings_status_task
    assert pairer.list_calls == 0
    assert ui.live_snapshot.mode is UiMode.NEEDS_PAIRING
    await ui.stop()


@pytest.mark.asyncio
async def test_deferred_initial_selection_preserves_settings_and_help() -> None:
    printer = PairedPrinter(address="AA:BB", name="INSTAX-TEST")
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([printer]),
        status_provider=_FakeStatusProvider(),
    )
    ui._show_settings(page=SettingsPage.SYSTEM)
    await ui._handle_action(UiAction.HELP)
    previous = ui.live_snapshot
    await ui._load_initial_printer_selection()
    assert ui.live_snapshot.mode is previous.mode
    assert ui.live_snapshot.help_dialog_body == previous.help_dialog_body
    assert ui.live_snapshot.settings_title == previous.settings_title
    assert ui.live_snapshot.paired_printer == printer
    await ui.stop()


@pytest.mark.asyncio
async def test_partial_agent_registration_is_cleaned_up_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from instantlink_bridge.ble import agent

    started, cleaned_up = asyncio.Event(), asyncio.Event()

    class Agent:
        async def start(self) -> None:
            started.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            cleaned_up.set()

    monkeypatch.setattr(agent, "BluezAgentService", Agent)
    monkeypatch.setattr(app, "instantlink_backend_enabled", lambda: True)
    task = asyncio.create_task(app.start_bluez_agent_if_needed())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned_up.is_set()


@pytest.mark.asyncio
async def test_help_opened_at_boot_returns_to_current_sync_home_after_background_readiness() -> (
    None
):
    ready, bluetooth = asyncio.Event(), asyncio.Event()
    ui = BridgeUi(
        BridgeConfig(sync=SyncConfig(destination=SyncDestination.IPHONE)),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([]),
        status_provider=_FakeStatusProvider(),
        ready_event=ready,
        bluetooth_ready_event=bluetooth,
    )
    ui._show_help_dialog(title="Sync", body="Starting services")
    assert ui.live_snapshot.mode is UiMode.HELP_DIALOG
    ready.set()
    bluetooth.set()
    await ui.sync_service_state_changed(True)
    await ui._deferred_initial_status()
    assert ui.live_snapshot.mode is UiMode.HELP_DIALOG
    ui._dismiss_help_dialog()
    assert ui.live_snapshot.mode is UiMode.READY
    assert ui.live_snapshot.sync_service_state == "listening"
    await ui.stop()


def test_help_opened_at_boot_preserves_starting_until_background_readiness() -> None:
    ui = BridgeUi(
        BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([]),
        status_provider=_FakeStatusProvider(),
    )
    ui._show_help_dialog(title="Startup", body="Starting services")
    ui._dismiss_help_dialog()
    assert ui.live_snapshot.mode is UiMode.BOOTING


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["queue-notify", "power-activity"])
@pytest.mark.parametrize("outcome", ["failure", "cancel"])
async def test_photo_ownership_cleanup_covers_post_dequeue_awaits(
    monkeypatch: pytest.MonkeyPatch, boundary: str, outcome: str
) -> None:
    runtime = Runtime(monkeypatch, upload=True)
    entered = asyncio.Event()

    async def fault(*_args: object, **_kwargs: object) -> None:
        entered.set()
        if outcome == "failure":
            raise RuntimeError("post-dequeue failure")
        await asyncio.Event().wait()

    if boundary == "queue-notify":
        monkeypatch.setattr(app, "notify_image_queue_changed", fault)
    else:

        class Power:
            async def run(self, stop: asyncio.Event) -> None:
                await stop.wait()

            record_activity = fault

        monkeypatch.setattr(app, "build_power_monitor", lambda *_args, **_kwargs: Power())
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    await asyncio.wait_for(entered.wait(), 1)
    if outcome == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    else:
        runtime.stop.set()
        await asyncio.wait_for(task, 2)
    assert runtime.events.count("release:photo.jpg") == 1
    assert not runtime.dispatched.is_set()
    assert runtime.queue is not None
    await asyncio.wait_for(runtime.queue.join(), 0.1)
    assert runtime.events.index("ftp-stopping") < runtime.events.index("ui-stop")


@pytest.mark.asyncio
async def test_ftp_admission_stops_before_slow_shared_resource_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = Runtime(monkeypatch)
    services: list[FtpReceiveService] = []

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
            return

    monkeypatch.setattr(ftp, "FtpReceiveService", SilentFtp)
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    await asyncio.wait_for(runtime.ready.wait(), 1)
    cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()

    async def slow_stop() -> None:
        cleanup_started.set()
        await cleanup_release.wait()

    runtime.ui.stop = slow_stop
    runtime.stop.set()
    await asyncio.wait_for(cleanup_started.wait(), 1)
    service = services[0]
    incoming = service.config.incoming_dir
    incoming.mkdir(parents=True)
    late = incoming / "late.hif"
    late.write_bytes(b"original")
    try:
        reply = service._ftp_preflight_reply(path=late)
        assert reply is not None and reply.startswith("451")
        service._handle_received_file(str(late), "192.168.8.10")
        service._pin_received_image(late)
        service._handoff_received_image(late, "192.168.8.10")
        await asyncio.sleep(0)
        assert service._queue.empty()
        assert not service._pending_paths
        assert late.read_bytes() == b"original"
    finally:
        cleanup_release.set()
        await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting_for", ["bluetooth", "manual-review"])
async def test_shutdown_releases_active_and_multiple_queued_sources_without_deleting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_for: str
) -> None:
    runtime = Runtime(monkeypatch)
    services: list[FtpReceiveService] = []
    photos: list[Path] = []
    dequeued, reviewing = asyncio.Event(), asyncio.Event()

    class QueuedFtp(FtpReceiveService):
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
            runtime.queue = queue

        def start(self) -> None:
            self.config.incoming_dir.mkdir(parents=True)
            for index in range(5):
                path = self.config.incoming_dir / f"photo-{index}.hif"
                path.write_bytes(b"original")
                photos.append(path)
                self._handle_received_file(str(path), "192.168.8.10")

    async def notify(*_args: object, **_kwargs: object) -> None:
        dequeued.set()

    async def manual_review(*_args: object, **_kwargs: object) -> None:
        reviewing.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ftp, "FtpReceiveService", QueuedFtp)
    monkeypatch.setattr(app, "notify_image_queue_changed", notify)
    monkeypatch.setattr(app, "dispatch_received_image", manual_review)
    if waiting_for == "manual-review":
        runtime.bluetooth_release.set()
    task = asyncio.create_task(app.run_ftp_receive_slice(Path("config.toml")))
    try:
        await asyncio.wait_for(dequeued.wait(), 1)
        if waiting_for == "manual-review":
            await asyncio.wait_for(reviewing.wait(), 1)
        assert runtime.queue is not None and runtime.queue.qsize() == 4
    finally:
        runtime.stop.set()
        await asyncio.wait_for(task, 2)
    service = services[0]
    assert not service._pending_paths
    assert runtime.queue is not None
    await asyncio.wait_for(runtime.queue.join(), 0.1)
    assert runtime.queue.empty()
    assert len(photos) == 5
    assert all(photo.read_bytes() == b"original" for photo in photos)
