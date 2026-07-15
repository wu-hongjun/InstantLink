from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from instantlink_bridge import app, system_info
from instantlink_bridge.ble.client import DiscoveredPrinter
from instantlink_bridge.ble.instax import NoFilmError
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig, SyncConfig, SyncDestination
from instantlink_bridge.imaging.pipeline import (
    ImagePipelineError,
    ImageTooLargeError,
    PrintEdit,
    UnsupportedImageError,
)
from instantlink_bridge.printing import PrintProgress, PrintProgressCallback, PrintStage
from instantlink_bridge.sync.outbox import SyncOutbox
from instantlink_bridge.system_info import SystemInfo
from instantlink_bridge.ui.models import PairedPrinter, UiMode, UiSnapshot


@pytest.mark.asyncio
async def test_handle_received_image_prints_after_auto_confirm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = FakePrintUi(should_print=True)
    pairer = FakePairer([PairedPrinter(address="88:B4:36:51:CC:E2", name="INSTAX-1N034655")])
    sent: list[PairedPrinter] = []

    async def resolve_target(_selected: PairedPrinter) -> PairedPrinter:
        return PairedPrinter(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")

    async def sender(
        printer: PairedPrinter,
        _received: ReceivedImage,
        _config: BridgeConfig,
        edit: PrintEdit,
        progress: PrintProgressCallback,
    ) -> None:
        sent.append(printer)
        assert edit == PrintEdit()
        progress(PrintProgress(stage=PrintStage.SENDING, title="Sending 50%", percent=50))

    monkeypatch.setattr(app, "resolve_print_target", resolve_target)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=pairer,
        printer_sender=sender,
    )

    assert sent == [PairedPrinter(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")]
    assert ui.events == [
        "received:image.jpg",
        f"confirm:{app.AUTO_PRINT_DELAY_S}",
        "printing:image.jpg",
        "progress:selecting_printer:Checking printer:Looking up printer:",
        "progress:selecting_printer:Finding printer:INSTAX-1N034655:",
        "progress:sending:Sending 50%::50",
        "complete:image.jpg",
    ]


@pytest.mark.asyncio
async def test_handle_received_image_cancel_skips_sender(tmp_path: Path) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = FakePrintUi(should_print=False)
    pairer = FakePairer([PairedPrinter(address="AA:BB:CC:DD:EE:FF", name="INSTAX-12345678")])
    sent: list[PairedPrinter] = []

    async def sender(
        printer: PairedPrinter,
        _received: ReceivedImage,
        _config: BridgeConfig,
        _edit: PrintEdit,
        _progress: PrintProgressCallback,
    ) -> None:
        sent.append(printer)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=pairer,
        printer_sender=sender,
    )

    assert sent == []
    assert ui.events == ["received:image.jpg", f"confirm:{app.AUTO_PRINT_DELAY_S}"]


@pytest.mark.asyncio
async def test_handle_received_image_can_skip_dequeue_receive_notification(tmp_path: Path) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = FakePrintUi(should_print=False)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        printer_sender=_unused_sender,
        notify_received=False,
    )

    assert ui.events == [f"confirm:{app.AUTO_PRINT_DELAY_S}"]


@pytest.mark.asyncio
async def test_handle_received_image_requires_selected_printer(tmp_path: Path) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = FakePrintUi(should_print=True)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        printer_sender=_unused_sender,
    )

    assert ui.events == [
        "received:image.jpg",
        f"confirm:{app.AUTO_PRINT_DELAY_S}",
        "printing:image.jpg",
        "progress:selecting_printer:Checking printer:Looking up printer:",
        "failed:Select printer first",
    ]


@pytest.mark.asyncio
async def test_handle_received_image_handles_preview_image_errors(tmp_path: Path) -> None:
    received = ReceivedImage(path=tmp_path / "broken.jpg", remote_ip="192.168.7.10")
    ui = FailingPreviewUi(UnsupportedImageError("bad input"))

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        printer_sender=_unused_sender,
    )

    assert ui.events == [
        "received:broken.jpg",
        f"confirm:{app.AUTO_PRINT_DELAY_S}",
        "failed:Image unsupported",
    ]


@pytest.mark.asyncio
async def test_handle_received_image_reports_slow_print_without_cancelling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = FakePrintUi(should_print=True)
    pairer = FakePairer([PairedPrinter(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")])

    async def resolve_target(selected: PairedPrinter) -> PairedPrinter:
        return selected

    async def slow_sender(
        _printer: PairedPrinter,
        _received: ReceivedImage,
        _config: BridgeConfig,
        _edit: PrintEdit,
        _progress: PrintProgressCallback,
    ) -> None:
        await asyncio.sleep(0.02)

    monkeypatch.setattr(app, "PRINT_JOB_TIMEOUT_S", 0.01)
    monkeypatch.setattr(app, "resolve_print_target", resolve_target)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=pairer,
        printer_sender=slow_sender,
    )

    assert "progress:finishing:Still printing:Waiting for printer:" in ui.events
    assert ui.events[-1] == "complete:image.jpg"


@pytest.mark.asyncio
async def test_handle_received_image_maps_printer_rejections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = FakePrintUi(should_print=True)
    pairer = FakePairer([PairedPrinter(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")])

    async def resolve_target(selected: PairedPrinter) -> PairedPrinter:
        return selected

    async def rejecting_sender(
        _printer: PairedPrinter,
        _received: ReceivedImage,
        _config: BridgeConfig,
        _edit: PrintEdit,
        _progress: PrintProgressCallback,
    ) -> None:
        raise NoFilmError("no film remaining")

    monkeypatch.setattr(app, "resolve_print_target", resolve_target)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=pairer,
        printer_sender=rejecting_sender,
    )

    assert ui.events[-1] == "failed:No film"


@pytest.mark.asyncio
async def test_handle_received_image_drains_progress_before_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = SlowProgressPrintUi(should_print=True)
    pairer = FakePairer([PairedPrinter(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")])

    async def resolve_target(selected: PairedPrinter) -> PairedPrinter:
        return selected

    async def rejecting_sender(
        _printer: PairedPrinter,
        _received: ReceivedImage,
        _config: BridgeConfig,
        _edit: PrintEdit,
        progress: PrintProgressCallback,
    ) -> None:
        progress(PrintProgress(stage=PrintStage.SENDING, title="Sending 50%", percent=50))
        raise NoFilmError("no film remaining")

    monkeypatch.setattr(app, "resolve_print_target", resolve_target)

    await app.handle_received_image(
        received,
        config=BridgeConfig(),
        ui=ui,
        pairer=pairer,
        printer_sender=rejecting_sender,
    )

    assert ui.events[-2:] == [
        "progress:sending:Sending 50%::50",
        "failed:No film",
    ]


@pytest.mark.asyncio
async def test_queue_status_hooks_are_optional_and_report_shape(tmp_path: Path) -> None:
    received = ReceivedImage(path=tmp_path / "image.jpg", remote_ip="192.168.7.10")
    ui = QueueAwarePrintUi(should_print=False)

    await app.notify_image_queue_changed(ui, depth=2, max_size=100)
    await app.notify_image_queue_overflow(ui, received, depth=100, max_size=100)
    await app.notify_image_queue_changed(object(), depth=1, max_size=100)
    await app.notify_image_queue_overflow(object(), received, depth=100, max_size=100)

    assert ui.events == [
        "queue:2/100",
        "overflow:image.jpg:100/100",
    ]


@pytest.mark.asyncio
async def test_dispatch_print_destination_runs_print_flow_without_spooling(
    tmp_path: Path,
) -> None:
    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=False)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="print"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )

    assert outbox.depth() == 0
    assert ui.events == ["received:image.jpg", "confirm:5.0"]


@pytest.mark.asyncio
async def test_dispatch_iphone_destination_spools_and_skips_print_flow(
    tmp_path: Path,
) -> None:
    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=True)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="iphone"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )

    assert outbox.depth() == 1
    assert ui.events == ["sync_outbox:1"]
    # Spooling must never mutate the received source file.
    assert received.path.read_bytes() == b"jpg"


@pytest.mark.asyncio
async def test_dispatch_both_destination_spools_before_print_flow(tmp_path: Path) -> None:
    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=False)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="both"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )

    assert outbox.depth() == 1
    assert ui.events == ["sync_outbox:1", "received:image.jpg", "confirm:5.0"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot_kwargs",
    [
        {"paired_printer": None, "mode": UiMode.NEEDS_PAIRING, "printer_status_fresh": False},
        {"mode": UiMode.PRINTER_OFFLINE, "printer_status_fresh": False},
        {"printer_status_fresh": False},
        {"film_remaining": 0},
    ],
)
async def test_dispatch_both_destination_skips_print_when_printer_unready(
    tmp_path: Path,
    snapshot_kwargs: dict[str, object],
) -> None:
    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=True)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="both", **snapshot_kwargs),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )

    # Spooled quietly, no print flow and no error screens.
    assert outbox.depth() == 1
    assert ui.events == ["sync_outbox:1"]


@pytest.mark.asyncio
async def test_dispatch_outbox_failure_does_not_break_print_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=False)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)

    def failing_add(_source: Path, *, remote_ip: str = "") -> None:
        _ = remote_ip
        raise OSError("disk full")

    monkeypatch.setattr(outbox, "add", failing_add)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="both"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )

    assert outbox.depth() == 0
    assert ui.events == ["received:image.jpg", "confirm:5.0"]


@pytest.mark.asyncio
async def test_dispatch_survives_missing_outbox(tmp_path: Path) -> None:
    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=True)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="iphone"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=None,
        printer_sender=_unused_sender,
    )

    assert ui.events == []


@pytest.mark.asyncio
async def test_dispatch_reads_destination_per_item(tmp_path: Path) -> None:
    """A runtime destination flip applies to the next dequeued item, no restart."""

    received = _write_received_image(tmp_path)
    ui = SyncAwarePrintUi(should_print=False)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)

    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="print"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )
    await app.dispatch_received_image(
        received,
        snapshot=_make_snapshot(sync_destination="iphone"),
        config=BridgeConfig(),
        ui=ui,
        pairer=FakePairer([]),
        outbox=outbox,
        printer_sender=_unused_sender,
    )

    assert outbox.depth() == 1
    assert ui.events == [
        "received:image.jpg",
        "confirm:5.0",
        "sync_outbox:1",
    ]


@pytest.mark.asyncio
async def test_sync_hooks_are_optional_and_report_shape() -> None:
    ui = SyncAwarePrintUi(should_print=False)

    await app.notify_sync_outbox_changed(ui, depth=3)
    await app.notify_sync_client_seen(ui)
    await app.notify_sync_outbox_changed(object(), depth=1)
    await app.notify_sync_client_seen(object())

    assert ui.events == ["sync_outbox:3", "sync_client_seen"]


@pytest.mark.asyncio
async def test_apply_sync_destination_change_starts_service_when_sync_enabled() -> None:
    service = FakeSyncService()

    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.IPHONE),
        service=service,
    )
    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.BOTH),
        service=service,
    )

    assert service.events == ["start", "start"]


@pytest.mark.asyncio
async def test_apply_sync_destination_change_stops_service_when_print_only() -> None:
    service = FakeSyncService()

    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.PRINT),
        service=service,
    )

    assert service.events == ["stop"]


@pytest.mark.asyncio
async def test_apply_sync_destination_change_survives_start_failure_and_no_service() -> None:
    service = FakeSyncService(fail_start=True)

    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.IPHONE),
        service=service,
    )
    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.IPHONE),
        service=None,
    )

    assert service.events == []


@pytest.mark.asyncio
async def test_stop_sync_service_guarded_swallows_stop_failure() -> None:
    service = FakeSyncService(fail_stop=True)

    await app.stop_sync_service_guarded(service, reason="shutdown")

    assert service.events == []


@pytest.mark.asyncio
async def test_resolve_print_target_derives_ios_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSTANTLINK_BRIDGE_PRINTER_BACKEND", "bleak")
    selected = PairedPrinter(address="88:B4:36:51:CC:E2", name="INSTAX-1N034655")

    async def scanner(_timeout_s: float) -> list[DiscoveredPrinter]:
        return [DiscoveredPrinter(address="88:B4:36:51:CC:E2", name="INSTAX-1N034655(ANDROID)")]

    monkeypatch.setattr(app, "scan_instax_printers", scanner)

    target = await app.resolve_print_target(selected)

    assert target == PairedPrinter(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")


@pytest.mark.asyncio
async def test_resolve_print_target_requires_visible_printer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSTANTLINK_BRIDGE_PRINTER_BACKEND", "bleak")
    selected = PairedPrinter(address="88:B4:36:51:CC:E2", name="INSTAX-1N034655")

    async def scanner(_timeout_s: float) -> list[DiscoveredPrinter]:
        return []

    async def bluez_scanner(_timeout_s: float) -> list[PairedPrinter]:
        return []

    monkeypatch.setattr(app, "scan_instax_printers", scanner)
    monkeypatch.setattr(app, "scan_bluez_instax_printers", bluez_scanner)

    with pytest.raises(app.PrintJobError, match="Printer offline"):
        await app.resolve_print_target(selected)


@pytest.mark.asyncio
async def test_resolve_print_target_uses_selected_printer_for_instantlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSTANTLINK_BRIDGE_PRINTER_BACKEND", "instantlink")
    selected = PairedPrinter(address="INSTANTLINK:1N034655", name="INSTAX-1N034655")

    assert await app.resolve_print_target(selected) == selected


def test_select_configured_printer_prefers_named_device() -> None:
    printers = [
        PairedPrinter(address="AA:BB:CC:DD:EE:01", name="INSTAX-A"),
        PairedPrinter(address="AA:BB:CC:DD:EE:02", name="INSTAX-B"),
    ]

    assert app.select_configured_printer(printers, configured_name="INSTAX-B") == printers[1]


def test_print_error_message_is_lcd_friendly() -> None:
    assert app.print_error_message(ImageTooLargeError(size=200, maximum=100)) == "Image too large"
    assert app.print_error_message(UnsupportedImageError("bad")) == "Image unsupported"
    assert app.print_error_message(ImagePipelineError("printer offline")) == "Printer offline"
    assert app.print_error_message(ImagePipelineError("printer timed out")) == "Printer timed out"
    assert app.print_error_message(ImagePipelineError("printer type unknown")) == (
        "Printer type unknown"
    )
    assert app.printer_rejection_message(NoFilmError("empty")) == "No film"


def test_main_version_prints_runtime_versions_without_starting_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(system_info, "read_system_info", _fake_system_info)

    async def fail_start(_config_path: Path) -> None:
        raise AssertionError("service should not start for --version")

    monkeypatch.setattr(app, "run_ftp_receive_slice", fail_start)

    app.main(["--version"])

    assert capsys.readouterr().out == (
        "InstantLink Bridge 9.8.7 (Python 3.11.9; BlueZ 5.82; OS Debian GNU/Linux 13 (trixie))\n"
    )


def test_main_status_prints_read_only_report_without_starting_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(system_info, "read_system_info", _fake_system_info)

    async def fail_start(_config_path: Path) -> None:
        raise AssertionError("service should not start for --status")

    monkeypatch.setattr(app, "run_ftp_receive_slice", fail_start)

    app.main(["--status"])

    assert capsys.readouterr().out == (
        "InstantLink Bridge status\n"
        "device: IB-1234ABCD\n"
        "app: 9.8.7\n"
        "python: 3.11.9\n"
        "bluez: 5.82\n"
        "os: Debian GNU/Linux 13 (trixie)\n"
    )


def test_main_starts_service_with_config_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "bridge.toml"
    started: list[Path] = []

    async def fake_start(config_path_arg: Path) -> None:
        started.append(config_path_arg)

    monkeypatch.setattr(app, "run_ftp_receive_slice", fake_start)

    app.main(["--config", str(config_path), "--log-level", "ERROR"])

    assert started == [config_path]


def _fake_system_info() -> SystemInfo:
    return SystemInfo(
        device_id="IB-1234ABCD",
        app_version="9.8.7",
        python_version="3.11.9",
        bluez_version="5.82",
        os_version="Debian GNU/Linux 13 (trixie)",
    )


async def _unused_sender(
    _printer: PairedPrinter,
    _received: ReceivedImage,
    _config: BridgeConfig,
    _edit: PrintEdit,
    _progress: PrintProgressCallback,
) -> None:
    raise AssertionError("sender should not be called")


class FakePairer:
    def __init__(self, printers: Sequence[PairedPrinter]) -> None:
        self._printers = list(printers)

    async def list_paired(self) -> list[PairedPrinter]:
        return self._printers

    async def pair_first_available(self) -> PairedPrinter:
        if not self._printers:
            raise AssertionError("no fake printer")
        return self._printers[0]

    def save_selected(self, _printer: PairedPrinter) -> None:
        return None

    async def forget_selected(self) -> None:
        return None


class FakePrintUi:
    def __init__(self, *, should_print: bool) -> None:
        self._should_print = should_print
        self.events: list[str] = []

    async def image_received(self, received: ReceivedImage) -> None:
        self.events.append(f"received:{received.path.name}")

    async def await_print_confirmation(
        self,
        received: ReceivedImage,
        *,
        timeout_s: float | None = app.AUTO_PRINT_DELAY_S,
    ) -> PrintEdit | None:
        _ = received
        self.events.append(f"confirm:{timeout_s}")
        return PrintEdit() if self._should_print else None

    async def printing_started(self, received: ReceivedImage) -> None:
        self.events.append(f"printing:{received.path.name}")

    async def print_progress(self, progress: PrintProgress) -> None:
        self.events.append(
            "progress:"
            f"{progress.stage.value}:"
            f"{progress.title}:"
            f"{progress.detail or ''}:"
            f"{'' if progress.percent is None else progress.percent}"
        )

    async def print_complete(self, received: ReceivedImage) -> None:
        self.events.append(f"complete:{received.path.name}")

    async def print_failed(self, message: str) -> None:
        self.events.append(f"failed:{message}")


class SlowProgressPrintUi(FakePrintUi):
    async def print_progress(self, progress: PrintProgress) -> None:
        await asyncio.sleep(0)
        await super().print_progress(progress)


class QueueAwarePrintUi(FakePrintUi):
    async def image_queue_changed(self, *, depth: int, max_size: int) -> None:
        self.events.append(f"queue:{depth}/{max_size}")

    async def image_queue_overflow(
        self,
        received: ReceivedImage,
        *,
        depth: int,
        max_size: int,
    ) -> None:
        self.events.append(f"overflow:{received.path.name}:{depth}/{max_size}")


class SyncAwarePrintUi(FakePrintUi):
    """FakePrintUi that also records the plan-050 sync hooks."""

    async def sync_outbox_changed(self, depth: int) -> None:
        self.events.append(f"sync_outbox:{depth}")

    async def sync_client_seen(self) -> None:
        self.events.append("sync_client_seen")


class FakeSyncService:
    """Records start/stop transitions like app.py drives SyncService."""

    def __init__(self, *, fail_start: bool = False, fail_stop: bool = False) -> None:
        self.events: list[str] = []
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    async def start(self) -> None:
        if self._fail_start:
            raise RuntimeError("bind failed")
        self.events.append("start")

    async def stop(self) -> None:
        if self._fail_stop:
            raise RuntimeError("cleanup failed")
        self.events.append("stop")


def _write_received_image(tmp_path: Path) -> ReceivedImage:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"jpg")
    return ReceivedImage(path=image_path, remote_ip="192.168.8.10")


def _make_snapshot(**kwargs: object) -> UiSnapshot:
    defaults: dict[str, object] = dict(
        mode=UiMode.READY,
        ftp_host="192.168.8.1",
        paired_printer=PairedPrinter(address="AA:BB:CC:DD:EE:FF", name="INSTAX-12345678"),
        printer_status_fresh=True,
        film_remaining=10,
        allow_print_without_film=False,
    )
    defaults.update(kwargs)
    return UiSnapshot(**defaults)  # type: ignore[arg-type]


class FailingPreviewUi(FakePrintUi):
    def __init__(self, error: Exception) -> None:
        super().__init__(should_print=True)
        self._error = error

    async def await_print_confirmation(
        self,
        received: ReceivedImage,
        *,
        timeout_s: float | None = app.AUTO_PRINT_DELAY_S,
    ) -> PrintEdit | None:
        _ = received
        self.events.append(f"confirm:{timeout_s}")
        raise self._error


# ---------------------------------------------------------------------------
# Plan 051 P2.3: the sync-service lifecycle reports its actual listener
# state to the UI so the LCD never claims sync-ready while nothing is
# bound on the sync port.
# ---------------------------------------------------------------------------


class SyncStateRecordingUi(SyncAwarePrintUi):
    """SyncAwarePrintUi that also records service-state notifications."""

    async def sync_service_state_changed(self, listening: bool) -> None:
        self.events.append(f"sync_listening:{listening}")


@pytest.mark.asyncio
async def test_start_sync_service_guarded_reports_listening_state() -> None:
    ui = SyncStateRecordingUi(should_print=False)

    await app.start_sync_service_guarded(FakeSyncService(), reason="startup", ui=ui)
    await app.start_sync_service_guarded(FakeSyncService(fail_start=True), reason="startup", ui=ui)
    await app.start_sync_service_guarded(None, reason="startup", ui=ui)

    assert ui.events == [
        "sync_listening:True",
        "sync_listening:False",
        "sync_listening:False",
    ]


@pytest.mark.asyncio
async def test_stop_sync_service_guarded_reports_not_listening() -> None:
    ui = SyncStateRecordingUi(should_print=False)

    await app.stop_sync_service_guarded(FakeSyncService(), reason="config_applied", ui=ui)
    # Even a failed stop leaves the service unreliable — report not-listening.
    await app.stop_sync_service_guarded(
        FakeSyncService(fail_stop=True), reason="config_applied", ui=ui
    )

    assert ui.events == ["sync_listening:False", "sync_listening:False"]


@pytest.mark.asyncio
async def test_apply_sync_destination_change_threads_ui_state() -> None:
    ui = SyncStateRecordingUi(should_print=False)
    service = FakeSyncService()

    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.IPHONE),
        service=service,
        ui=ui,
    )
    await app.apply_sync_destination_change(
        SyncConfig(destination=SyncDestination.PRINT),
        service=service,
        ui=ui,
    )

    assert service.events == ["start", "stop"]
    assert ui.events == ["sync_listening:True", "sync_listening:False"]


@pytest.mark.asyncio
async def test_sync_service_state_hook_is_optional() -> None:
    # A UI without the hook (or a bare object) must not break the lifecycle.
    ui = SyncAwarePrintUi(should_print=False)

    await app.start_sync_service_guarded(FakeSyncService(), reason="startup", ui=ui)
    await app.start_sync_service_guarded(FakeSyncService(), reason="startup", ui=object())
    await app.stop_sync_service_guarded(FakeSyncService(), reason="shutdown", ui=None)

    assert ui.events == []


# ---------------------------------------------------------------------------
# Plan 051 P3.11: sync-token rotation restarts the service so it re-reads
# the rotated bearer token. The stop leg is silent (the controller already
# put the surface in "starting"); only the start outcome is reported, so
# the UI flow reads "starting" → "listening" (or "unavailable" on failure).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_rotation_restart_restarts_service_and_reports_listening() -> None:
    ui = SyncStateRecordingUi(should_print=False)
    service = FakeSyncService()

    await app.restart_sync_service_for_token_rotation(service, enabled=True, ui=ui)

    assert service.events == ["stop", "start"]
    assert ui.events == ["sync_listening:True"]


@pytest.mark.asyncio
async def test_token_rotation_restart_reports_failure_as_not_listening() -> None:
    ui = SyncStateRecordingUi(should_print=False)
    service = FakeSyncService(fail_start=True)

    await app.restart_sync_service_for_token_rotation(service, enabled=True, ui=ui)

    assert service.events == ["stop"]
    assert ui.events == ["sync_listening:False"]


@pytest.mark.asyncio
async def test_token_rotation_restart_skips_start_when_sync_disabled() -> None:
    ui = SyncStateRecordingUi(should_print=False)
    service = FakeSyncService()

    await app.restart_sync_service_for_token_rotation(service, enabled=False, ui=ui)

    assert service.events == ["stop"]
    assert ui.events == []


@pytest.mark.asyncio
async def test_token_rotation_restart_survives_missing_service() -> None:
    ui = SyncStateRecordingUi(should_print=False)

    await app.restart_sync_service_for_token_rotation(None, enabled=True, ui=ui)

    # Nothing can listen this boot: report it rather than staying silent.
    assert ui.events == ["sync_listening:False"]


# ---------------------------------------------------------------------------
# Plan 054 phase A: virtual-LCD wiring helpers
# ---------------------------------------------------------------------------


def test_make_remote_screen_provider_renders_and_caches_per_snapshot() -> None:
    """The provider renders the live snapshot and reuses the frame object
    while the snapshot is unchanged, so SyncService's identity-keyed PNG
    cache holds across polls of an idle screen."""

    snapshot = UiSnapshot(mode=UiMode.READY, ftp_host="192.168.8.1")
    snapshots = [snapshot]
    provider = app.make_remote_screen_provider(lambda: snapshots[0])

    first = provider()
    assert first is not None
    assert first.size == (240, 240)
    assert provider() is first  # unchanged snapshot -> cached frame object

    snapshots[0] = UiSnapshot(mode=UiMode.SETTINGS, ftp_host="192.168.8.1")
    second = provider()
    assert second is not None
    assert second is not first


def test_make_remote_input_injector_maps_action_strings() -> None:
    injected: list[object] = []

    def _inject(action: object) -> bool:
        injected.append(action)
        return True

    injector = app.make_remote_input_injector(_inject)

    from instantlink_bridge.ui.models import UiAction

    assert injector("select") is True
    assert injector("pair") is True
    assert injected == [UiAction.SELECT, UiAction.PAIR]
    assert injector("jump") is False  # unknown strings never reach the queue
    assert injected == [UiAction.SELECT, UiAction.PAIR]
