from __future__ import annotations

import socket
import struct
from ipaddress import IPv4Interface

import pytest

from instantlink_bridge.net import addresses
from instantlink_bridge.net import linux_snapshot as native


def message(kind: int, body: bytes = b"", *, sequence: int = 1, flags: int = 0) -> bytes:
    raw = struct.pack("=IHHII", 16 + len(body), kind, flags, sequence, 77) + body
    return raw + b"\0" * (-len(raw) % 4)


def attribute(kind: int, value: bytes) -> bytes:
    raw = struct.pack("=HH", 4 + len(value), kind) + value
    return raw + b"\0" * (-len(raw) % 4)


def link(index: int, name: str, *, flags: int = 1, sequence: int = 2) -> bytes:
    return message(
        16,
        struct.pack("=BBHiII", 0, 0, 1, index, flags, 0) + attribute(3, name.encode() + b"\0"),
        sequence=sequence,
    )


def address(index: int, value: str, *, prefix: int = 24, scope: int = 0) -> bytes:
    return message(
        20,
        struct.pack("=BBBBI", socket.AF_INET, prefix, 0, scope, index)
        + attribute(2, socket.inet_aton(value)),
    )


class FakeSocket:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = replies
        self.requests: list[bytes] = []
        self.timeouts: list[float] = []
        self.closed = False
        self.flags = 0
        self.source = (0, 0)
        self.error: OSError | None = None

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def bind(self, value: tuple[int, int]) -> None:
        assert value == (0, 0)

    def getsockname(self) -> tuple[int, int]:
        return (77, 0)

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def send(self, value: bytes) -> int:
        self.requests.append(value)
        return len(value)

    def recvmsg(self, size: int) -> tuple[bytes, list[object], int, tuple[int, int]]:
        assert size == 65536
        if self.error is not None:
            raise self.error
        return (self.replies.pop(0), [], self.flags, self.source)


def install_socket(monkeypatch: pytest.MonkeyPatch, fake: FakeSocket) -> None:
    monkeypatch.setattr(native.sys, "platform", "linux")
    monkeypatch.setattr(native.socket, "AF_NETLINK", 16, raising=False)
    monkeypatch.setattr(native.socket, "NETLINK_ROUTE", 0, raising=False)
    monkeypatch.setattr(native.socket, "socket", lambda *_args: fake)


def healthy_replies() -> list[bytes]:
    return [
        address(5, "192.168.8.1")
        + address(5, "10.2.3.4", prefix=22)
        + address(6, "192.168.7.1")
        + address(5, "10.8.8.8", scope=254)
        + address(99, "10.4.5.6")
        + message(3),
        link(5, "wlan0") + link(6, "usb0") + message(3, sequence=2),
    ]


def test_fresh_dump_preserves_order_prefixes_scope_and_missing_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSocket(healthy_replies())
    install_socket(monkeypatch, fake)
    assert native.read_ipv4_interfaces(("wlan0", "usb0", "missing")) == {
        "wlan0": [IPv4Interface("192.168.8.1/24"), IPv4Interface("10.2.3.4/22")],
        "usb0": [IPv4Interface("192.168.7.1/24")],
        "missing": [],
    }
    assert fake.closed
    assert [struct.unpack_from("=H", request, 4)[0] for request in fake.requests] == [22, 18]
    assert [struct.unpack_from("=H", request, 6)[0] for request in fake.requests] == [0x301] * 2
    assert all(0 < timeout <= 0.25 for timeout in fake.timeouts)


@pytest.mark.parametrize("require_up", [False, True])
def test_admin_flags_sampled_last_and_per_interface_compatibility(
    monkeypatch: pytest.MonkeyPatch, require_up: bool
) -> None:
    fake = FakeSocket(
        [address(5, "192.168.8.1") + message(3), link(5, "wlan0", flags=0) + message(3, sequence=2)]
    )
    install_socket(monkeypatch, fake)
    assert native.read_ipv4_interfaces(("wlan0",), require_up=require_up)["wlan0"] == (
        [] if require_up else [IPv4Interface("192.168.8.1/24")]
    )


def test_point_to_point_local_wins_and_unknown_attributes_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = struct.pack("=BBBBI", socket.AF_INET, 32, 0, 0, 5)
    raw += attribute(1, socket.inet_aton("10.0.0.2"))
    raw += attribute(2, socket.inet_aton("10.0.0.1"))
    raw += attribute(400, b"future") + attribute(400, b"another")
    fake = FakeSocket([message(20, raw) + message(3), link(5, "usb0") + message(3, sequence=2)])
    install_socket(monkeypatch, fake)
    assert native.read_ipv4_interfaces(("usb0",))["usb0"] == [IPv4Interface("10.0.0.1/32")]


@pytest.mark.parametrize(
    "broken",
    [
        b"short",
        struct.pack("=IHHII", 15, 20, 0, 1, 77),
        struct.pack("=IHHII", 100, 20, 0, 1, 77),
        message(20, b"short"),
        message(20, struct.pack("=BBBBI", socket.AF_INET, 24, 0, 0, 5) + b"abc"),
        message(20, struct.pack("=BBBBI", socket.AF_INET, 24, 0, 0, 5) + struct.pack("=HH", 3, 2)),
        message(3, struct.pack("=i", -16)),
        message(3, b"x"),
        message(3, flags=0x10),
        message(20, flags=0x10),
        message(2, struct.pack("=i", 0)),
        message(4),
        message(3, sequence=99),
        message(3) + address(5, "10.0.0.1"),
        b"",
    ],
)
def test_failed_or_incomplete_dump_never_returns_partial_results(
    monkeypatch: pytest.MonkeyPatch, broken: bytes
) -> None:
    fake = FakeSocket(
        [address(5, "192.168.8.1"), broken, message(3), link(5, "wlan0") + message(3, sequence=2)]
    )
    install_socket(monkeypatch, fake)
    with pytest.raises(OSError):
        native.read_ipv4_interfaces(("wlan0",))
    assert fake.closed


@pytest.mark.parametrize("scope", [0, 253])
def test_address_without_local_uses_address_attribute(
    monkeypatch: pytest.MonkeyPatch, scope: int
) -> None:
    raw = struct.pack("=BBBBI", socket.AF_INET, 16, 0, scope, 5)
    raw += attribute(1, socket.inet_aton("169.254.1.2"))
    fake = FakeSocket([message(20, raw) + message(3), link(5, "usb0") + message(3, sequence=2)])
    install_socket(monkeypatch, fake)
    assert native.read_ipv4_interfaces(("usb0",))["usb0"] == [IPv4Interface("169.254.1.2/16")]


@pytest.mark.parametrize("failure", ["truncated", "sender", "group", "timeout", "overrun"])
def test_socket_failure_closes_and_discards_snapshot(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fake = FakeSocket(healthy_replies())
    install_socket(monkeypatch, fake)
    if failure == "truncated":
        fake.flags = socket.MSG_TRUNC
    elif failure == "sender":
        fake.source = (12, 0)
    elif failure == "group":
        fake.source = (0, 1)
    elif failure == "timeout":
        fake.error = TimeoutError("expired")
    else:
        fake.error = OSError(105, "ENOBUFS")
    with pytest.raises(OSError):
        native.read_ipv4_interfaces(("wlan0",))
    assert fake.closed


def test_deadline_shared_across_both_dumps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket(healthy_replies())
    install_socket(monkeypatch, fake)
    times = iter((1.0, 1.0, 1.0, 1.3))
    monkeypatch.setattr(native.time, "monotonic", lambda: next(times))
    with pytest.raises(OSError, match="deadline"):
        native.read_ipv4_interfaces(("wlan0",))
    assert len(fake.requests) == 1
    assert fake.closed


@pytest.mark.parametrize("per_interface", [False, True])
def test_native_success_does_not_spawn_ip(
    monkeypatch: pytest.MonkeyPatch, per_interface: bool
) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []

    def snapshot(
        names: tuple[str, ...], *, require_up: bool = True
    ) -> dict[str, list[IPv4Interface]]:
        calls.append((names, require_up))
        return {name: [IPv4Interface("192.168.8.1/24")] for name in names}

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("ip must not run on native success")

    monkeypatch.setattr(addresses, "read_ipv4_interfaces", snapshot)
    monkeypatch.setattr(addresses.subprocess, "run", forbidden)
    if per_interface:
        assert addresses.detect_ipv4_interfaces_for_interface("wlan0") == [
            IPv4Interface("192.168.8.1/24")
        ]
        assert calls == [(("wlan0",), False)]
    else:
        assert addresses.detect_ipv4_interfaces_by_interface(("wlan0", "wlan0")) == {
            "wlan0": [IPv4Interface("192.168.8.1/24")]
        }
        assert calls == [(("wlan0",), True)]


def test_unsupported_platform_does_not_open_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native.sys, "platform", "darwin")
    with pytest.raises(OSError, match="Linux"):
        native.read_ipv4_interfaces(("wlan0",))


@pytest.mark.parametrize("label", [b"usb0\0", b"usb0:camera\0", None])
def test_address_labels_preserve_aliases_and_optional_labels(
    monkeypatch: pytest.MonkeyPatch, label: bytes | None
) -> None:
    raw = struct.pack("=BBBBI", socket.AF_INET, 24, 0, 0, 5)
    raw += attribute(2, socket.inet_aton("192.168.7.1"))
    if label is not None:
        raw += attribute(3, label)
    fake = FakeSocket([message(20, raw) + message(3), link(5, "usb0") + message(3, sequence=2)])
    install_socket(monkeypatch, fake)
    assert native.read_ipv4_interfaces(("usb0",))["usb0"] == [IPv4Interface("192.168.7.1/24")]


@pytest.mark.parametrize("label", [b"old0\0", b"usb0", b"usb0\0extra\0", b"usb0other\0"])
def test_ambiguous_or_malformed_address_label_rejects_snapshot(
    monkeypatch: pytest.MonkeyPatch, label: bytes
) -> None:
    raw = struct.pack("=BBBBI", socket.AF_INET, 24, 0, 0, 5)
    raw += attribute(2, socket.inet_aton("192.168.7.1")) + attribute(3, label)
    fake = FakeSocket([message(20, raw) + message(3), link(5, "usb0") + message(3, sequence=2)])
    install_socket(monkeypatch, fake)
    with pytest.raises(OSError):
        native.read_ipv4_interfaces(("usb0",))
    assert fake.closed


@pytest.mark.parametrize(
    "bad_links", [link(5, "usb0") + link(5, "ignored"), link(5, "usb0") + link(6, "usb0")]
)
def test_ambiguous_link_identity_rejects_snapshot(
    monkeypatch: pytest.MonkeyPatch, bad_links: bytes
) -> None:
    fake = FakeSocket([address(5, "192.168.7.1") + message(3), bad_links + message(3, sequence=2)])
    install_socket(monkeypatch, fake)
    with pytest.raises(OSError, match="ambiguous"):
        native.read_ipv4_interfaces(("usb0",))
    assert fake.closed


@pytest.mark.parametrize("failure", ["socket", "timeout", "parser"])
@pytest.mark.parametrize("per_interface", [False, True])
def test_native_failure_runs_exactly_one_fresh_bounded_ip_fallback(
    monkeypatch: pytest.MonkeyPatch, failure: str, per_interface: bool
) -> None:
    import json
    import subprocess

    calls: list[list[str]] = []

    def fail(*_args: object, **_kwargs: object) -> object:
        if failure == "timeout":
            raise TimeoutError("native deadline")
        if failure == "parser":
            raise native.NetlinkSnapshotError("incomplete dump")
        raise OSError("socket unavailable")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 1.5
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                [
                    {
                        "ifname": "usb0",
                        "flags": ["UP"],
                        "addr_info": [{"local": "192.168.7.1", "prefixlen": 24}],
                    }
                ]
            ),
        )

    monkeypatch.setattr(addresses, "read_ipv4_interfaces", fail)
    monkeypatch.setattr(addresses.subprocess, "run", run)
    if per_interface:
        assert addresses.detect_ipv4_interfaces_for_interface("usb0") == [
            IPv4Interface("192.168.7.1/24")
        ]
        assert calls == [["ip", "-j", "-4", "addr", "show", "dev", "usb0"]]
    else:
        assert addresses.detect_ipv4_interfaces_by_interface(("usb0", "missing")) == {
            "usb0": [IPv4Interface("192.168.7.1/24")],
            "missing": [],
        }
        assert calls == [["ip", "-j", "-4", "addr", "show"]]


@pytest.mark.parametrize("prefix", range(33))
@pytest.mark.parametrize(
    "value", ["0.0.0.0", "1.2.3.4", "127.0.0.1", "169.254.1.2", "192.168.8.1", "255.255.255.255"]
)
def test_packed_addresses_preserve_host_bits_and_every_prefix(value: str, prefix: int) -> None:
    records = [
        (kind, body)
        for kind, _flags, _seq, _port, body in native._messages(address(5, value, prefix=prefix))
    ]
    actual = native._parse_addresses(records, {5: "usb0"}, ("usb0",))["usb0"][0]
    expected = IPv4Interface(f"{value}/{prefix}")
    assert actual == expected
    assert actual.ip == expected.ip
    assert actual.network == expected.network
    assert actual.netmask == expected.netmask


@pytest.mark.parametrize("prefix", [33, 255])
def test_invalid_ipv4_prefix_rejects_entire_snapshot(
    monkeypatch: pytest.MonkeyPatch, prefix: int
) -> None:
    fake = FakeSocket(
        [
            address(5, "192.168.7.1") + address(5, "10.0.0.1", prefix=prefix) + message(3),
            link(5, "usb0") + message(3, sequence=2),
        ]
    )
    install_socket(monkeypatch, fake)
    with pytest.raises(native.NetlinkSnapshotError, match="invalid IPv4"):
        native.read_ipv4_interfaces(("usb0",))
    assert fake.closed


@pytest.mark.parametrize("local", [None, b"", b"\x01\x02\x03", b"\x01\x02\x03\x04\x05"])
@pytest.mark.parametrize("with_peer", [False, True])
def test_invalid_local_never_uses_valid_peer_or_partial_result(
    monkeypatch: pytest.MonkeyPatch, local: bytes | None, with_peer: bool
) -> None:
    raw = struct.pack("=BBBBI", socket.AF_INET, 24, 0, 0, 5)
    if local is not None:
        raw += attribute(2, local)
    if with_peer:
        raw += attribute(1, socket.inet_aton("10.0.0.2"))
    fake = FakeSocket(
        [
            address(5, "192.168.7.1") + message(20, raw) + message(3),
            link(5, "usb0") + message(3, sequence=2),
        ]
    )
    install_socket(monkeypatch, fake)
    if local is None and with_peer:
        assert native.read_ipv4_interfaces(("usb0",))["usb0"] == [
            IPv4Interface("192.168.7.1/24"),
            IPv4Interface("10.0.0.2/24"),
        ]
    else:
        with pytest.raises(native.NetlinkSnapshotError, match="invalid IPv4"):
            native.read_ipv4_interfaces(("usb0",))
    assert fake.closed


def test_ipv6_record_is_ignored_without_affecting_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    ipv6 = struct.pack("=BBBBI", socket.AF_INET6, 64, 0, 0, 5)
    ipv6 += attribute(2, socket.inet_pton(socket.AF_INET6, "2001:db8::1"))
    fake = FakeSocket(
        [
            message(20, ipv6) + address(5, "192.168.7.1") + message(3),
            link(5, "usb0") + message(3, sequence=2),
        ]
    )
    install_socket(monkeypatch, fake)
    assert native.read_ipv4_interfaces(("usb0",))["usb0"] == [IPv4Interface("192.168.7.1/24")]


def test_next_snapshot_observes_changed_then_removed_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in ("192.168.7.1", "10.10.10.10", None):
        fake = FakeSocket(
            [
                (address(5, value) if value else b"") + message(3),
                link(5, "usb0") + message(3, sequence=2),
            ]
        )
        install_socket(monkeypatch, fake)
        assert native.read_ipv4_interfaces(("usb0",))["usb0"] == (
            [IPv4Interface(f"{value}/24")] if value else []
        )
        assert len(fake.requests) == 2
        assert fake.closed
