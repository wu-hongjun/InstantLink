"""Instax command opcodes and response decoding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from instantlink_bridge.ble import protocol

OP_DEVICE_INFO_SERVICE = 0x0001
OP_SUPPORT_FUNCTION_INFO = 0x0002
OP_DOWNLOAD_START = 0x1000
OP_DATA = 0x1001
OP_DOWNLOAD_END = 0x1002
OP_DOWNLOAD_CANCEL = 0x1003
OP_PRINT_IMAGE = 0x1080
OP_LED_PATTERN_SETTINGS = 0x3001
OP_SHUT_DOWN = 0x0100
OP_RESET = 0x0101

INFO_IMAGE_SUPPORT = 0
INFO_BATTERY = 1
INFO_PRINTER_FUNCTION = 2
INFO_PRINT_HISTORY = 3


class ResponseKind(StrEnum):
    """Decoded response kind."""

    DEVICE_INFO = "device_info"
    IMAGE_SUPPORT_INFO = "image_support_info"
    BATTERY_STATUS = "battery_status"
    PRINTER_FUNCTION_INFO = "printer_function_info"
    HISTORY_INFO = "history_info"
    DOWNLOAD_ACK = "download_ack"
    PRINT_STATUS = "print_status"
    LED_ACK = "led_ack"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DecodedResponse:
    """Generic decoded response container."""

    kind: ResponseKind
    payload: bytes
    status: int | None = None
    width: int | None = None
    height: int | None = None
    battery_state: int | None = None
    battery_level: int | None = None
    film_remaining: int | None = None
    is_charging: bool | None = None
    print_count: int | None = None


def device_info() -> bytes:
    """Build a device info command."""

    return protocol.build_packet(OP_DEVICE_INFO_SERVICE)


def image_support_info() -> bytes:
    """Build an image support query."""

    return protocol.build_packet(OP_SUPPORT_FUNCTION_INFO, bytes([INFO_IMAGE_SUPPORT]))


def battery_status() -> bytes:
    """Build a battery status query."""

    return protocol.build_packet(OP_SUPPORT_FUNCTION_INFO, bytes([INFO_BATTERY]))


def printer_function_info() -> bytes:
    """Build a printer function query."""

    return protocol.build_packet(OP_SUPPORT_FUNCTION_INFO, bytes([INFO_PRINTER_FUNCTION]))


def history_info() -> bytes:
    """Build a print history query."""

    return protocol.build_packet(OP_SUPPORT_FUNCTION_INFO, bytes([INFO_PRINT_HISTORY]))


def download_start(image_size: int, print_option: int = 0) -> bytes:
    """Build a download-start command."""

    payload = bytearray([0x02, print_option & 0xFF, 0x00, 0x00])
    payload.extend(image_size.to_bytes(4, "big"))
    return protocol.build_packet(OP_DOWNLOAD_START, bytes(payload))


def data_chunk(index: int, data: bytes) -> bytes:
    """Build an image data chunk command."""

    payload = bytearray(index.to_bytes(4, "big"))
    payload.extend(data)
    return protocol.build_packet(OP_DATA, bytes(payload))


def download_end() -> bytes:
    """Build a download-end command."""

    return protocol.build_packet(OP_DOWNLOAD_END)


def download_cancel() -> bytes:
    """Build a download-cancel command."""

    return protocol.build_packet(OP_DOWNLOAD_CANCEL)


def print_image() -> bytes:
    """Build a print-image command."""

    return protocol.build_packet(OP_PRINT_IMAGE)


def led_pattern(red: int, green: int, blue: int, pattern: int) -> bytes:
    """Build a LED pattern command using BGR color order."""

    return protocol.build_packet(
        OP_LED_PATTERN_SETTINGS,
        bytes([pattern & 0xFF, 0x01, 0x01, 0xFF, blue & 0xFF, green & 0xFF, red & 0xFF]),
    )


def shutdown() -> bytes:
    """Build a shutdown command."""

    return protocol.build_packet(OP_SHUT_DOWN)


def reset() -> bytes:
    """Build a reset command."""

    return protocol.build_packet(OP_RESET)


def decode_response(packet: protocol.Packet) -> DecodedResponse:
    """Decode a parsed packet into a typed response summary."""

    payload = packet.payload
    if packet.opcode == OP_DEVICE_INFO_SERVICE:
        return DecodedResponse(kind=ResponseKind.DEVICE_INFO, payload=payload)
    if packet.opcode == OP_SUPPORT_FUNCTION_INFO:
        return _decode_support_function_info(payload)
    if packet.opcode in {OP_DOWNLOAD_START, OP_DATA, OP_DOWNLOAD_END, OP_DOWNLOAD_CANCEL}:
        status = payload[0] if payload else None
        return DecodedResponse(
            kind=ResponseKind.DOWNLOAD_ACK,
            payload=payload,
            status=status,
        )
    if packet.opcode == OP_PRINT_IMAGE:
        status = payload[0] if payload else None
        return DecodedResponse(kind=ResponseKind.PRINT_STATUS, payload=payload, status=status)
    if packet.opcode == OP_LED_PATTERN_SETTINGS:
        return DecodedResponse(kind=ResponseKind.LED_ACK, payload=payload)
    return DecodedResponse(kind=ResponseKind.UNKNOWN, payload=payload)


def _decode_support_function_info(payload: bytes) -> DecodedResponse:
    if len(payload) < 2 or payload[0] != 0:
        return DecodedResponse(kind=ResponseKind.UNKNOWN, payload=payload)
    info_type = payload[1]
    data = payload[2:]
    if info_type == INFO_IMAGE_SUPPORT and len(data) >= 4:
        return DecodedResponse(
            kind=ResponseKind.IMAGE_SUPPORT_INFO,
            payload=payload,
            width=int.from_bytes(data[0:2], "big"),
            height=int.from_bytes(data[2:4], "big"),
        )
    if info_type == INFO_BATTERY and len(data) >= 2:
        return DecodedResponse(
            kind=ResponseKind.BATTERY_STATUS,
            payload=payload,
            battery_state=data[0],
            battery_level=data[1],
        )
    if info_type == INFO_PRINTER_FUNCTION and data:
        return DecodedResponse(
            kind=ResponseKind.PRINTER_FUNCTION_INFO,
            payload=payload,
            film_remaining=data[0] & 0x0F,
            is_charging=bool(data[0] & 0x80),
        )
    if info_type == INFO_PRINT_HISTORY and len(data) >= 2:
        return DecodedResponse(
            kind=ResponseKind.HISTORY_INFO,
            payload=payload,
            print_count=int.from_bytes(data[0:2], "big"),
        )
    return DecodedResponse(kind=ResponseKind.UNKNOWN, payload=payload)
