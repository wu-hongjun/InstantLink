"""Battery and idle power-management policy."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Protocol

from instantlink_bridge.power.pisugar import BatteryState
from instantlink_bridge.power.x306 import X306BatteryClient

LOGGER = logging.getLogger(__name__)


class Clock(Protocol):
    """Monotonic clock used by the power policy."""

    def monotonic(self) -> float:
        """Return monotonic seconds."""


class MonotonicClock:
    """Default monotonic clock implementation."""

    def monotonic(self) -> float:
        """Return `time.monotonic()`."""

        return time.monotonic()


class BatteryClient(Protocol):
    """Battery provider contract used by the monitor."""

    def read_battery_state(self) -> BatteryState:
        """Return the latest battery snapshot."""


class BatteryAlert(StrEnum):
    """Battery alert level derived from a battery snapshot."""

    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class IdleStage(StrEnum):
    """Idle stage derived from the time since the last activity event."""

    ACTIVE = "active"
    DIM = "dim"
    SCREEN_OFF = "screen_off"
    DEEP_IDLE = "deep_idle"
    POWEROFF = "poweroff"


class PowerEventKind(StrEnum):
    """Power monitor event kinds for parent orchestrator integration."""

    BATTERY_UPDATE = "battery_update"
    BATTERY_ALERT_CHANGED = "battery_alert_changed"
    IDLE_STAGE_CHANGED = "idle_stage_changed"
    SHUTDOWN_REQUESTED = "shutdown_requested"


class ShutdownReason(StrEnum):
    """Why the power monitor requested shutdown."""

    LOW_BATTERY = "low_battery"
    IDLE_TIMEOUT = "idle_timeout"


@dataclass(frozen=True, slots=True)
class BatteryPolicy:
    """Battery polling and threshold policy."""

    poll_interval_s: float = 30.0
    warning_threshold_percent: float = 20.0
    safe_shutdown_threshold_percent: float = 10.0

    def __post_init__(self) -> None:
        _require_positive_finite(self.poll_interval_s, "poll_interval_s")
        _require_percent(self.warning_threshold_percent, "warning_threshold_percent")
        _require_percent(
            self.safe_shutdown_threshold_percent,
            "safe_shutdown_threshold_percent",
        )
        if self.safe_shutdown_threshold_percent > self.warning_threshold_percent:
            raise ValueError("safe_shutdown_threshold_percent must be <= warning_threshold_percent")


@dataclass(frozen=True, slots=True)
class IdlePolicy:
    """Idle timeout policy in seconds since last activity."""

    dim_after_s: float = 30.0
    screen_off_after_s: float = 90.0
    deep_idle_after_s: float = 300.0
    poweroff_after_s: float = 600.0
    poweroff_enabled: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("dim_after_s", self.dim_after_s),
            ("screen_off_after_s", self.screen_off_after_s),
            ("deep_idle_after_s", self.deep_idle_after_s),
            ("poweroff_after_s", self.poweroff_after_s),
        ):
            _require_positive_finite(value, name)
        if not (
            self.dim_after_s
            < self.screen_off_after_s
            < self.deep_idle_after_s
            < self.poweroff_after_s
        ):
            raise ValueError("idle thresholds must be strictly increasing")

    def stage_for_idle(self, idle_seconds: float) -> IdleStage:
        """Return the idle stage for elapsed idle seconds."""

        if self.poweroff_enabled and idle_seconds >= self.poweroff_after_s:
            return IdleStage.POWEROFF
        if idle_seconds >= self.deep_idle_after_s:
            return IdleStage.DEEP_IDLE
        if idle_seconds >= self.screen_off_after_s:
            return IdleStage.SCREEN_OFF
        if idle_seconds >= self.dim_after_s:
            return IdleStage.DIM
        return IdleStage.ACTIVE

    def transition_thresholds(self) -> tuple[float, ...]:
        """Return transition thresholds in increasing order."""

        return (
            self.dim_after_s,
            self.screen_off_after_s,
            self.deep_idle_after_s,
            *(() if not self.poweroff_enabled else (self.poweroff_after_s,)),
        )


@dataclass(frozen=True, slots=True)
class PowerPolicy:
    """Combined battery and idle policy."""

    battery: BatteryPolicy = field(default_factory=BatteryPolicy)
    idle: IdlePolicy = field(default_factory=IdlePolicy)


@dataclass(frozen=True, slots=True)
class BatteryEvaluation:
    """Battery policy result for a single snapshot."""

    state: BatteryState
    alert: BatteryAlert
    requires_shutdown: bool


@dataclass(frozen=True, slots=True)
class IdleState:
    """Current idle state."""

    stage: IdleStage
    idle_seconds: float
    last_activity_monotonic: float


@dataclass(frozen=True, slots=True)
class IdleTransition:
    """A change in idle stage."""

    previous_stage: IdleStage
    current_stage: IdleStage
    state: IdleState


@dataclass(frozen=True, slots=True)
class PowerEvent:
    """Typed event emitted by `PowerMonitor`."""

    kind: PowerEventKind
    created_at_monotonic: float
    battery: BatteryState | None = None
    battery_alert: BatteryAlert | None = None
    idle_state: IdleState | None = None
    shutdown_reason: ShutdownReason | None = None


PowerEventHandler = Callable[[PowerEvent], Awaitable[None] | None]
ShutdownCallable = Callable[[], Awaitable[None] | None]


class IdleTimer:
    """Pure idle timer state machine with an injectable clock."""

    def __init__(
        self,
        *,
        policy: IdlePolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._policy = policy if policy is not None else IdlePolicy()
        self._clock = clock if clock is not None else MonotonicClock()
        self._last_activity_monotonic = self._clock.monotonic()
        self._stage = IdleStage.ACTIVE

    @property
    def policy(self) -> IdlePolicy:
        """Return the idle policy."""

        return self._policy

    @property
    def stage(self) -> IdleStage:
        """Return the current idle stage without polling the clock."""

        return self._stage

    def current_state(self) -> IdleState:
        """Return the current idle state."""

        now = self._clock.monotonic()
        return IdleState(
            stage=self._stage,
            idle_seconds=max(0.0, now - self._last_activity_monotonic),
            last_activity_monotonic=self._last_activity_monotonic,
        )

    def poll(self) -> IdleTransition | None:
        """Advance the idle stage according to the current clock."""

        state = self.current_state()
        next_stage = self._policy.stage_for_idle(state.idle_seconds)
        if next_stage == self._stage:
            return None
        previous_stage = self._stage
        self._stage = next_stage
        return IdleTransition(
            previous_stage=previous_stage,
            current_stage=next_stage,
            state=IdleState(
                stage=next_stage,
                idle_seconds=state.idle_seconds,
                last_activity_monotonic=state.last_activity_monotonic,
            ),
        )

    def record_activity(self) -> IdleTransition | None:
        """Reset idle timing after activity and wake to the active stage."""

        now = self._clock.monotonic()
        previous_stage = self._stage
        self._last_activity_monotonic = now
        self._stage = IdleStage.ACTIVE
        if previous_stage == IdleStage.ACTIVE:
            return None
        return IdleTransition(
            previous_stage=previous_stage,
            current_stage=IdleStage.ACTIVE,
            state=IdleState(
                stage=IdleStage.ACTIVE,
                idle_seconds=0.0,
                last_activity_monotonic=now,
            ),
        )

    def seconds_until_next_transition(self) -> float | None:
        """Return seconds until the next idle transition, or None after poweroff."""

        idle_seconds = self.current_state().idle_seconds
        for threshold in self._policy.transition_thresholds():
            if idle_seconds < threshold:
                return max(0.0, threshold - idle_seconds)
        return None


class PowerMonitor:
    """Async battery polling and idle policy coordinator."""

    def __init__(
        self,
        *,
        battery_client: BatteryClient | None = None,
        policy: PowerPolicy | None = None,
        clock: Clock | None = None,
        shutdown: ShutdownCallable | None = None,
        event_handler: PowerEventHandler | None = None,
    ) -> None:
        self._policy = policy if policy is not None else PowerPolicy()
        self._clock = clock if clock is not None else MonotonicClock()
        self._battery_client = battery_client if battery_client is not None else X306BatteryClient()
        self._shutdown = shutdown if shutdown is not None else _noop_shutdown
        self._event_handler = event_handler
        self._idle_timer = IdleTimer(policy=self._policy.idle, clock=self._clock)
        self._last_battery_alert: BatteryAlert | None = None
        self._shutdown_requested = False
        self._idle_reschedule_event: asyncio.Event | None = None

    @property
    def policy(self) -> PowerPolicy:
        """Return the configured power policy."""

        return self._policy

    @property
    def idle_timer(self) -> IdleTimer:
        """Return the idle timer for read-only inspection."""

        return self._idle_timer

    async def poll_battery_once(self) -> BatteryEvaluation:
        """Read battery state once, emit events, and request shutdown if required."""

        state = self._battery_client.read_battery_state()
        evaluation = evaluate_battery(state, self._policy.battery)
        await self._emit(
            PowerEvent(
                kind=PowerEventKind.BATTERY_UPDATE,
                created_at_monotonic=self._clock.monotonic(),
                battery=state,
                battery_alert=evaluation.alert,
            )
        )

        if evaluation.alert != self._last_battery_alert:
            self._last_battery_alert = evaluation.alert
            await self._emit(
                PowerEvent(
                    kind=PowerEventKind.BATTERY_ALERT_CHANGED,
                    created_at_monotonic=self._clock.monotonic(),
                    battery=state,
                    battery_alert=evaluation.alert,
                )
            )

        if evaluation.requires_shutdown:
            await self._request_shutdown(ShutdownReason.LOW_BATTERY, battery=state)
        return evaluation

    async def poll_idle_once(self) -> IdleState:
        """Advance idle state once and request shutdown at the poweroff stage."""

        transition = self._idle_timer.poll()
        state = self._idle_timer.current_state()
        if transition is not None:
            state = transition.state
            await self._emit(
                PowerEvent(
                    kind=PowerEventKind.IDLE_STAGE_CHANGED,
                    created_at_monotonic=self._clock.monotonic(),
                    idle_state=state,
                )
            )
        if state.stage == IdleStage.POWEROFF:
            await self._request_shutdown(ShutdownReason.IDLE_TIMEOUT, idle_state=state)
        return state

    async def record_activity(self) -> IdleState:
        """Reset idle state after GPIO, USB, FTP, or UI activity."""

        transition = self._idle_timer.record_activity()
        state = self._idle_timer.current_state()
        if self._idle_reschedule_event is not None:
            self._idle_reschedule_event.set()
        if transition is not None:
            state = transition.state
            await self._emit(
                PowerEvent(
                    kind=PowerEventKind.IDLE_STAGE_CHANGED,
                    created_at_monotonic=self._clock.monotonic(),
                    idle_state=state,
                )
            )
        return state

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run battery polling and idle timing until `stop_event` is set."""

        battery_task = asyncio.create_task(self.run_battery_polling(stop_event))
        idle_task = asyncio.create_task(self.run_idle_timer(stop_event))
        tasks = (battery_task, idle_task)
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def run_battery_polling(self, stop_event: asyncio.Event) -> None:
        """Poll the battery client on the configured interval."""

        while not stop_event.is_set():
            await self.poll_battery_once()
            await _wait_for_stop(stop_event, self._policy.battery.poll_interval_s)

    async def run_idle_timer(self, stop_event: asyncio.Event) -> None:
        """Poll idle transitions on their next deadline."""

        if self._idle_reschedule_event is None:
            self._idle_reschedule_event = asyncio.Event()
        while not stop_event.is_set():
            self._idle_reschedule_event.clear()
            await self.poll_idle_once()
            delay_s = self._idle_timer.seconds_until_next_transition()
            if delay_s is None:
                delay_s = self._policy.battery.poll_interval_s
            await _wait_for_stop_or_event(stop_event, self._idle_reschedule_event, delay_s)

    async def _request_shutdown(
        self,
        reason: ShutdownReason,
        *,
        battery: BatteryState | None = None,
        idle_state: IdleState | None = None,
    ) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        LOGGER.warning("power.shutdown_requested reason=%s", reason.value)
        await self._emit(
            PowerEvent(
                kind=PowerEventKind.SHUTDOWN_REQUESTED,
                created_at_monotonic=self._clock.monotonic(),
                battery=battery,
                battery_alert=(
                    evaluate_battery(battery, self._policy.battery).alert
                    if battery is not None
                    else None
                ),
                idle_state=idle_state,
                shutdown_reason=reason,
            )
        )
        try:
            await _await_if_needed(self._shutdown())
        except Exception:
            LOGGER.exception("power.shutdown_callable_failed reason=%s", reason.value)
            raise

    async def _emit(self, event: PowerEvent) -> None:
        if self._event_handler is None:
            return
        await _await_if_needed(self._event_handler(event))


def evaluate_battery(state: BatteryState, policy: BatteryPolicy | None = None) -> BatteryEvaluation:
    """Evaluate warning and safe-shutdown thresholds for one battery snapshot."""

    battery_policy = policy if policy is not None else BatteryPolicy()
    if not state.available:
        return BatteryEvaluation(
            state=state,
            alert=BatteryAlert.UNAVAILABLE,
            requires_shutdown=False,
        )
    if state.percentage is None:
        return BatteryEvaluation(
            state=state,
            alert=BatteryAlert.UNKNOWN,
            requires_shutdown=False,
        )
    if state.percentage <= battery_policy.safe_shutdown_threshold_percent:
        alert = BatteryAlert.CRITICAL
    elif state.percentage <= battery_policy.warning_threshold_percent:
        alert = BatteryAlert.WARNING
    else:
        alert = BatteryAlert.OK

    return BatteryEvaluation(
        state=state,
        alert=alert,
        requires_shutdown=alert == BatteryAlert.CRITICAL and state.external_power is not True,
    )


async def _wait_for_stop(stop_event: asyncio.Event, timeout_s: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout_s)
    except TimeoutError:
        return


async def _wait_for_stop_or_event(
    stop_event: asyncio.Event,
    event: asyncio.Event,
    timeout_s: float,
) -> None:
    stop_task = asyncio.create_task(stop_event.wait())
    event_task = asyncio.create_task(event.wait())
    tasks: set[asyncio.Task[bool]] = {stop_task, event_task}
    try:
        await asyncio.wait(tasks, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def _await_if_needed(awaitable: Awaitable[None] | None) -> None:
    if awaitable is not None:
        await awaitable


def _noop_shutdown() -> None:
    return None


def _require_positive_finite(value: float, name: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite value greater than 0")


def _require_percent(value: float, name: str) -> None:
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100")
