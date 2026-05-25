from __future__ import annotations

from ipaddress import IPv4Interface
from pathlib import Path

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
