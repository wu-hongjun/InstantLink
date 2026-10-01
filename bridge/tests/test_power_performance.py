from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from instantlink_bridge.config import BridgeConfig, UiConfig
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
