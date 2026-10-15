"""Diagnostic backend parity for the observed Square Link history payload."""

from __future__ import annotations

import pytest

from instantlink_bridge.ble import commands, protocol


def response(data: bytes, status: int = 0) -> commands.DecodedResponse:
    return commands.decode_response(
        protocol.Packet(
            opcode=commands.OP_SUPPORT_FUNCTION_INFO,
            payload=bytes([status, commands.INFO_PRINT_HISTORY]) + data,
        )
    )


def test_observed_square_history_reads_leading_full_counter() -> None:
    for suffix in [bytes.fromhex("00000012"), bytes.fromhex("ffffffff")]:
        decoded = response(bytes.fromhex("00000043") + suffix)
        assert decoded.kind is commands.ResponseKind.HISTORY_INFO
        assert decoded.print_count == 67


@pytest.mark.parametrize("count", [0, 42, 67, 255, 256, 65535])
@pytest.mark.parametrize("square_format", [False, True])
def test_supported_counters_preserve_native_u16_contract(count: int, square_format: bool) -> None:
    data = (
        count.to_bytes(4, "big") + bytes.fromhex("00000012")
        if square_format
        else count.to_bytes(2, "big")
    )
    decoded = response(data)
    assert decoded.kind is commands.ResponseKind.HISTORY_INFO
    assert decoded.print_count == count


@pytest.mark.parametrize("count", [65536, 65536 + 67, 0xFFFFFFFF])
def test_overflow_never_wraps_or_reports_high_u16_as_count(count: int) -> None:
    decoded = response(count.to_bytes(4, "big") + bytes.fromhex("00000012"))
    assert decoded.kind is commands.ResponseKind.UNKNOWN
    assert decoded.print_count is None


@pytest.mark.parametrize("length", [0, 1, 3, 4, 5, 6, 7, 9, 10, 16])
def test_ambiguous_or_truncated_history_data_is_rejected(length: int) -> None:
    decoded = response(bytes([0x43]) * length)
    assert decoded.kind is commands.ResponseKind.UNKNOWN
    assert decoded.print_count is None


def test_nonzero_history_status_is_not_a_valid_count() -> None:
    decoded = response(bytes.fromhex("0000004300000012"), status=1)
    assert decoded.kind is commands.ResponseKind.UNKNOWN
    assert decoded.print_count is None
