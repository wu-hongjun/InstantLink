from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from test_image_worker import FakeFactory, FakeProcess, FakeResultReader
from test_ui_controller import (
    _FakeDisplay,
    _FakePairer,
    _unused_wifi_mode_setter,
    _wait_for_preview_image,
)

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig, CorrectionConfig, PrinterConfig, UiConfig
from instantlink_bridge.imaging import worker as image_worker
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    ImagePipelineError,
    PreparedImage,
    PrintEdit,
)
from instantlink_bridge.imaging.worker import ImagePreparationWorker
from instantlink_bridge.power.performance import CpuPerformanceController
from instantlink_bridge.ui.controller import BridgeUi, PreviewTool
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import UiAction, UiMode, UiSnapshot


def _ui(display: _FakeDisplay, *, cpu: CpuPerformanceController | None = None) -> BridgeUi:
    return BridgeUi(
        BridgeConfig(
            printer=PrinterConfig(model=PrinterModel.SQUARE),
            ui=UiConfig(unlock_requires_three_presses=False),
        ),
        display=display,
        input_device=NullInput(),
        pairer=_FakePairer([]),
        wifi_mode_setter=_unused_wifi_mode_setter,
        cpu_performance=cpu,
    )


@pytest.mark.asyncio
async def test_review_duration_starts_after_slow_preview_is_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    display = _FakeDisplay()
    ui = _ui(display)
    release = asyncio.Event()
    started = asyncio.Event()

    async def build(_received: ReceivedImage, _edit: PrintEdit) -> Image.Image:
        started.set()
        await release.wait()
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=0.1)
    )
    await started.wait()
    await asyncio.sleep(0.15)
    assert not task.done()
    assert display.snapshots[-1].print_title == "Preparing preview"
    release.set()
    await _wait_for_preview_image(display)
    visible_reviews = [snapshot for snapshot in display.snapshots if snapshot.preview_image]
    assert visible_reviews[0].print_title == "Print in 1s"
    assert not any(snapshot.print_title == "Preview" for snapshot in visible_reviews)
    assert not task.done()
    await asyncio.sleep(0.04)
    assert not task.done()
    assert await asyncio.wait_for(task, 0.5) == PrintEdit()


@pytest.mark.parametrize("action", [UiAction.UP, UiAction.HELP, UiAction.PAIR])
@pytest.mark.asyncio
async def test_edit_or_tool_switch_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: UiAction
) -> None:
    display = _FakeDisplay()
    ui = _ui(display)

    async def build(_received: ReceivedImage, _edit: PrintEdit) -> Image.Image:
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=0.1)
    )
    await _wait_for_preview_image(display)
    await ui._handle_action(action)
    await asyncio.sleep(0.15)
    assert not task.done()
    assert display.snapshots[-1].print_title == "Preview"
    assert display.snapshots[-1].print_progress_percent is None
    await ui._handle_action(UiAction.SELECT)
    edit = await asyncio.wait_for(task, 0.5)
    assert edit == (PrintEdit(zoom=1.25) if action is UiAction.UP else PrintEdit())


@pytest.mark.parametrize(
    ("edit", "tool", "action"),
    [
        (PrintEdit(), "zoom", UiAction.DOWN),
        (PrintEdit(zoom=3.0), "zoom", UiAction.UP),
        (PrintEdit(zoom=1.5, offset_x=1.0), "crop", UiAction.RIGHT),
        (PrintEdit(), "rotate", UiAction.UP),
    ],
)
@pytest.mark.asyncio
async def test_unchanged_edit_stops_countdown_without_rebuilding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    edit: PrintEdit,
    tool: PreviewTool,
    action: UiAction,
) -> None:
    display = _FakeDisplay()
    ui = _ui(display)
    builds = 0

    async def build(_received: ReceivedImage, _edit: PrintEdit) -> Image.Image:
        nonlocal builds
        builds += 1
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=0.04)
    )
    try:
        await _wait_for_preview_image(display)
        ui._preview_edit, ui._preview_tool = edit, tool
        await ui._handle_action(action)
        await asyncio.sleep(0.06)
        assert builds == 1
        assert ui._preview_edit == edit
        assert not task.done()
        assert ui.live_snapshot.print_title == "Preview"
        assert ui.live_snapshot.print_progress_percent is None
        await ui._handle_action(UiAction.SELECT)
        assert await asyncio.wait_for(task, 0.5) == edit
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_preparing_preview_terminates_worker_and_releases_boost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = FakeProcess()
    reader = FakeResultReader()
    started = asyncio.Event()
    worker = ImagePreparationWorker(
        process_factory=FakeFactory([(process, reader)], on_call=lambda _: started.set()),
        poll_interval_s=0.001,
        shutdown_grace_s=0.001,
    )
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)
    await cpu.start()
    ui = _ui(_FakeDisplay())

    async def build(received: ReceivedImage, _edit: PrintEdit) -> Image.Image:
        await worker.prepare(received.path, PrinterModel.SQUARE)
        raise AssertionError("cancelled worker must never return")

    monkeypatch.setattr(ui, "_build_preview_image", build)

    async def job() -> PrintEdit | None:
        async with cpu.boost():
            return await ui.await_print_confirmation(
                ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=None
            )

    task = asyncio.create_task(job())
    await asyncio.wait_for(started.wait(), 0.5)
    assert modes[-1] == "performance"
    await ui._handle_action(UiAction.BACK)
    assert await asyncio.wait_for(task, 0.5) is None
    assert process.terminated
    assert process.closed
    assert reader.closed
    assert modes[-1] == "powersave"
    await cpu.close()


@pytest.mark.asyncio
async def test_edit_rebuild_keeps_cancel_responsive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    display = _FakeDisplay()
    ui = _ui(display)
    rebuilding = asyncio.Event()
    cancelled = asyncio.Event()

    async def build(_received: ReceivedImage, edit: PrintEdit) -> Image.Image:
        if edit == PrintEdit():
            return Image.new("RGB", (80, 80))
        rebuilding.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("cancelled rebuild must never return")

    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=None)
    )
    await _wait_for_preview_image(display)
    # A slow rebuild must not block the shared GPIO/virtual input handler.
    await asyncio.wait_for(ui._handle_action(UiAction.UP), 0.1)
    await asyncio.wait_for(rebuilding.wait(), 0.5)
    assert display.snapshots[-1].print_title == "Updating preview"
    await asyncio.wait_for(ui._handle_action(UiAction.BACK), 0.1)
    assert await asyncio.wait_for(task, 0.5) is None
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_timed_preview_preserves_prepared_bytes_for_print(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (120, 90), (100, 140, 160)).save(path)
    ui = _ui(_FakeDisplay())
    received = ReceivedImage(path, "camera")
    edit = await ui.await_print_confirmation(received, timeout_s=0.05)
    assert ui.take_prepared_print_image(received, edit) is not None
    assert ui.take_prepared_print_image(received, edit) is None


@pytest.mark.asyncio
async def test_prepared_preview_rejects_changed_printer_correction(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (120, 90), (100, 140, 160)).save(path)
    ui = _ui(_FakeDisplay())
    received = ReceivedImage(path, "camera")
    edit = await ui.await_print_confirmation(received, timeout_s=0.05)
    ui._config = replace(ui.config, correction=CorrectionConfig(saturation=-40))
    assert ui.take_prepared_print_image(received, edit) is None


@pytest.mark.parametrize("late_action", [UiAction.BACK, UiAction.UP])
@pytest.mark.asyncio
async def test_expired_review_commits_before_cleanup_can_accept_late_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, late_action: UiAction
) -> None:
    display = _FakeDisplay()
    ui = _ui(display)
    expired = asyncio.Event()
    render = display.render

    def observe_render(snapshot: UiSnapshot) -> None:
        render(snapshot)
        if snapshot.print_title == "Print in 0s":
            expired.set()

    async def build(_received: ReceivedImage, _edit: PrintEdit) -> Image.Image:
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(display, "render", observe_render)
    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=0.01)
    )
    await asyncio.wait_for(expired.wait(), 0.5)
    # Cleanup yields after committing the print, while the preview remains up.
    await ui._handle_action(late_action)
    assert ui.snapshot.print_title == "Print in 0s"
    assert ui.snapshot.preview_zoom == 1.0
    assert await task == PrintEdit()


@pytest.mark.asyncio
async def test_initial_status_refresh_during_preparation_releases_abandoned_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ui = _ui(_FakeDisplay())
    started = asyncio.Event()
    release = asyncio.Event()

    async def build(_received: ReceivedImage, _edit: PrintEdit) -> Image.Image:
        started.set()
        await release.wait()
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=5)
    )
    await started.wait()
    await ui.refresh_printer_status()
    release.set()
    assert await asyncio.wait_for(task, 0.5) is None
    assert (
        ui.take_prepared_print_image(ReceivedImage(tmp_path / "photo.jpg", "camera"), None) is None
    )


@pytest.mark.asyncio
async def test_confirm_during_rebuild_finishes_latest_edit_and_reuses_prepared_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (120, 90), (100, 140, 160)).save(path)
    display = _FakeDisplay()
    ui = _ui(display)
    received = ReceivedImage(path, "camera")
    task = asyncio.create_task(ui.await_print_confirmation(received, timeout_s=None))
    await _wait_for_preview_image(display)
    assert ui._prepared_print_image is not None
    rebuilding = asyncio.Event()
    release = asyncio.Event()
    builds: list[PrintEdit] = []
    original_build = ui._build_preview_image

    async def slow_rebuild(received: ReceivedImage, edit: PrintEdit) -> Image.Image | None:
        builds.append(edit)
        if edit.zoom == 1.25:
            rebuilding.set()
            await release.wait()
        return await original_build(received, edit)

    monkeypatch.setattr(ui, "_build_preview_image", slow_rebuild)
    await ui._handle_action(UiAction.UP)
    await rebuilding.wait()
    await ui._handle_action(UiAction.UP)  # Coalesce one more edit before acceptance.
    await ui._handle_action(UiAction.SELECT)
    await ui._handle_action(UiAction.UP)  # Acceptance freezes the selected edit.
    assert ui._preview_edit == PrintEdit(zoom=1.5)
    assert not task.done()
    assert ui._preview_build_task is not None and not ui._preview_build_task.cancelling()
    release.set()
    edit = await asyncio.wait_for(task, 0.5)
    assert edit == PrintEdit(zoom=1.5)
    assert builds == [PrintEdit(zoom=1.25), PrintEdit(zoom=1.5)]
    assert ui._prepared_print_key == (received.path, edit)
    assert ui.take_prepared_print_image(received, edit) is not None
    assert ui.take_prepared_print_image(received, edit) is None


@pytest.mark.parametrize("outcome", ["back", "shutdown", "failure", "no-film"])
@pytest.mark.asyncio
async def test_pending_preview_acceptance_can_cancel_fail_or_block_without_printing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outcome: str
) -> None:
    display = _FakeDisplay()
    ui = _ui(display)
    rebuilding, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def build(_received: ReceivedImage, edit: PrintEdit) -> Image.Image:
        if edit == PrintEdit():
            return Image.new("RGB", (80, 80))
        rebuilding.set()
        try:
            await release.wait()
            if outcome == "failure":
                raise ImagePipelineError("bad edited image")
            return Image.new("RGB", (80, 80))
        finally:
            finished.set()

    monkeypatch.setattr(ui, "_build_preview_image", build)
    task = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=None)
    )
    try:
        await _wait_for_preview_image(display)
        await ui._handle_action(UiAction.UP)
        await asyncio.wait_for(rebuilding.wait(), 0.5)
        await ui._handle_action(UiAction.SELECT)
        assert ui._preview_accept_requested
        assert not task.done()
        if outcome == "back":
            await asyncio.wait_for(ui._handle_action(UiAction.BACK), 0.1)
        elif outcome == "shutdown":
            task.cancel()
        else:
            if outcome == "no-film":
                ui._snapshot = replace(ui._snapshot, film_remaining=0)
            release.set()
        if outcome == "shutdown":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
        else:
            assert await asyncio.wait_for(task, 0.5) is None
        assert finished.is_set()
        assert ui._pending_print_result is None
        assert not ui._preview_accept_requested
        assert ui._prepared_print_image is None
        if outcome == "failure":
            assert ui.live_snapshot.mode is UiMode.ERROR
        elif outcome == "no-film":
            assert ui.live_snapshot.mode is UiMode.NO_FILM
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_accepting_inflight_worker_preserves_decoded_cache_and_prepared_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "photo.hif"
    source.write_bytes(b"HIF source fixture")
    output = BytesIO()
    Image.new("RGB", (80, 80), (80, 120, 160)).save(output, format="JPEG")
    prepared = PreparedImage(output.getvalue(), PrinterModel.SQUARE, 800, 800, 85, FitMode.AUTO)
    first, second = FakeProcess(), FakeProcess()
    first.finish()
    first_reader, second_reader = FakeResultReader(), FakeResultReader()
    first_reader.set_result(image_worker._PreparedImageResult(prepared))
    started = asyncio.Event()
    factory = FakeFactory(
        [(first, first_reader), (second, second_reader)],
        on_call=lambda index: started.set() if index == 1 else None,
    )
    worker = ImagePreparationWorker(
        process_factory=factory, poll_interval_s=0.001, shutdown_grace_s=0.01
    )
    monkeypatch.setattr("instantlink_bridge.ui.controller.prepare_for_instax_async", worker.prepare)
    display = _FakeDisplay()
    ui = _ui(display)
    received = ReceivedImage(source, "camera")
    confirmation = asyncio.create_task(ui.await_print_confirmation(received, timeout_s=None))
    try:
        await _wait_for_preview_image(display)
        cache = worker._working_cache
        assert cache is not None
        Image.new("RGB", (80, 80)).save(cache.path, format="BMP")
        await ui._handle_action(UiAction.UP)
        await asyncio.wait_for(started.wait(), 0.5)
        assert factory.requests[1].working_cache is cache
        await ui._handle_action(UiAction.SELECT)
        await asyncio.sleep(0.01)
        assert not confirmation.done()
        assert not second.terminated
        assert cache.path.exists()
        second.finish()
        second_reader.set_result(image_worker._PreparedImageResult(prepared))
        edit = await asyncio.wait_for(confirmation, 0.5)
        assert edit == PrintEdit(zoom=1.25)
        assert ui.take_prepared_print_image(received, edit) == prepared
        assert not second.terminated
        assert worker._working_cache is cache and cache.path.exists()
    finally:
        if not confirmation.done():
            confirmation.cancel()
            await asyncio.gather(confirmation, return_exceptions=True)
        await worker.aclose()


@pytest.mark.asyncio
async def test_locked_manual_preview_boosts_only_while_preparing_or_rebuilding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)

    cpu = CpuPerformanceController(setter)
    ui = _ui(_FakeDisplay(), cpu=cpu)
    initial_started = asyncio.Event()
    initial_release = asyncio.Event()
    rebuild_started = asyncio.Event()
    rebuild_release = asyncio.Event()

    async def prepare(_received: ReceivedImage, edit: PrintEdit) -> Image.Image:
        # Exercise the production UI boost wrapper around this I/O boundary.
        assert modes[-1] == "performance"
        if edit == PrintEdit():
            initial_started.set()
            await initial_release.wait()
        else:
            rebuild_started.set()
            await rebuild_release.wait()
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(ui, "_prepare_preview_image", prepare)
    await cpu.start()
    ui._lock_screen()
    await cpu.start()
    assert modes[-1] == "powersave"
    confirmation = asyncio.create_task(
        ui.await_print_confirmation(ReceivedImage(tmp_path / "photo.jpg", "camera"), timeout_s=None)
    )
    try:
        await asyncio.wait_for(initial_started.wait(), 0.5)
        assert modes[-1] == "performance"
        initial_release.set()
        await asyncio.wait_for(ui._preview_ready_event.wait(), 0.5)
        assert ui.snapshot.preview_image is not None
        assert not confirmation.done()
        assert modes[-1] == "powersave"

        # First input wakes only; the second edits and starts another worker.
        await ui._handle_action(UiAction.UP)
        await cpu.start()
        assert modes[-1] == "performance"
        assert ui.snapshot.preview_zoom == 1.0
        await ui._handle_action(UiAction.UP)
        await asyncio.wait_for(rebuild_started.wait(), 0.5)
        ui._lock_screen()
        await cpu.start()
        assert modes[-1] == "performance"

        rebuild_release.set()
        assert ui._preview_build_task is not None
        await asyncio.wait_for(ui._preview_build_task, 0.5)
        assert ui.snapshot.preview_zoom == 1.25
        assert not confirmation.done()
        assert modes[-1] == "powersave"

        await ui._handle_action(UiAction.BACK)  # Wake only.
        await ui._handle_action(UiAction.BACK)  # Cancel the waiting photo.
        assert await asyncio.wait_for(confirmation, 0.5) is None
    finally:
        if not confirmation.done():
            confirmation.cancel()
            await asyncio.gather(confirmation, return_exceptions=True)
        await cpu.close()
