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


def test_bridge_waits_for_listening_bus_without_serializing_network_or_daemon() -> None:
    unit = read_unit("instantlink-bridge.service")
    after = unit_dependencies(unit, "After")
    wants = unit_dependencies(unit, "Wants")
    independent_services = {
        "bluetooth.service",
        "systemd-networkd.service",
        "dnsmasq.service",
        "NetworkManager.service",
    }

    # Requiring a listening socket retains the bus-connect guarantee while its
    # socket-activated daemon can initialize during Python's initial imports.
    assert "dbus.socket" in after & wants
    assert not after & (independent_services | {"dbus.service", "network-online.target"})
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
