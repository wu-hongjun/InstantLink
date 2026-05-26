from __future__ import annotations

from instantlink_bridge.manager.health import (
    PLAN_030_HEALTH_GATE_SPECS,
    BridgeHealthGate,
    HealthCheckContext,
    HealthGateResult,
    HealthGateStatus,
    HealthProbe,
    UpdateHealthAction,
    decide_boot_recovery,
    decide_mark_good,
    run_health_checks,
)
from instantlink_bridge.manager.release_slots import RollbackState, UpdateStateStatus


def test_all_pass_health_marks_pending_update_good() -> None:
    state = _pending_state()
    health = run_health_checks(
        _passing_probes(),
        context=HealthCheckContext(expected_version="0.2.0", now=1000.0),
    )

    decision = decide_mark_good(state, health, now="2026-05-26T15:31:00Z")

    assert health.all_required_gates_passed
    assert health.checked_at == 1000.0
    assert health.expected_version == "0.2.0"
    assert decision.action is UpdateHealthAction.MARK_GOOD
    assert not decision.rollback_recommended
    assert decision.reason is None
    assert decision.state is not None
    assert decision.state.status is UpdateStateStatus.GOOD
    assert decision.state.active_release == state.active_release
    assert decision.state.target_release is None
    assert decision.state.updated_at == "2026-05-26T15:31:00Z"


def test_failed_required_gate_recommends_rollback_with_reason() -> None:
    probes = _passing_probes()
    probes[BridgeHealthGate.FTP_LISTENER_READY] = _constant_probe(
        HealthGateResult.failed(BridgeHealthGate.FTP_LISTENER_READY, "port_closed")
    )
    health = run_health_checks(probes)

    decision = decide_mark_good(_pending_state(), health)

    assert not health.all_required_gates_passed
    assert decision.action is UpdateHealthAction.ROLLBACK_RECOMMENDED
    assert decision.rollback_recommended
    assert decision.state is None
    assert decision.reason == "health_gate_failed:ftp_listener_ready:port_closed"


def test_optional_printer_offline_does_not_block_mark_good() -> None:
    probes = _passing_probes()
    probes[BridgeHealthGate.PRINTER_STATUS_LOOP_ALIVE] = _constant_probe(
        HealthGateResult.skipped(
            BridgeHealthGate.PRINTER_STATUS_LOOP_ALIVE,
            "printer_offline",
            required=False,
        )
    )
    health = run_health_checks(probes)

    decision = decide_mark_good(_pending_state(), health)
    printer = health.result_for(BridgeHealthGate.PRINTER_STATUS_LOOP_ALIVE)

    assert printer is not None
    assert printer.status is HealthGateStatus.SKIPPED
    assert not printer.required
    assert health.all_required_gates_passed
    assert decision.action is UpdateHealthAction.MARK_GOOD
    assert decision.state is not None
    assert decision.state.status is UpdateStateStatus.GOOD


def test_pending_verification_on_boot_prefers_rollback_without_passing_health() -> None:
    state = _pending_state()

    decision = decide_boot_recovery(state)

    assert decision.action is UpdateHealthAction.ROLLBACK_RECOMMENDED
    assert decision.rollback_recommended
    assert decision.state == state
    assert decision.reason == "pending_verification_after_boot"


def test_stale_lcd_heartbeat_fails_required_gate() -> None:
    probes = _passing_probes()
    probes[BridgeHealthGate.LCD_HEARTBEAT_FRESH_OR_DISABLED] = _constant_probe(
        HealthGateResult.failed(
            BridgeHealthGate.LCD_HEARTBEAT_FRESH_OR_DISABLED,
            "lcd_heartbeat_stale",
        )
    )
    health = run_health_checks(probes)

    decision = decide_mark_good(_pending_state(), health)

    assert health.result_for(BridgeHealthGate.LCD_HEARTBEAT_FRESH_OR_DISABLED) is not None
    assert health.required_failures == (
        HealthGateResult.failed(
            BridgeHealthGate.LCD_HEARTBEAT_FRESH_OR_DISABLED,
            "lcd_heartbeat_stale",
        ),
    )
    assert decision.action is UpdateHealthAction.ROLLBACK_RECOMMENDED
    assert (
        decision.reason
        == "health_gate_failed:lcd_heartbeat_fresh_or_disabled:lcd_heartbeat_stale"
    )


def _pending_state() -> RollbackState:
    return RollbackState.pending_verification(
        active_release="2026-05-26T153000Z-v0.2.0",
        previous_release="2026-05-24T153000Z-v0.1.5",
        now="2026-05-26T15:30:00Z",
    )


def _passing_probes() -> dict[BridgeHealthGate, HealthProbe]:
    return {
        spec.gate: _constant_probe(HealthGateResult.passed(spec.gate))
        for spec in PLAN_030_HEALTH_GATE_SPECS
    }


def _constant_probe(result: HealthGateResult) -> HealthProbe:
    def probe(_context: HealthCheckContext) -> HealthGateResult:
        return result

    return probe
