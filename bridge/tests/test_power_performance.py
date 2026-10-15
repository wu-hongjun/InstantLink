from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from instantlink_bridge.config import BridgeConfig, UiConfig
from instantlink_bridge.power import performance
from instantlink_bridge.power.monitor import IdleStage
from instantlink_bridge.power.performance import CpuPerformanceController
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import UiAction, UiSnapshot


@pytest.mark.asyncio
async def test_locked_photo_job_boosts_and_restores_scaling_even_on_failure() -> None:
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)
    with pytest.raises(ValueError):
        async with cpu.boost():
            assert modes[-1] == "performance"
            async with cpu.boost():
                assert modes[-1] == "performance"
            raise ValueError("image failed")
    assert modes[-1] == "powersave"
    cpu.set_power_saving(False)
    await cpu.start()
    assert modes[-1] == "performance"
    await cpu.close()
    assert modes[-1] == "ondemand"


@pytest.mark.asyncio
async def test_transient_lock_failure_recovers_without_another_mode_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(performance, "CPU_RETRY_DELAY", 0.001, raising=False)
    restored = asyncio.Event()
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)
        if mode == "powersave":
            if modes.count(mode) == 1:
                raise OSError("transient failure")
            restored.set()

    cpu = CpuPerformanceController(setter)
    try:
        await cpu.start()
        cpu.set_power_saving(True)
        async with asyncio.timeout(0.15):
            await restored.wait()
        assert modes == ["performance", "powersave", "powersave"]
    finally:
        await cpu.close()


@pytest.mark.asyncio
async def test_cancel_after_governor_write_restores_locked_minimum() -> None:
    actual = "powersave"
    wrote = asyncio.Event()

    async def setter(mode: str) -> None:
        nonlocal actual
        actual = mode
        if mode == "performance":
            wrote.set()
            await asyncio.Event().wait()

    cpu = CpuPerformanceController(setter)
    cpu.set_power_saving(True)
    await cpu.start()

    async def job() -> None:
        async with cpu.boost():
            pytest.fail("cancelled boost entry must not begin work")

    task = asyncio.create_task(job())
    await wrote.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cpu._jobs == 0
    assert actual == "powersave"
    await cpu.close()


@pytest.mark.asyncio
async def test_partial_governor_failure_restores_locked_minimum() -> None:
    actual = "powersave"

    async def setter(mode: str) -> None:
        nonlocal actual
        actual = mode
        if mode == "performance":
            raise OSError("helper failed after writing sysfs")

    cpu = CpuPerformanceController(setter)
    cpu.set_power_saving(True)
    await cpu.start()
    async with cpu.boost():
        assert actual == "performance"
    assert actual == "powersave"
    await cpu.close()


@pytest.mark.asyncio
async def test_timeout_after_governor_write_restores_locked_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(performance, "CPU_SETTER_TIMEOUT", 0.01)
    actual = "powersave"

    async def setter(mode: str) -> None:
        nonlocal actual
        actual = mode
        if mode == "performance":
            await asyncio.Event().wait()

    cpu = CpuPerformanceController(setter)
    cpu.set_power_saving(True)
    await cpu.start()
    async with asyncio.timeout(0.15):
        async with cpu.boost():
            assert actual == "performance"
        assert actual == "powersave"
        await cpu.close()


@pytest.mark.asyncio
async def test_retries_back_off_coalesce_requests_and_warnings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    delays: list[float] = []
    modes: list[str] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def setter(mode: str) -> None:
        modes.append(mode)
        if len(modes) < 5:
            raise OSError("helper unavailable")

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(performance, "CPU_RETRY_MAX_DELAY", 0.7)
    cpu = CpuPerformanceController(setter)
    await cpu.start()
    retry = cpu._retry_task
    assert retry is not None
    # Polling an unchanged tier must not create more helper calls or workers.
    for _ in range(50):
        cpu.set_power_saving(False)
        assert cpu._retry_task is retry
    await retry
    assert delays == [0.25, 0.5, 0.7, 0.7]
    assert modes == ["performance"] * 5
    assert caplog.text.count("power.cpu_mode_failed") == 1
    await cpu.close()


@pytest.mark.asyncio
async def test_close_cancels_pending_retry_and_restores_ondemand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(performance, "CPU_RETRY_DELAY", 30.0)
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)
        if mode == "powersave":
            raise OSError("idle helper failed")

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)
    transition = cpu._task
    assert transition is not None
    await transition
    retry = cpu._retry_task
    assert retry is not None
    async with asyncio.timeout(0.15):
        await cpu.close()
    assert retry.done()
    assert transition.done()
    assert modes == ["performance", "powersave", "ondemand"]
    cpu.set_power_saving(False)
    await cpu.close()
    assert modes == ["performance", "powersave", "ondemand"]


@pytest.mark.asyncio
async def test_close_interrupts_inflight_write_and_bounds_hung_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(performance, "CPU_SETTER_TIMEOUT", 0.01)
    idle_started = asyncio.Event()
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)
        if mode != "performance":
            idle_started.set()
            await asyncio.Event().wait()

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)
    await idle_started.wait()
    transition = cpu._task
    assert transition is not None
    async with asyncio.timeout(0.15):
        await cpu.close()
    assert transition.done()
    assert cpu._retry_task is None
    assert cpu._close_task is not None and cpu._close_task.done()
    assert modes == ["performance", "powersave", "ondemand"]
    assert cpu._applied is None


@pytest.mark.asyncio
async def test_cancelled_close_joins_ondemand_restore() -> None:
    restoring = asyncio.Event()
    release = asyncio.Event()
    modes: list[str] = []

    async def setter(mode: str) -> None:
        if mode == "ondemand":
            restoring.set()
            await release.wait()
        modes.append(mode)

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    task = asyncio.create_task(cpu.close())
    await restoring.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert modes == ["performance", "ondemand"]
    assert cpu._close_task is not None and cpu._close_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellations", [2, 5])
async def test_repeated_close_cancellation_waits_for_held_restore(cancellations: int) -> None:
    restoring = asyncio.Event()
    release = asyncio.Event()
    actual = "performance"

    async def setter(mode: str) -> None:
        nonlocal actual
        if mode == "ondemand":
            restoring.set()
            await release.wait()
        actual = mode

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    task = asyncio.create_task(cpu.close())
    await restoring.wait()
    exited_before_restore: list[bool] = []
    for _ in range(cancellations):
        task.cancel()
        await asyncio.sleep(0)
        exited_before_restore.append(task.done())
    assert actual == "performance"
    assert cpu._close_task is not None and not cpu._close_task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await cpu._close_task
    assert not any(exited_before_restore)
    assert actual == "ondemand"
    assert cpu._close_task.done()


@pytest.mark.asyncio
async def test_rapid_mode_changes_coalesce_to_latest_request() -> None:
    idle_started = asyncio.Event()
    release = asyncio.Event()
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)
        if mode == "powersave":
            idle_started.set()
            await release.wait()

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)
    await idle_started.wait()
    transition = cpu._task
    for _ in range(50):
        cpu.set_power_saving(False)
        cpu.set_power_saving(True)
        assert cpu._task is transition
    cpu.set_power_saving(False)
    release.set()
    await cpu.start()
    assert modes == ["performance", "powersave", "performance"]
    await cpu.close()


@pytest.mark.asyncio
async def test_cancelled_photo_job_releases_locked_boost() -> None:
    modes: list[str] = []
    started = asyncio.Event()

    async def setter(mode: str) -> None:
        modes.append(mode)

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)

    async def job() -> None:
        async with cpu.boost():
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(job())
    await started.wait()
    assert modes[-1] == "performance"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert modes[-1] == "powersave"
    await cpu.close()


@pytest.mark.asyncio
async def test_wake_during_idle_helper_is_not_lost() -> None:
    modes: list[str] = []
    idle_started = asyncio.Event()
    release_idle = asyncio.Event()

    async def setter(mode: str) -> None:
        modes.append(mode)
        if mode == "powersave":
            idle_started.set()
            await release_idle.wait()

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    cpu.set_power_saving(True)
    await idle_started.wait()
    cpu.set_power_saving(False)
    release_idle.set()
    await cpu.start()
    assert modes == ["performance", "powersave", "performance"]
    await cpu.close()


@pytest.mark.asyncio
async def test_cpu_helper_failure_does_not_abort_photo_job(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def setter(mode: str) -> None:
        raise OSError("helper unavailable")

    cpu = CpuPerformanceController(setter)
    await cpu.start()
    async with cpu.boost():
        pass
    await cpu.close()
    assert caplog.text.count("power.cpu_mode_failed") == 1


@pytest.mark.asyncio
async def test_ui_lock_and_wake_drive_cpu_policy_without_display_hardware() -> None:
    modes: list[str] = []

    async def setter(mode: str) -> None:
        modes.append(mode)

    class Display:
        def render(self, snapshot: UiSnapshot) -> None:
            pass

        def set_idle_stage(self, stage: str) -> None:
            pass

        def close(self) -> None:
            pass

    cpu = CpuPerformanceController(setter)
    ui = BridgeUi(
        BridgeConfig(ui=UiConfig(unlock_requires_three_presses=False)),
        display=Display(),
        input_device=NullInput(),
        cpu_performance=cpu,
        config_path=Path("/unused"),
    )
    await cpu.start()
    ui._lock_screen()
    await cpu.start()
    assert modes[-1] == "powersave"
    # Background activity cannot lift a manual lock or change its CPU policy.
    ui._apply_idle_stage(IdleStage.ACTIVE)
    await cpu.start()
    assert modes[-1] == "powersave"
    await ui._handle_action(UiAction.SELECT)
    await cpu.start()
    assert modes[-1] == "performance"
    ui._apply_idle_stage(IdleStage.DIM)
    await cpu.start()
    assert modes[-1] == "performance"
    ui._apply_idle_stage(IdleStage.SCREEN_OFF)
    await cpu.start()
    assert modes[-1] == "powersave"
    await cpu.close()
