from __future__ import annotations

import json
import subprocess
from ipaddress import IPv4Interface
from pathlib import Path

import pytest

from instantlink_bridge.net.addresses import (
    address_from_ip_json,
    addresses_from_ip_json,
    detect_link_carrier,
    ipv4_interfaces_from_ip_json,
)


def test_address_from_ip_json_extracts_first_non_host_ipv4() -> None:
    data = [
        {
            "ifname": "wlan0",
            "addr_info": [
                {
                    "family": "inet",
                    "local": "192.168.5.149",
                    "prefixlen": 22,
                    "scope": "global",
                },
            ],
        }
    ]

    assert address_from_ip_json(data) == "192.168.5.149"


def test_addresses_from_ip_json_extracts_all_non_host_ipv4_addresses() -> None:
    data = [
        {
            "ifname": "usb0",
            "addr_info": [
                {"family": "inet", "local": "169.254.10.20", "prefixlen": 16, "scope": "link"},
                {"family": "inet", "local": "192.168.7.1", "prefixlen": 24, "scope": "global"},
                {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"},
            ],
        }
    ]

    assert addresses_from_ip_json(data) == ["169.254.10.20", "192.168.7.1"]


def test_ipv4_interfaces_from_ip_json_keeps_prefix_lengths() -> None:
    data = [
        {
            "ifname": "wlan0",
            "addr_info": [
                {
                    "family": "inet",
                    "local": "192.168.5.149",
                    "prefixlen": 22,
                    "scope": "global",
                },
                {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"},
                {"family": "inet", "local": "not-an-ip", "prefixlen": 24, "scope": "global"},
            ],
        }
    ]

    assert ipv4_interfaces_from_ip_json(data) == [IPv4Interface("192.168.5.149/22")]


def test_address_from_ip_json_ignores_loopback_scope() -> None:
    data = [
        {
            "ifname": "lo",
            "addr_info": [
                {"family": "inet", "local": "127.0.0.1", "scope": "host"},
            ],
        }
    ]

    assert address_from_ip_json(data) is None


def test_detect_link_carrier_reads_sysfs_value(tmp_path: Path) -> None:
    carrier = tmp_path / "usb0" / "carrier"
    carrier.parent.mkdir()
    carrier.write_text("1\n", encoding="utf-8")

    assert detect_link_carrier(sys_class_net=tmp_path)


def test_detect_link_carrier_returns_false_when_missing(tmp_path: Path) -> None:
    assert not detect_link_carrier(sys_class_net=tmp_path)


@pytest.mark.parametrize("missing_wifi", [False, True])
def test_address_snapshot_uses_one_probe_and_keeps_prefixes_and_missing_interfaces(
    monkeypatch: pytest.MonkeyPatch, missing_wifi: bool
) -> None:
    from instantlink_bridge.net import addresses

    calls: list[list[str]] = []
    records = [
        {
            "ifname": "usb0",
            "addr_info": [{"local": "192.168.7.1", "prefixlen": 24, "scope": "global"}],
        },
        {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8, "scope": "host"}]},
    ]
    if not missing_wifi:
        records.append(
            {
                "ifname": "wlan0",
                "addr_info": [
                    {"local": "192.168.8.1", "prefixlen": 24, "scope": "global"},
                    {"local": "10.42.5.2", "prefixlen": 22, "scope": "global"},
                    {"local": "bad", "prefixlen": 24, "scope": "global"},
                ],
            }
        )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["timeout"] == 1.5
        return subprocess.CompletedProcess(command, 0, json.dumps(records))

    monkeypatch.setattr(addresses.subprocess, "run", run)
    result = addresses.detect_ipv4_interfaces_by_interface(("wlan0", "usb0"))
    assert calls == [["ip", "-j", "-4", "addr", "show"]]
    assert result["usb0"] == [IPv4Interface("192.168.7.1/24")]
    assert result["wlan0"] == (
        [] if missing_wifi else [IPv4Interface("192.168.8.1/24"), IPv4Interface("10.42.5.2/22")]
    )


@pytest.mark.parametrize("failure", ["timeout", "missing", "bad_json", "failed"])
def test_address_snapshot_failure_is_safe_and_does_not_retry_per_interface(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from instantlink_bridge.net import addresses

    calls = 0

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1.5)
        if failure == "missing":
            raise FileNotFoundError("ip")
        return subprocess.CompletedProcess(command, 1 if failure == "failed" else 0, "bad")

    monkeypatch.setattr(addresses.subprocess, "run", run)
    assert addresses.detect_ipv4_interfaces_by_interface(("wlan0", "usb0")) == {
        "wlan0": [],
        "usb0": [],
    }
    assert calls == 1


@pytest.mark.parametrize("flags", [["BROADCAST", "MULTICAST"], []])
def test_address_snapshot_excludes_admin_down_interface_with_retained_ip(
    monkeypatch: pytest.MonkeyPatch, flags: list[str]
) -> None:
    from instantlink_bridge.net import addresses

    records = [
        {
            "ifname": "wlan0",
            "flags": flags,
            "operstate": "DOWN",
            "addr_info": [{"local": "192.168.8.1", "prefixlen": 24}],
        },
        {
            "ifname": "usb0",
            "flags": ["UP"],
            "addr_info": [{"local": "192.168.7.1", "prefixlen": 24}],
        },
    ]
    monkeypatch.setattr(
        addresses.subprocess,
        "run",
        lambda command, **_kw: subprocess.CompletedProcess(command, 0, json.dumps(records)),
    )
    result = addresses.detect_ipv4_interfaces_by_interface(("wlan0", "usb0"))
    assert result["wlan0"] == []
    assert result["usb0"] == [IPv4Interface("192.168.7.1/24")]


@pytest.mark.parametrize("operstate", ["DORMANT", "UNKNOWN", "UP"])
def test_address_snapshot_keeps_admin_up_interface_without_carrier_requirement(
    monkeypatch: pytest.MonkeyPatch, operstate: str
) -> None:
    from instantlink_bridge.net import addresses

    records = [
        {
            "ifname": "wlan0",
            "flags": ["BROADCAST", "MULTICAST", "UP"],
            "operstate": operstate,
            "addr_info": [{"local": "192.168.8.1", "prefixlen": 24}],
        }
    ]
    monkeypatch.setattr(
        addresses.subprocess,
        "run",
        lambda command, **_kw: subprocess.CompletedProcess(command, 0, json.dumps(records)),
    )
    assert addresses.detect_ipv4_interfaces_by_interface(("wlan0",))["wlan0"] == [
        IPv4Interface("192.168.8.1/24")
    ]
