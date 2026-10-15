"""Fresh Linux IPv4 snapshots using bounded, private rtnetlink dump requests."""

from __future__ import annotations

import socket
import struct
import sys
import time
from collections.abc import Iterator
from ipaddress import IPv4Address, IPv4Interface

_HEADER = struct.Struct("=IHHII")
_LINK = struct.Struct("=BBHiII")
_ADDRESS = struct.Struct("=BBBBI")
_ATTRIBUTE = struct.Struct("=HH")
_DUMP_FLAGS = 0x301  # REQUEST | ROOT | MATCH
_DUMP_INTERRUPTED = 0x10
_NATIVE_TIMEOUT_S = 0.25


class NetlinkSnapshotError(OSError):
    """A dump could not provide a complete, trusted snapshot."""


def read_ipv4_interfaces(
    names: tuple[str, ...], *, require_up: bool = True
) -> dict[str, list[IPv4Interface]]:
    """Return a fresh snapshot, or raise so the caller can use its portable probe.

    Each call owns one socket. Link and address dumps share a deadline; no
    partial results or cache survive a failed, interrupted or malformed dump.
    """
    if sys.platform != "linux":
        raise NetlinkSnapshotError("rtnetlink is only available on Linux")
    deadline = time.monotonic() + _NATIVE_TIMEOUT_S
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, socket.NETLINK_ROUTE) as connection:
        connection.bind((0, 0))
        port_id = connection.getsockname()[0]
        address_records = _dump(
            connection, 22, _ADDRESS.pack(socket.AF_INET, 0, 0, 0, 0), 1, port_id, deadline
        )
        # Sample administrative flags last: a retained address must not mask
        # a link that went down during the address dump. This is a fresh
        # bounded snapshot, not an atomic transaction with interface changes.
        link_records = _dump(connection, 18, _LINK.pack(0, 0, 0, 0, 0, 0), 2, port_id, deadline)
        links = _parse_links(link_records, names, require_up=require_up)
        return _parse_addresses(address_records, links, names)


def _dump(
    connection: socket.socket,
    kind: int,
    payload: bytes,
    sequence: int,
    port_id: int,
    deadline: float,
) -> list[tuple[int, bytes]]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NetlinkSnapshotError("network snapshot deadline expired")
    connection.settimeout(remaining)
    connection.send(
        _HEADER.pack(_HEADER.size + len(payload), kind, _DUMP_FLAGS, sequence, 0) + payload
    )
    records: list[tuple[int, bytes]] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NetlinkSnapshotError("network snapshot deadline expired")
        connection.settimeout(remaining)
        data, _ancillary, flags, source = connection.recvmsg(65536)
        if flags & socket.MSG_TRUNC or source != (0, 0) or not data:
            raise NetlinkSnapshotError("untrusted or truncated network snapshot")
        done = False
        for message_type, message_flags, message_sequence, message_port, body in _messages(data):
            if message_sequence != sequence or message_port not in (0, port_id):
                raise NetlinkSnapshotError("network snapshot response identity mismatch")
            if message_flags & _DUMP_INTERRUPTED:
                raise NetlinkSnapshotError("network snapshot interrupted by interface changes")
            if done:
                raise NetlinkSnapshotError("network snapshot data after completion")
            if message_type == 3:  # NLMSG_DONE: may carry an error status.
                if body and (len(body) < 4 or struct.unpack_from("=i", body)[0] != 0):
                    raise NetlinkSnapshotError("network snapshot completion failed")
                done = True
            elif message_type == 2:  # NLMSG_ERROR, including unsolicited acknowledgements.
                raise NetlinkSnapshotError("network snapshot request failed")
            elif message_type == 4:  # NLMSG_OVERRUN
                raise NetlinkSnapshotError("network snapshot buffer overrun")
            elif message_type != 1:  # Ignore NLMSG_NOOP only.
                records.append((message_type, body))
        if done:
            return records


def _messages(data: bytes) -> Iterator[tuple[int, int, int, int, bytes]]:
    position = 0
    while position < len(data):
        if len(data) - position < _HEADER.size:
            raise NetlinkSnapshotError("short network message header")
        length, kind, flags, sequence, port = _HEADER.unpack_from(data, position)
        end = position + length
        aligned_end = position + _align(length)
        if length < _HEADER.size or end > len(data) or aligned_end > len(data):
            raise NetlinkSnapshotError("invalid network message length")
        yield kind, flags, sequence, port, data[position + _HEADER.size : end]
        position = aligned_end


def _attributes(data: bytes) -> dict[int, bytes]:
    attributes: dict[int, bytes] = {}
    position = 0
    while position < len(data):
        if len(data) - position < _ATTRIBUTE.size:
            raise NetlinkSnapshotError("short network attribute header")
        length, kind = _ATTRIBUTE.unpack_from(data, position)
        end = position + length
        aligned_end = position + _align(length)
        if length < _ATTRIBUTE.size or end > len(data) or aligned_end > len(data):
            raise NetlinkSnapshotError("invalid network attribute length")
        if kind in (1, 2, 3) and kind in attributes:
            raise NetlinkSnapshotError("duplicate network attribute")
        attributes[kind] = data[position + _ATTRIBUTE.size : end]
        position = aligned_end
    return attributes


def _parse_links(
    records: list[tuple[int, bytes]], names: tuple[str, ...], *, require_up: bool
) -> dict[int, str]:
    links: dict[int, str] = {}
    seen_indexes: set[int] = set()
    seen_names: set[str] = set()
    for kind, body in records:
        if kind != 16 or len(body) < _LINK.size:  # RTM_NEWLINK
            raise NetlinkSnapshotError("unexpected link snapshot record")
        _family, _padding, _type, index, flags, _change = _LINK.unpack_from(body)
        attributes = _attributes(body[_LINK.size :])
        raw_name = attributes.get(3)  # IFLA_IFNAME
        if index <= 0 or raw_name is None or not raw_name.endswith(b"\0"):
            raise NetlinkSnapshotError("invalid link identity")
        try:
            name = raw_name[:-1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise NetlinkSnapshotError("invalid link name") from error
        if not name or "\0" in name or index in seen_indexes or name in seen_names:
            raise NetlinkSnapshotError("ambiguous link identity")
        seen_indexes.add(index)
        seen_names.add(name)
        if name in names and (not require_up or flags & 1):  # IFF_UP, independent of carrier.
            links[index] = name
    return links


def _parse_addresses(
    records: list[tuple[int, bytes]], links: dict[int, str], names: tuple[str, ...]
) -> dict[str, list[IPv4Interface]]:
    addresses: dict[str, list[IPv4Interface]] = {name: [] for name in names}
    for kind, body in records:
        if kind != 20 or len(body) < _ADDRESS.size:  # RTM_NEWADDR
            raise NetlinkSnapshotError("unexpected address snapshot record")
        family, prefix, _flags, scope, index = _ADDRESS.unpack_from(body)
        attributes = _attributes(body[_ADDRESS.size :])
        if family != socket.AF_INET or scope == 254 or index not in links:  # RT_SCOPE_HOST
            continue
        raw_label = attributes.get(3)  # IFA_LABEL can identify an index renamed/reused mid-probe.
        if raw_label is not None:
            expected = links[index].encode("utf-8")
            if not raw_label.endswith(b"\0"):
                raise NetlinkSnapshotError("invalid address label")
            label = raw_label[:-1]
            if b"\0" in label or (label != expected and not label.startswith(expected + b":")):
                raise NetlinkSnapshotError("interface identity changed during network snapshot")
        local = attributes.get(2, attributes.get(1))  # IFA_LOCAL wins over point-to-point peer.
        if prefix > 32 or local is None or len(local) != 4:
            raise NetlinkSnapshotError("invalid IPv4 snapshot record")
        addresses[links[index]].append(IPv4Interface(f"{IPv4Address(local)}/{prefix}"))
    return addresses


def _align(length: int) -> int:
    return (length + 3) & ~3
