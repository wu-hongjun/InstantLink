"""Preserve independent startup and recovery paths in the installed units."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

SYSTEMD_ROOT = Path(__file__).resolve().parents[1] / "systemd"


def read_unit(name: str) -> ConfigParser:
    unit = ConfigParser(interpolation=None)
    unit.read(SYSTEMD_ROOT / name, encoding="utf-8")
    return unit


def unit_dependencies(unit: ConfigParser, field: str) -> set[str]:
    return set(unit.get("Unit", field, fallback="").split())


def test_bridge_keeps_bus_daemon_ordering_without_serializing_network() -> None:
    unit = read_unit("instantlink-bridge.service")
    after = unit_dependencies(unit, "After")
    wants = unit_dependencies(unit, "Wants")
    independent_services = {
        "bluetooth.service",
        "systemd-networkd.service",
        "dnsmasq.service",
        "NetworkManager.service",
    }

    # The daemon must start first and stop after Bridge cleanup. Ordering only
    # against its socket loses that reverse shutdown dependency (plan 098).
    assert "dbus.service" in after
    assert not after & (independent_services | {"network-online.target"})
    assert independent_services <= wants
    # Retain systemd's sysinit/basic/shutdown ordering and real app readiness.
    assert unit.getboolean("Unit", "DefaultDependencies", fallback=True)
    assert unit["Service"]["Type"] == "notify"
    assert unit["Service"]["WatchdogSec"] == "30"


def test_manager_recovery_does_not_wait_for_or_restart_the_bridge() -> None:
    bridge = read_unit("instantlink-bridge.service")
    manager = read_unit("instantlink-bridge-manager.service")
    for field in ("After", "Before", "Requires", "Wants", "BindsTo", "PartOf"):
        # A Bridge that fails before READY must not hold the rescue API behind
        # its startup timeout. Manager operations explicitly control restarts.
        assert "instantlink-bridge.service" not in unit_dependencies(manager, field)
        assert "instantlink-bridge-manager.service" not in unit_dependencies(bridge, field)
