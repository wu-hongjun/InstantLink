"""Instax BLE packet protocol.

Ported from InstantLink's `instantlink-core/src/protocol.rs`.
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER = bytes([0x41, 0x62])
RESPONSE_HEADER = bytes([0x61, 0x42])
MTU_SIZE = 182
MIN_PACKET_SIZE = 7
MAX_PACKET_PAYLOAD = 65_535 - MIN_PACKET_SIZE


class ProtocolError(ValueError):
    """Raised when packet data is malformed."""


@dataclass(frozen=True, slots=True)
class Packet:
    """Parsed Instax protocol packet."""

    opcode: int
    payload: bytes


def checksum(data: bytes) -> int:
    """Compute Instax checksum: `(255 - (sum & 255)) & 255`."""

    return (255 - (sum(data) & 255)) & 255


def build_packet(opcode: int, payload: bytes = b"") -> bytes:
    """Build a complete Instax protocol packet."""

    if len(payload) > MAX_PACKET_PAYLOAD:
        raise ProtocolError(
            f"packet payload too large: {len(payload)} bytes (max {MAX_PACKET_PAYLOAD})"
        )
    total_size = MIN_PACKET_SIZE + len(payload)
    packet = bytearray()
    packet.extend(HEADER)
    packet.extend(total_size.to_bytes(2, "big"))
    packet.extend(opcode.to_bytes(2, "big"))
    packet.extend(payload)
    packet.append(checksum(bytes(packet)))
    return bytes(packet)


def parse_packet(data: bytes) -> Packet | None:
    """Parse a complete Instax packet, returning `None` if validation fails."""

    if len(data) < MIN_PACKET_SIZE:
        return None
    if data[:2] not in {HEADER, RESPONSE_HEADER}:
        return None
    expected_total = int.from_bytes(data[2:4], "big")
    if expected_total < MIN_PACKET_SIZE or len(data) < expected_total:
        return None
    if data[expected_total - 1] != checksum(data[: expected_total - 1]):
        return None
    opcode = int.from_bytes(data[4:6], "big")
    return Packet(opcode=opcode, payload=data[6 : expected_total - 1])


def fragment(packet: bytes) -> list[bytes]:
    """Split a protocol packet into BLE MTU-sized fragments."""

    return [packet[index : index + MTU_SIZE] for index in range(0, len(packet), MTU_SIZE)]


class PacketAssembler:
    """Reassemble fragmented BLE notifications into complete packets."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> Packet | None:
        """Feed one BLE fragment and return a packet when complete."""

        self._buffer.extend(data)
        if len(self._buffer) < 4:
            return None
        if bytes(self._buffer[:2]) not in {HEADER, RESPONSE_HEADER}:
            next_header = self._find_next_header()
            del self._buffer[:next_header]
            raise ProtocolError(f"invalid header: {next_header} byte(s) discarded")
        expected_total = int.from_bytes(self._buffer[2:4], "big")
        if expected_total < MIN_PACKET_SIZE:
            actual = len(self._buffer)
            del self._buffer[:2]
            raise ProtocolError(f"length mismatch: declared {expected_total}, actual {actual}")
        if len(self._buffer) < expected_total:
            return None
        packet_data = bytes(self._buffer[:expected_total])
        del self._buffer[:expected_total]
        packet = parse_packet(packet_data)
        if packet is None:
            raise ProtocolError("bad checksum or malformed packet")
        return packet

    def reset(self) -> None:
        """Clear buffered fragments."""

        self._buffer.clear()

    def _find_next_header(self) -> int:
        for index, value in enumerate(self._buffer[1:], start=1):
            if value in {HEADER[0], RESPONSE_HEADER[0]}:
                return index
        return len(self._buffer)
