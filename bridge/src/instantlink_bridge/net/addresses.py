"""Local network address detection."""

from __future__ import annotations

import json
import logging
import subprocess
from ipaddress import IPv4Interface
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def detect_ipv4_for_interface(interface: str = "wlan0") -> str | None:
    """Return the first IPv4 address assigned to an interface."""

    addresses = detect_ipv4_addresses_for_interface(interface)
    return addresses[0] if addresses else None


def detect_ipv4_addresses_for_interface(interface: str = "wlan0") -> list[str]:
    """Return non-host IPv4 addresses assigned to an interface."""

    return [str(address.ip) for address in detect_ipv4_interfaces_for_interface(interface)]


def detect_ipv4_interfaces_for_interface(interface: str = "wlan0") -> list[IPv4Interface]:
    """Return non-host IPv4 interface addresses assigned to an interface."""

    try:
        result = subprocess.run(
            ["ip", "-j", "-4", "addr", "show", "dev", interface],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        LOGGER.debug("network.ip_lookup_failed interface=%s", interface, exc_info=True)
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        LOGGER.debug("network.ip_lookup_invalid_json interface=%s", interface)
        return []
    return ipv4_interfaces_from_ip_json(data)


def address_from_ip_json(data: object) -> str | None:
    """Extract the first global IPv4 address from `ip -j -4 addr` JSON."""

    addresses = addresses_from_ip_json(data)
    return addresses[0] if addresses else None


def addresses_from_ip_json(data: object) -> list[str]:
    """Extract all non-host IPv4 addresses from `ip -j -4 addr` JSON."""

    return [str(address.ip) for address in ipv4_interfaces_from_ip_json(data)]


def ipv4_interfaces_from_ip_json(data: object) -> list[IPv4Interface]:
    """Extract all non-host IPv4 interface addresses from `ip -j -4 addr` JSON."""

    if not isinstance(data, list):
        return []
    addresses: list[IPv4Interface] = []
    for interface in data:
        if not isinstance(interface, dict):
            continue
        for address in _addr_info(interface):
            local = address.get("local")
            scope = str(address.get("scope", "global"))
            if not isinstance(local, str) or not local or scope == "host":
                continue
            prefix_len = _prefix_len(address)
            if prefix_len is None:
                continue
            try:
                addresses.append(IPv4Interface(f"{local}/{prefix_len}"))
            except ValueError:
                continue
    return addresses


def detect_link_carrier(
    interface: str = "usb0",
    *,
    sys_class_net: Path = Path("/sys/class/net"),
) -> bool:
    """Return whether a network interface reports link carrier."""

    try:
        return (sys_class_net / interface / "carrier").read_text(encoding="utf-8").strip() == "1"
    except OSError:
        LOGGER.debug("network.carrier_lookup_failed interface=%s", interface, exc_info=True)
        return False


def _addr_info(interface: dict[str, Any]) -> list[dict[str, Any]]:
    raw = interface.get("addr_info")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _prefix_len(address: dict[str, Any]) -> int | None:
    raw = address.get("prefixlen", 32)
    try:
        prefix_len = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= prefix_len <= 32:
        return prefix_len
    return None
