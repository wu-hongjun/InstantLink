from __future__ import annotations

from collections.abc import Sequence

import pytest

from instantlink_bridge.power.monitor import (
    BatteryAlert,
    BatteryPolicy,
    IdlePolicy,
    IdleStage,
    IdleTimer,
    PowerEvent,
    PowerEventKind,
    PowerMonitor,
    ShutdownReason,
    evaluate_battery,
)
from instantlink_bridge.power.pisugar import BatteryState
from instantlink_bridge.power.x306 import X306BatteryClient


def test_default_power_policy_matches_epic_thresholds() -> None:
    battery_policy = BatteryPolicy()

    assert battery_policy.poll_interval_s == 30.0
    assert battery_policy.warning_threshold_percent == 20.0
    assert battery_policy.safe_shutdown_threshold_percent == 10.0


def test_x306_backend_reports_no_software_battery_telemetry() -> None:
    state = X306BatteryClient().read_battery_state()

    assert not state.available
    assert state.model == "SupTronics X306 18650 UPS"
    assert state.percentage is None
    assert state.error is not None
    assert "no host telemetry" in state.error


def test_idle_timer_transitions_and_resets_on_activity() -> None:
    clock = FakeClock()
    timer = IdleTimer(clock=clock)

    clock.advance(29.0)
    assert timer.poll() is None
    assert timer.current_state().stage is IdleStage.ACTIVE

    clock.advance(1.0)
    transition = timer.poll()
    assert transition is not None
    assert transition.current_stage is IdleStage.DIM

    clock.advance(60.0)
    transition = timer.poll()
    assert transition is not None
    assert transition.current_stage is IdleStage.SCREEN_OFF

    transition = timer.record_activity()
    assert transition is not None
    assert transition.previous_stage is IdleStage.SCREEN_OFF
    assert transition.current_stage is IdleStage.ACTIVE
    assert timer.current_state().idle_seconds == 0.0

    clock.advance(300.0)
    transition = timer.poll()
    assert transition is not None
    assert transition.current_stage is IdleStage.DEEP_IDLE

    clock.advance(300.0)
    transition = timer.poll()
    assert transition is not None
    assert transition.current_stage is IdleStage.POWEROFF


def test_idle_timer_can_disable_poweroff_stage() -> None:
    clock = FakeClock()
    timer = IdleTimer(policy=IdlePolicy(poweroff_enabled=False), clock=clock)

    clock.advance(600.0)
    transition = timer.poll()

    assert transition is not None
    assert transition.current_stage is IdleStage.DEEP_IDLE
    assert timer.seconds_until_next_transition() is None


def test_battery_evaluation_applies_warning_and_shutdown_thresholds() -> None:
    assert evaluate_battery(BatteryState(available=True, percentage=50.0)).alert is BatteryAlert.OK
    assert (
        evaluate_battery(BatteryState(available=True, percentage=20.0)).alert
        is BatteryAlert.WARNING
    )

    critical = evaluate_battery(BatteryState(available=True, percentage=10.0))
    assert critical.alert is BatteryAlert.CRITICAL
    assert critical.requires_shutdown

    plugged_in = evaluate_battery(BatteryState(available=True, percentage=5.0, power_plugged=True))
    assert plugged_in.alert is BatteryAlert.CRITICAL
    assert plugged_in.requires_shutdown is False

    assert evaluate_battery(BatteryState.unavailable()).alert is BatteryAlert.UNAVAILABLE


@pytest.mark.asyncio
async def test_power_monitor_emits_warning_and_calls_injected_shutdown_once() -> None:
    clock = FakeClock()
    events: list[PowerEvent] = []
    shutdowns: list[float] = []

    def shutdown() -> None:
        shutdowns.append(clock.monotonic())

    monitor = PowerMonitor(
        battery_client=FakeBatteryClient(
            [
                BatteryState(available=True, percentage=20.0),
                BatteryState(available=True, percentage=10.0),
            ]
        ),
        clock=clock,
        shutdown=shutdown,
        event_handler=events.append,
    )

    warning = await monitor.poll_battery_once()
    critical = await monitor.poll_battery_once()
    repeated = await monitor.poll_battery_once()

    assert warning.alert is BatteryAlert.WARNING
    assert critical.alert is BatteryAlert.CRITICAL
    assert repeated.alert is BatteryAlert.CRITICAL
    shutdown_events = [event for event in events if event.kind is PowerEventKind.SHUTDOWN_REQUESTED]
    assert shutdowns == [0.0]
    assert len(shutdown_events) == 1
    assert shutdown_events[0].shutdown_reason is ShutdownReason.LOW_BATTERY


@pytest.mark.asyncio
async def test_power_monitor_idle_poweroff_uses_injected_shutdown() -> None:
    clock = FakeClock()
    events: list[PowerEvent] = []
    shutdowns: list[float] = []

    def shutdown() -> None:
        shutdowns.append(clock.monotonic())

    monitor = PowerMonitor(
        battery_client=FakeBatteryClient([BatteryState.unavailable()]),
        clock=clock,
        shutdown=shutdown,
        event_handler=events.append,
    )

    clock.advance(600.0)
    state = await monitor.poll_idle_once()

    assert state.stage is IdleStage.POWEROFF
    assert shutdowns == [600.0]
    assert events[-1].kind is PowerEventKind.SHUTDOWN_REQUESTED
    assert events[-1].shutdown_reason is ShutdownReason.IDLE_TIMEOUT


@pytest.mark.asyncio
async def test_power_monitor_record_activity_wakes_idle_stage() -> None:
    clock = FakeClock()
    events: list[PowerEvent] = []
    monitor = PowerMonitor(
        battery_client=FakeBatteryClient([BatteryState.unavailable()]),
        clock=clock,
        event_handler=events.append,
    )

    clock.advance(90.0)
    await monitor.poll_idle_once()
    state = await monitor.record_activity()

    assert state.stage is IdleStage.ACTIVE
    assert state.idle_seconds == 0.0
    assert events[-1].kind is PowerEventKind.IDLE_STAGE_CHANGED
    assert events[-1].idle_state is not None
    assert events[-1].idle_state.stage is IdleStage.ACTIVE


class FakeClock:
    def __init__(self) -> None:
        self._now = 0.0

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeBatteryClient:
    def __init__(self, states: Sequence[BatteryState]) -> None:
        self._states = list(states)
        self.calls = 0

    def read_battery_state(self) -> BatteryState:
        self.calls += 1
        if len(self._states) > 1:
            return self._states.pop(0)
        return self._states[0]
