from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from test_ui_controller import (
    _FakeDisplay,
    _FakePairer,
    _FakeStatusProvider,
    _unused_wifi_mode_setter,
)

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import AdjustmentsConfig, BridgeConfig
from instantlink_bridge.imaging import postprocess
from instantlink_bridge.imaging.pipeline import FitMode, PreparedImage, PrintEdit
from instantlink_bridge.net.health import ConnectionHealth, build_connection_health
from instantlink_bridge.ui import controller
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import UiMode
from instantlink_bridge.ui.settings import SettingKey, SettingsPage


def make_ui(
    *, config: BridgeConfig | None = None, provider: _FakeStatusProvider | None = None
) -> BridgeUi:
    return BridgeUi(
        config or BridgeConfig(),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer([]),
        status_provider=provider or _FakeStatusProvider(),
        wifi_mode_setter=_unused_wifi_mode_setter,
    )


def health_for(host: str) -> ConnectionHealth:
    return build_connection_health(
        checked_at=time.time(),
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4=host,
        usb_carrier=True,
        usb_ipv4_addresses=["192.168.7.1"],
        wifi_ipv4_addresses=[host],
    )


@pytest.mark.asyncio
async def test_network_refresh_callers_share_one_probe_and_waiter_cancellation_is_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = Event(), Event()
    calls = 0

    def probe(**_kwargs: object) -> ConnectionHealth:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return health_for("192.168.8.1")

    ui = make_ui()
    monkeypatch.setattr(controller, "detect_camera_link_health", probe)
    first = asyncio.create_task(ui._refresh_network_status())
    assert await asyncio.to_thread(started.wait, 1)
    second = asyncio.create_task(ui._refresh_network_status())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert ui._network_refresh_task is not None and not ui._network_refresh_task.done()
    release.set()
    await asyncio.wait_for(second, 1)
    assert calls == 1
    assert ui.live_snapshot.hotspot_host == "192.168.8.1"
    await ui.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_config", [True, False])
async def test_network_refresh_discards_probe_after_config_or_wifi_activation_changes(
    monkeypatch: pytest.MonkeyPatch,
    changed_config: bool,
) -> None:
    started, release = Event(), Event()
    hosts: list[str] = []

    def probe(**kwargs: object) -> ConnectionHealth:
        host = str(kwargs["expected_hotspot_ipv4"])
        hosts.append(host)
        if len(hosts) == 1:
            started.set()
            assert release.wait(2)
        return health_for(host)

    ui = make_ui()
    monkeypatch.setattr(controller, "detect_camera_link_health", probe)
    task = asyncio.create_task(ui._refresh_network_status())
    assert await asyncio.to_thread(started.wait, 1)
    if changed_config:
        ui._config = replace(ui._config, ftp=replace(ui._config.ftp, hotspot_host="192.168.9.1"))
    else:

        async def activate(_mode: object) -> str:
            return "activated"

        monkeypatch.setattr(ui, "_wifi_mode_setter", activate)
        await ui._apply_ftp_mode_network(ui.config.ftp.mode)
    release.set()
    await asyncio.wait_for(task, 1)
    assert len(hosts) == 2
    assert ui.live_snapshot.hotspot_host == ("192.168.9.1" if changed_config else "192.168.8.1")
    assert ui._network_refresh_task is not None and ui._network_refresh_task.done()
    await ui.stop()


@pytest.mark.asyncio
async def test_network_probe_cannot_apply_after_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    started, release, finished = Event(), Event(), Event()

    def probe(**_kwargs: object) -> ConnectionHealth:
        started.set()
        assert release.wait(2)
        finished.set()
        return health_for("192.168.8.1")

    ui = make_ui()
    monkeypatch.setattr(controller, "detect_camera_link_health", probe)
    task = asyncio.create_task(ui._refresh_network_status())
    assert await asyncio.to_thread(started.wait, 1)
    await ui.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    before = ui.live_snapshot
    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    await asyncio.sleep(0)
    assert ui.live_snapshot is before
    assert ui.live_snapshot.hotspot_host is None


@pytest.mark.asyncio
async def test_settings_refresh_overlaps_network_and_paired_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_started, paired_started = asyncio.Event(), asyncio.Event()
    ui = make_ui()
    ui._show_settings(page=SettingsPage.SYSTEM)

    async def network() -> None:
        network_started.set()
        await asyncio.wait_for(paired_started.wait(), 0.2)

    async def paired() -> list[object]:
        paired_started.set()
        await asyncio.wait_for(network_started.wait(), 0.2)
        return []

    monkeypatch.setattr(ui, "_refresh_network_status", network)
    monkeypatch.setattr(ui._pairer, "list_paired", paired)
    await asyncio.wait_for(ui._refresh_status_from_settings(), 0.5)
    assert ui.live_snapshot.settings_message == "No printer saved"
    await ui.stop()


@pytest.mark.asyncio
async def test_settings_refresh_cancels_and_joins_its_independent_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = [asyncio.Event(), asyncio.Event()]
    canceled = [asyncio.Event(), asyncio.Event()]
    ui = make_ui()
    ui._show_settings(page=SettingsPage.SYSTEM)

    async def blocked(index: int) -> list[object]:
        starts[index].set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled[index].set()
        return []

    async def network() -> None:
        await blocked(0)

    async def paired() -> list[object]:
        return await blocked(1)

    monkeypatch.setattr(ui, "_refresh_network_status", network)
    monkeypatch.setattr(ui._pairer, "list_paired", paired)
    task = asyncio.create_task(ui._refresh_status_from_settings())
    await asyncio.gather(*(started.wait() for started in starts))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(event.is_set() for event in canceled)
    await ui.stop()


@pytest.mark.asyncio
async def test_settings_refresh_action_returns_before_io_and_keeps_navigation_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    ui = make_ui()
    ui._show_settings(page=SettingsPage.SYSTEM)

    async def network() -> None:
        started.set()
        await release.wait()

    monkeypatch.setattr(ui, "_refresh_network_status", network)
    await asyncio.wait_for(ui._activate_setting(SettingKey.REFRESH_STATUS), 0.2)
    await asyncio.wait_for(started.wait(), 0.2)
    assert ui._settings_status_task is not None and not ui._settings_status_task.done()
    original_task = ui._settings_status_task
    await ui._activate_setting(SettingKey.REFRESH_STATUS)
    assert ui._settings_status_task is original_task
    ui._show_cached_home_status()
    release.set()
    await original_task
    assert ui.live_snapshot.mode is UiMode.NEEDS_PAIRING
    await ui.stop()


@pytest.mark.asyncio
async def test_preview_overlaps_model_detection_and_exif_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_started, metadata_started = Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    ui = make_ui(config=BridgeConfig(adjustments=AdjustmentsConfig(datestamp=True)))
    seen: list[str] = []

    async def model() -> PrinterModel:
        model_started.set()
        await asyncio.wait_for(metadata_started.wait(), 0.5)
        return PrinterModel.SQUARE

    def metadata(*_args: object, **_kwargs: object) -> str:
        loop.call_soon_threadsafe(metadata_started.set)
        assert model_started.wait(0.5)
        return "2026-10-11"

    async def prepare(*_args: object, **kwargs: object) -> PreparedImage:
        adjustments = kwargs["adjustments"]
        assert isinstance(adjustments, postprocess.AdjustmentProfile)
        seen.append(adjustments.datestamp_text)
        return PreparedImage(b"jpeg", PrinterModel.SQUARE, 80, 80, 100, FitMode.AUTO)

    monkeypatch.setattr(ui, "_resolve_printer_model_for_preview", model)
    monkeypatch.setattr(postprocess, "read_exif_datestamp_text", metadata)
    monkeypatch.setattr(controller, "prepare_for_instax_async", prepare)
    monkeypatch.setattr(
        controller, "create_preview_from_prepared", lambda _: Image.new("RGB", (80, 80))
    )
    await asyncio.wait_for(
        ui._prepare_preview_image(ReceivedImage(tmp_path / "photo.jpg", "camera"), PrintEdit()), 1
    )
    assert seen == ["2026-10-11"]
    await ui.stop()


@pytest.mark.asyncio
async def test_cancel_preview_joins_model_task_and_never_applies_late_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    metadata_started, metadata_release, metadata_finished = Event(), Event(), Event()
    model_cancelled = asyncio.Event()
    ui = make_ui(config=BridgeConfig(adjustments=AdjustmentsConfig(datestamp=True)))

    async def model() -> PrinterModel:
        try:
            await asyncio.Event().wait()
        finally:
            model_cancelled.set()
        raise AssertionError("canceled detection cannot return a model")

    def metadata(*_args: object, **_kwargs: object) -> str:
        metadata_started.set()
        assert metadata_release.wait(2)
        metadata_finished.set()
        return "late metadata"

    monkeypatch.setattr(ui, "_resolve_printer_model_for_preview", model)
    monkeypatch.setattr(postprocess, "read_exif_datestamp_text", metadata)
    task = asyncio.create_task(
        ui._prepare_preview_image(ReceivedImage(tmp_path / "photo.jpg", "camera"), PrintEdit())
    )
    try:
        assert await asyncio.to_thread(metadata_started.wait, 1)
        task.cancel()
        await asyncio.wait_for(model_cancelled.wait(), 0.2)
        await asyncio.sleep(0)
        assert not task.done()
        assert not metadata_finished.is_set()
        metadata_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert model_cancelled.is_set()
        assert metadata_finished.is_set()
        assert ui._prepared_print_image is None
    finally:
        metadata_release.set()
        await ui.stop()


@pytest.mark.asyncio
async def test_shutdown_cancels_all_tasks_before_waiting_for_any_cleanup() -> None:
    canceled = [asyncio.Event(), asyncio.Event()]
    finished: list[int] = []
    starts = [asyncio.Event(), asyncio.Event()]
    ui = make_ui()

    async def worker(index: int) -> None:
        starts[index].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled[index].set()
            await canceled[1 - index].wait()
            finished.append(index)

    ui._action_task = asyncio.create_task(worker(0))
    ui._status_task = asyncio.create_task(worker(1))
    await asyncio.gather(*(started.wait() for started in starts))
    await asyncio.wait_for(ui.stop(), 0.2)
    assert sorted(finished) == [0, 1]


@pytest.mark.asyncio
async def test_shutdown_uses_one_deadline_for_all_slow_task_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    ui = make_ui()

    async def worker(index: int) -> None:
        starts[index].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    tasks = [asyncio.create_task(worker(index)) for index in range(2)]
    ui._action_task, ui._status_task = tasks
    await asyncio.gather(*(started.wait() for started in starts))
    monkeypatch.setattr(controller, "UI_TASK_CANCEL_BUDGET_S", 0.03)
    before = asyncio.get_running_loop().time()
    try:
        await ui.stop()
        elapsed = asyncio.get_running_loop().time() - before
        assert elapsed < 0.15
        assert all(not task.done() for task in tasks)
    finally:
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_repeated_stop_cancel_waits_for_workers_before_closing_resources() -> None:
    cleaning, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    provider = _FakeStatusProvider()
    ui = make_ui(provider=provider)

    async def worker() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            finished.set()

    ui._action_task = asyncio.create_task(worker())
    await asyncio.sleep(0)
    stop = asyncio.create_task(ui.stop())
    await asyncio.wait_for(cleaning.wait(), 0.2)
    stop.cancel()
    await asyncio.sleep(0)
    stop.cancel()
    await asyncio.sleep(0)
    assert not stop.done()
    assert provider.close_calls == 0
    assert provider.close_cached_calls == 0
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stop, 0.2)
    assert finished.is_set()
    assert provider.close_calls == 1
    assert provider.close_cached_calls == 1


@pytest.mark.asyncio
async def test_repeated_preview_cancellation_does_not_interrupt_model_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    started, cleaning, release_model, finished = (asyncio.Event() for _ in range(4))
    release_metadata = Event()
    ui = make_ui(config=BridgeConfig(adjustments=AdjustmentsConfig(datestamp=True)))

    async def model() -> PrinterModel:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release_model.wait()
            finished.set()
            raise

    def metadata(*_args: object, **_kwargs: object) -> str:
        assert release_metadata.wait(2)
        return "metadata"

    monkeypatch.setattr(ui, "_resolve_printer_model_for_preview", model)
    monkeypatch.setattr(postprocess, "read_exif_datestamp_text", metadata)
    task = asyncio.create_task(
        ui._prepare_preview_image(ReceivedImage(tmp_path / "photo.jpg", "camera"), PrintEdit())
    )
    try:
        await asyncio.wait_for(started.wait(), 0.2)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 0.2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not finished.is_set()
        release_model.set()
        release_metadata.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert finished.is_set()
    finally:
        release_metadata.set()
        await ui.stop()
