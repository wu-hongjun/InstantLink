from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

import pytest

from instantlink_bridge.config import BridgeConfig, FtpConfig, FtpReceiveMode, write_config
from instantlink_bridge.net.health import FtpActivityTracker, build_connection_health
from instantlink_bridge.power.performance import CpuPerformanceController
from instantlink_bridge.ui import controller
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.display import NullDisplay
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiMode
from instantlink_bridge.ui.settings import WifiMode


def make_ui(setter: Callable[[WifiMode], Awaitable[str]]) -> BridgeUi:
    ui = BridgeUi(
        BridgeConfig(ftp=FtpConfig(mode=FtpReceiveMode.HOTSPOT)),
        display=NullDisplay(),
        input_device=NullInput(),
        wifi_mode_setter=setter,
    )
    ui._hotspot_recovery_enabled = True
    ui._hotspot_recovery_next_at = 0
    return ui


async def radio_enabled() -> bool:
    return True


@pytest.mark.asyncio
async def test_past_camera_login_does_not_delay_missing_hotspot_recovery() -> None:
    async def setter(_mode: WifiMode) -> str:
        return "ok"

    ui = make_ui(setter)
    ui._ftp_activity = FtpActivityTracker()
    ui._ftp_activity.record_connection("192.168.8.59")
    assert ui._hotspot_recovery_allowed()
    ui._hotspot_host = "192.168.8.1"
    assert not ui._hotspot_recovery_allowed()


@pytest.mark.asyncio
async def test_locked_recovery_keeps_idle_cpu_dark_display_and_printer_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governors: list[str] = []
    addresses: list[str] = []

    async def cpu_setter(governor: str) -> None:
        governors.append(governor)

    async def wifi_setter(mode: WifiMode) -> str:
        assert mode is WifiMode.HOTSPOT
        addresses.append("192.168.8.1")
        return "hotspot active"

    class Display(NullDisplay):
        def __init__(self) -> None:
            self.frames = 0
            self.stages: list[str] = []

        def render(self, snapshot: controller.UiSnapshot) -> None:
            self.frames += 1

        def set_idle_stage(self, stage: str) -> None:
            self.stages.append(stage)

    cpu = CpuPerformanceController(cpu_setter)
    await cpu.start()
    display = Display()
    ui = make_ui(wifi_setter)
    ui._cpu_performance = cpu
    ui._display = display
    printer = PairedPrinter("FA:AB:BC:C7:95:64", "INSTAX-52006924")
    ui._snapshot = replace(
        ui._snapshot,
        mode=UiMode.READY,
        paired_printer=printer,
        film_remaining=6,
        printer_status_fresh=True,
    )
    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio_enabled)
    monkeypatch.setattr(
        controller,
        "detect_camera_link_health",
        lambda **_: build_connection_health(
            checked_at=time.time(),
            expected_usb_ipv4="192.168.7.1",
            usb_carrier=True,
            usb_ipv4_addresses=["192.168.7.1"],
            wifi_ipv4_addresses=addresses,
        ),
    )
    ui._lock_screen()
    if cpu._task is not None:
        await cpu._task
    assert governors == ["performance", "powersave"]
    assert ui._network_status_poll_interval_s() == 5.0
    await ui._refresh_network_status()
    assert ui._hotspot_recovery_task is not None
    await ui._hotspot_recovery_task
    assert ui.live_snapshot.hotspot_host == "192.168.8.1"
    assert ui.live_snapshot.camera_receive_ready
    assert ui.live_snapshot.paired_printer == printer
    assert ui.live_snapshot.printer_status_fresh
    assert ui._screen_locked
    assert ui.snapshot.idle_stage == "screen_off"
    assert display.frames == 0
    assert display.stages == ["screen_off"]
    assert governors == ["performance", "powersave"]
    await ui.stop()
    await cpu.close()


@pytest.mark.asyncio
async def test_boot_failure_retries_without_blocking_network_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[WifiMode] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def setter(mode: WifiMode) -> str:
        calls.append(mode)
        if len(calls) == 1:
            raise RuntimeError("firmware unavailable")
        started.set()
        await release.wait()
        return "ok"

    ui = make_ui(setter)
    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio_enabled)
    health = build_connection_health(
        checked_at=time.time(),
        expected_usb_ipv4="192.168.7.1",
        usb_carrier=True,
        usb_ipv4_addresses=["192.168.7.1"],
        wifi_ipv4_addresses=[],
    )
    monkeypatch.setattr(controller, "detect_camera_link_health", lambda **_: health)
    await ui._apply_configured_ftp_mode_at_start()
    await ui._refresh_network_status()
    await asyncio.wait_for(started.wait(), timeout=1)
    # An unfinished helper is not awaited by health polling; no duplicate starts.
    await asyncio.wait_for(ui._refresh_network_status(), timeout=1)
    assert calls == [WifiMode.HOTSPOT, WifiMode.HOTSPOT]
    assert ui.snapshot.usb_connected
    release.set()
    assert ui._hotspot_recovery_task is not None
    await ui._hotspot_recovery_task
    assert ui._hotspot_recovery_failures == 1


@pytest.mark.asyncio
async def test_recovery_backoff_caps_at_five_minutes_and_requires_verified_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[WifiMode] = []

    async def setter(mode: WifiMode) -> str:
        calls.append(mode)
        return "helper succeeded but IP still absent"

    async def refresh() -> None:
        return

    ui = make_ui(setter)
    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio_enabled)
    monkeypatch.setattr(ui, "_refresh_network_status", refresh)
    for delay in (30, 60, 120, 300, 300):
        before = asyncio.get_running_loop().time()
        await ui._recover_hotspot()
        assert before + delay <= ui._hotspot_recovery_next_at <= before + delay + 1
        ui._schedule_hotspot_recovery()
        assert ui._hotspot_recovery_task is None
    assert len(calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(FtpReceiveMode))
async def test_ready_and_other_receive_modes_do_not_probe_or_activate(mode: FtpReceiveMode) -> None:
    async def setter(_mode: WifiMode) -> str:
        pytest.fail("unexpected network mutation")

    ui = make_ui(setter)
    ui._config = replace(ui._config, ftp=replace(ui._config.ftp, mode=mode))
    if mode is FtpReceiveMode.HOTSPOT:
        ui._hotspot_host = "192.168.8.1"
        ui._hotspot_recovery_failures = 3
    ui._schedule_hotspot_recovery()
    assert ui._hotspot_recovery_task is None
    if mode is FtpReceiveMode.HOTSPOT:
        assert ui._hotspot_recovery_failures == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, None])
async def test_disabled_or_unknown_radio_is_left_untouched(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool | None,
) -> None:
    async def setter(_mode: WifiMode) -> str:
        pytest.fail("intentional off/unknown state must not be overridden")

    async def radio() -> bool | None:
        return enabled

    ui = make_ui(setter)
    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio)
    await ui._recover_hotspot()
    assert ui._hotspot_recovery_failures == 0
    assert ui._hotspot_recovery_next_at > asyncio.get_running_loop().time() + 299


@pytest.mark.asyncio
async def test_recovery_defers_active_jobs_settings_and_recent_ftp() -> None:
    async def setter(_mode: WifiMode) -> str:
        pytest.fail("busy runtime must not mutate networking")

    ui = make_ui(setter)
    for mode in (UiMode.PRINTING, UiMode.IMAGE_RECEIVED):
        ui._snapshot = replace(ui._snapshot, mode=mode)
        ui._schedule_hotspot_recovery()
        assert ui._hotspot_recovery_task is None
    ui._snapshot = replace(ui._snapshot, mode=UiMode.READY)
    ui._settings_operation_pending = True
    ui._schedule_hotspot_recovery()
    assert ui._hotspot_recovery_task is None
    ui._settings_operation_pending = False
    ui._ftp_activity = FtpActivityTracker()
    ui._ftp_activity.record_connection("192.168.7.2")
    ui._schedule_hotspot_recovery()
    assert ui._hotspot_recovery_task is None


@pytest.mark.asyncio
async def test_mode_switch_cancels_recovery_before_applying_new_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls: list[WifiMode] = []

    async def setter(mode: WifiMode) -> str:
        calls.append(mode)
        if mode is WifiMode.HOTSPOT:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return "ok"

    async def refresh() -> None:
        return

    ui = make_ui(setter)
    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio_enabled)
    monkeypatch.setattr(ui, "_refresh_network_status", refresh)
    ui._schedule_hotspot_recovery()
    await asyncio.wait_for(started.wait(), timeout=1)
    await ui._set_ftp_receive_mode(
        replace(ui._config, ftp=replace(ui._config.ftp, mode=FtpReceiveMode.PEER))
    )
    assert cancelled.is_set()
    assert calls == [WifiMode.HOTSPOT, WifiMode.HOME]
    assert ui._hotspot_recovery_task is None
    assert ui._config.ftp.mode is FtpReceiveMode.PEER


@pytest.mark.asyncio
async def test_startup_grace_and_stop_do_not_leave_recovery_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def setter(_mode: WifiMode) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "unreachable"

    ui = make_ui(setter)
    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio_enabled)
    ui._hotspot_recovery_next_at = asyncio.get_running_loop().time() + 30
    ui._schedule_hotspot_recovery()
    assert ui._hotspot_recovery_task is None
    ui._hotspot_recovery_next_at = 0
    ui._schedule_hotspot_recovery()
    await asyncio.wait_for(started.wait(), timeout=1)
    await ui.stop()
    assert cancelled.is_set()
    assert not ui._hotspot_recovery_enabled


@pytest.mark.asyncio
async def test_cancelled_helper_terminates_process_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        returncode: int | None = None

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.exited = asyncio.Event()
            self.terminated = False

        async def communicate(self) -> tuple[bytes, None]:
            self.started.set()
            await self.exited.wait()
            return b"", None

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15
            self.exited.set()

    process = Process()

    async def create(*_args: object, **_kwargs: object) -> Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(controller.set_wifi_mode_with_helper(WifiMode.HOTSPOT))
    await asyncio.wait_for(process.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert process.returncode == -15


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "returncode", "expected"),
    [
        (b"enabled\n", 0, True),
        (b"disabled\n", 0, False),
        (b"other\n", 0, None),
        (b"enabled\n", 1, None),
    ],
)
async def test_radio_probe_classifies_only_known_successful_output(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
    returncode: int,
    expected: bool | None,
) -> None:
    class Process:
        async def communicate(self) -> tuple[bytes, None]:
            return output, None

    process = Process()
    process.returncode = returncode

    async def create(*_args: object, **_kwargs: object) -> Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    assert await controller.detect_wifi_radio_enabled() is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [FtpReceiveMode.WIRED, FtpReceiveMode.PEER])
@pytest.mark.parametrize("changed_during_probe", [False, True])
async def test_persisted_app_mode_changes_prevent_stale_hotspot_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: FtpReceiveMode,
    changed_during_probe: bool,
) -> None:
    async def setter(_mode: WifiMode) -> str:
        pytest.fail("persisted App intent must take precedence over stale live config")

    ui = make_ui(setter)
    ui._config_path = tmp_path / "config.toml"
    updated = replace(ui._config, ftp=replace(ui._config.ftp, mode=mode))
    write_config(ui._config if changed_during_probe else updated, ui._config_path)

    async def radio() -> bool:
        if changed_during_probe:
            assert ui._config_path is not None
            write_config(updated, ui._config_path)
        return True

    monkeypatch.setattr(controller, "detect_wifi_radio_enabled", radio)
    await ui._recover_hotspot()
    assert ui._hotspot_recovery_failures == 0
    assert ui._hotspot_recovery_next_at > asyncio.get_running_loop().time() + 299


@pytest.mark.asyncio
async def test_cancelled_helper_cleanup_is_bounded_even_with_inherited_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        returncode: int | None = None

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.terminated = False
            self.killed = False

        async def communicate(self) -> tuple[bytes, None]:
            self.started.set()
            await asyncio.Event().wait()
            return b"", None

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            return -9

    process = Process()

    async def create(*_args: object, **_kwargs: object) -> Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(controller.set_wifi_mode_with_helper(WifiMode.HOTSPOT))
    await asyncio.wait_for(process.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert process.terminated and process.killed


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_radio_probe_timeout_and_cancellation_reap_process(
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    class Process:
        returncode: int | None = None

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.exited = asyncio.Event()
            self.killed = False

        async def communicate(self) -> tuple[bytes, None]:
            self.started.set()
            await self.exited.wait()
            return b"", None

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9
            self.exited.set()

        async def wait(self) -> int:
            return -9

    process = Process()

    async def create(*_args: object, **_kwargs: object) -> Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(controller.detect_wifi_radio_enabled())
    await asyncio.wait_for(process.started.wait(), timeout=1)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await asyncio.wait_for(task, timeout=3) is None
    assert process.killed
