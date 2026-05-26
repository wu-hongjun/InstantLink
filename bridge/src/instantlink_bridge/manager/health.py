"""Health-gated rollback primitives for Bridge updates."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TypeAlias

from instantlink_bridge.manager.release_slots import RollbackState, UpdateStateStatus


class BridgeHealthGate(StrEnum):
    """Plan 030 health gates used before an update can be marked good."""

    MANAGER_API_RESPONDS = "manager_api_responds"
    RUNTIME_SERVICE_STABLE = "runtime_service_stable"
    VERSION_REPORTS_EXPECTED = "version_reports_expected"
    CONFIG_PARSES = "config_parses"
    LCD_HEARTBEAT_FRESH_OR_DISABLED = "lcd_heartbeat_fresh_or_disabled"
    FTP_LISTENER_READY = "ftp_listener_ready"
    NETWORK_MODE_TRUTHFUL = "network_mode_truthful"
    PRINTER_STATUS_LOOP_ALIVE = "printer_status_loop_alive"
    DISK_FLOOR = "disk_floor"
    NO_CRITICAL_STARTUP_EXCEPTION = "no_critical_startup_exception"


class HealthGateStatus(StrEnum):
    """Outcome for one health gate."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class UpdateHealthAction(StrEnum):
    """Decision produced from update health state."""

    NONE = "none"
    MARK_GOOD = "mark_good"
    ROLLBACK_RECOMMENDED = "rollback_recommended"


@dataclass(frozen=True, slots=True)
class HealthGateSpec:
    """Static policy for one Plan 030 health gate."""

    gate: BridgeHealthGate
    description: str
    required: bool = True
    may_be_optional: bool = False


@dataclass(frozen=True, slots=True)
class HealthGateResult:
    """Result reported by one injectable health probe."""

    gate: BridgeHealthGate
    status: HealthGateStatus
    required: bool = True
    reason: str | None = None
    message: str | None = None

    @classmethod
    def passed(
        cls,
        gate: BridgeHealthGate,
        *,
        required: bool = True,
        reason: str | None = None,
        message: str | None = None,
    ) -> HealthGateResult:
        return cls(
            gate=gate,
            status=HealthGateStatus.PASSED,
            required=required,
            reason=reason,
            message=message,
        )

    @classmethod
    def failed(
        cls,
        gate: BridgeHealthGate,
        reason: str,
        *,
        required: bool = True,
        message: str | None = None,
    ) -> HealthGateResult:
        return cls(
            gate=gate,
            status=HealthGateStatus.FAILED,
            required=required,
            reason=reason,
            message=message,
        )

    @classmethod
    def skipped(
        cls,
        gate: BridgeHealthGate,
        reason: str,
        *,
        required: bool = False,
        message: str | None = None,
    ) -> HealthGateResult:
        return cls(
            gate=gate,
            status=HealthGateStatus.SKIPPED,
            required=required,
            reason=reason,
            message=message,
        )

    @property
    def is_required_failure(self) -> bool:
        """Return whether this result blocks marking the update good."""

        return self.required and self.status is not HealthGateStatus.PASSED


@dataclass(frozen=True, slots=True)
class HealthCheckContext:
    """Context shared with health probes.

    Probes are intentionally injected; this module does not call systemd, network sockets,
    hardware, or journals directly.
    """

    expected_version: str | None = None
    selected_network_mode: str | None = None
    now: float | None = None


HealthProbe: TypeAlias = Callable[[HealthCheckContext], HealthGateResult]


@dataclass(frozen=True, slots=True)
class BridgeHealthResult:
    """Aggregated result for a full Bridge update health check."""

    gate_results: tuple[HealthGateResult, ...]
    gate_specs: tuple[HealthGateSpec, ...] = ()
    checked_at: float | None = None
    expected_version: str | None = None

    def __post_init__(self) -> None:
        if not self.gate_specs:
            object.__setattr__(self, "gate_specs", PLAN_030_HEALTH_GATE_SPECS)

    @property
    def required_failures(self) -> tuple[HealthGateResult, ...]:
        """Return supplied gate results that block mark-good."""

        return tuple(result for result in self.gate_results if result.is_required_failure)

    @property
    def missing_required_gates(self) -> tuple[BridgeHealthGate, ...]:
        """Return required gates with no result."""

        present = {result.gate for result in self.gate_results}
        return tuple(
            spec.gate
            for spec in self.gate_specs
            if spec.required and spec.gate not in present
        )

    @property
    def all_required_gates_passed(self) -> bool:
        """Return whether every required gate is present and passing."""

        return self.blocking_reason is None

    @property
    def blocking_reason(self) -> str | None:
        """Return a rollback-safe reason for the first required health failure."""

        result_by_gate = {result.gate: result for result in self.gate_results}
        for spec in self.gate_specs:
            result = result_by_gate.get(spec.gate)
            if result is None:
                if spec.required:
                    return f"health_gate_missing:{spec.gate.value}"
                continue
            if result.is_required_failure:
                reason = result.reason or result.status.value
                return f"health_gate_failed:{result.gate.value}:{reason}"
        return None

    def result_for(self, gate: BridgeHealthGate) -> HealthGateResult | None:
        """Return the first result for a gate, if present."""

        for result in self.gate_results:
            if result.gate is gate:
                return result
        return None


@dataclass(frozen=True, slots=True)
class MarkGoodDecision:
    """Decision for marking a pending update good after health checks."""

    action: UpdateHealthAction
    health: BridgeHealthResult
    state: RollbackState | None = None
    reason: str | None = None

    @property
    def rollback_recommended(self) -> bool:
        """Return whether the caller should roll back instead of marking good."""

        return self.action is UpdateHealthAction.ROLLBACK_RECOMMENDED


@dataclass(frozen=True, slots=True)
class BootRecoveryDecision:
    """Decision for pending update state discovered during boot."""

    action: UpdateHealthAction
    state: RollbackState | None = None
    health: BridgeHealthResult | None = None
    reason: str | None = None

    @property
    def rollback_recommended(self) -> bool:
        """Return whether boot recovery should restore the previous release."""

        return self.action is UpdateHealthAction.ROLLBACK_RECOMMENDED


PLAN_030_HEALTH_GATE_SPECS: tuple[HealthGateSpec, ...] = (
    HealthGateSpec(
        BridgeHealthGate.MANAGER_API_RESPONDS,
        "instantlink-bridge-manager.service responds to /v1/status",
    ),
    HealthGateSpec(
        BridgeHealthGate.RUNTIME_SERVICE_STABLE,
        "instantlink-bridge.service is active for the stability window without restart",
    ),
    HealthGateSpec(
        BridgeHealthGate.VERSION_REPORTS_EXPECTED,
        "instantlink-bridge --version reports the expected installed version",
    ),
    HealthGateSpec(
        BridgeHealthGate.CONFIG_PARSES,
        "config parses and configured paths are writable",
    ),
    HealthGateSpec(
        BridgeHealthGate.LCD_HEARTBEAT_FRESH_OR_DISABLED,
        "LCD render loop heartbeat is fresh or display is disabled",
    ),
    HealthGateSpec(
        BridgeHealthGate.FTP_LISTENER_READY,
        "FTP listener is bound on the active upload mode address and port",
    ),
    HealthGateSpec(
        BridgeHealthGate.NETWORK_MODE_TRUTHFUL,
        "network status matches the selected receive mode",
    ),
    HealthGateSpec(
        BridgeHealthGate.PRINTER_STATUS_LOOP_ALIVE,
        "printer status loop is alive and non-blocking",
        may_be_optional=True,
    ),
    HealthGateSpec(
        BridgeHealthGate.DISK_FLOOR,
        "disk free space remains above the configured floor",
    ),
    HealthGateSpec(
        BridgeHealthGate.NO_CRITICAL_STARTUP_EXCEPTION,
        "no critical startup exception is present after the new service start",
    ),
)


def run_health_checks(
    probes: Mapping[BridgeHealthGate, HealthProbe],
    *,
    context: HealthCheckContext | None = None,
    gate_specs: Iterable[HealthGateSpec] = PLAN_030_HEALTH_GATE_SPECS,
) -> BridgeHealthResult:
    """Run health probes using only the supplied injectable probe callables."""

    check_context = context or HealthCheckContext()
    specs = tuple(gate_specs)
    results: list[HealthGateResult] = []
    for spec in specs:
        probe = probes.get(spec.gate)
        if probe is None:
            results.append(
                HealthGateResult.failed(
                    spec.gate,
                    "probe_missing",
                    required=spec.required,
                )
            )
            continue
        try:
            result = probe(check_context)
        except Exception as exc:
            results.append(
                HealthGateResult.failed(
                    spec.gate,
                    f"probe_exception:{type(exc).__name__}",
                    required=spec.required,
                )
            )
            continue
        results.append(_apply_gate_spec(spec, result))
    return BridgeHealthResult(
        gate_results=tuple(results),
        gate_specs=specs,
        checked_at=check_context.now,
        expected_version=check_context.expected_version,
    )


def decide_mark_good(
    state: RollbackState,
    health: BridgeHealthResult,
    *,
    now: str | None = None,
) -> MarkGoodDecision:
    """Return whether health permits marking the pending update good."""

    reason = health.blocking_reason
    if reason is not None:
        return MarkGoodDecision(
            action=UpdateHealthAction.ROLLBACK_RECOMMENDED,
            health=health,
            reason=reason,
        )
    return MarkGoodDecision(
        action=UpdateHealthAction.MARK_GOOD,
        health=health,
        state=state.mark_good(now=now),
    )


def decide_boot_recovery(
    state: RollbackState | None,
    *,
    health: BridgeHealthResult | None = None,
    now: str | None = None,
) -> BootRecoveryDecision:
    """Return the safe boot-time action for persisted update state."""

    if state is None or state.status is not UpdateStateStatus.PENDING_VERIFICATION:
        return BootRecoveryDecision(action=UpdateHealthAction.NONE, state=state, health=health)
    if health is not None and health.all_required_gates_passed:
        return BootRecoveryDecision(
            action=UpdateHealthAction.MARK_GOOD,
            state=state.mark_good(now=now),
            health=health,
        )
    return BootRecoveryDecision(
        action=UpdateHealthAction.ROLLBACK_RECOMMENDED,
        state=state,
        health=health,
        reason=health.blocking_reason if health is not None else "pending_verification_after_boot",
    )


def _apply_gate_spec(spec: HealthGateSpec, result: HealthGateResult) -> HealthGateResult:
    if result.gate is not spec.gate:
        return HealthGateResult.failed(
            spec.gate,
            f"probe_returned_wrong_gate:{result.gate.value}",
            required=spec.required,
        )
    required = result.required if spec.may_be_optional else spec.required
    return replace(result, required=required)
