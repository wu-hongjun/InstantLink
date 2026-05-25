from __future__ import annotations

import pytest

from instantlink_bridge.ble import commands, protocol


def test_build_parse_packet_round_trip() -> None:
    packet = protocol.build_packet(0x4321, b"\x01\x02")
    parsed = protocol.parse_packet(packet)
    assert parsed == protocol.Packet(opcode=0x4321, payload=b"\x01\x02")


def test_checksum_known_value() -> None:
    assert protocol.checksum(bytes([0x41, 0x62])) == 92


def test_fragment_and_assemble() -> None:
    packet = protocol.build_packet(0x1234, bytes([0xAA]) * 300)
    fragments = protocol.fragment(packet)
    assert len(fragments) > 1

    assembler = protocol.PacketAssembler()
    assembled = None
    for fragment in fragments:
        assembled = assembler.feed(fragment)
    assert assembled == protocol.Packet(opcode=0x1234, payload=bytes([0xAA]) * 300)


def test_assembler_discards_bad_header_then_accepts_next_packet() -> None:
    packet = protocol.build_packet(0x2222, b"\x01")
    assembler = protocol.PacketAssembler()
    with pytest.raises(protocol.ProtocolError):
        assembler.feed(b"\xde\xad\x00\x07")
    assert assembler.feed(packet) == protocol.Packet(opcode=0x2222, payload=b"\x01")


def test_download_start_encoding() -> None:
    packet = commands.download_start(50_000, print_option=1)
    parsed = protocol.parse_packet(packet)
    assert parsed is not None
    assert parsed.opcode == commands.OP_DOWNLOAD_START
    assert parsed.payload[:4] == b"\x02\x01\x00\x00"
    assert int.from_bytes(parsed.payload[4:8], "big") == 50_000


def test_decode_image_support_response() -> None:
    packet = protocol.Packet(
        opcode=commands.OP_SUPPORT_FUNCTION_INFO,
        payload=b"\x00" + bytes([commands.INFO_IMAGE_SUPPORT]) + b"\x03\x20\x03\x20",
    )
    response = commands.decode_response(packet)
    assert response.kind == commands.ResponseKind.IMAGE_SUPPORT_INFO
    assert response.width == 800
    assert response.height == 800
