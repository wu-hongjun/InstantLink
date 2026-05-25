from __future__ import annotations

from instantlink_bridge.watchdog import _watchdog_interval_seconds


def test_watchdog_interval_uses_half_systemd_timeout() -> None:
    assert _watchdog_interval_seconds({"WATCHDOG_USEC": "30000000"}) == 15.0


def test_watchdog_interval_has_one_second_floor() -> None:
    assert _watchdog_interval_seconds({"WATCHDOG_USEC": "1000000"}) == 1.0


def test_watchdog_interval_ignores_missing_or_invalid_values() -> None:
    assert _watchdog_interval_seconds({}) is None
    assert _watchdog_interval_seconds({"WATCHDOG_USEC": "not-an-int"}) is None
