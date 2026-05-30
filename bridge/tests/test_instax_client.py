from __future__ import annotations

import asyncio
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest

from instantlink_bridge.ble import client as client_module
from instantlink_bridge.ble import commands, protocol
from instantlink_bridge.ble.client import (
    BleakInstaxTransport,
    ConnectedInstaxPrinter,
    connect_instax_printer,
    print_file_to_printer,
)
from instantlink_bridge.ble.instax import InstaxPrintPlan, InstaxProtocolClient
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.ble.session import InstaxBleSessionManager, PrinterEndpoint
from instantlink_bridge.imaging.pipeline import FitMode, PreparedImage, PrintEdit


class MockTransport:
    def __init__(self, responses: list[protocol.Packet], dis_model: str | None = None) -> None:
        self.responses = deque(responses)
        self.sent: list[bytes] = []
        self.dis_model = dis_model

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive(self, timeout_s: float = 10.0) -> protocol.Packet:
        return self.responses.popleft()

    async def send_and_receive(
        self,
        data: bytes,
        timeout_s: float = 10.0,
    ) -> protocol.Packet:
        await self.send(data)
        return await self.receive(timeout_s)

    def model_number_hint(self) -> str | None:
        return self.dis_model


def support_response(info_type: int, data: bytes) -> protocol.Packet:
    return protocol.Packet(
        opcode=commands.OP_SUPPORT_FUNCTION_INFO,
        payload=b"\x00" + bytes([info_type]) + data,
    )


def image_support_response(width: int, height: int) -> protocol.Packet:
    return support_response(
        commands.INFO_IMAGE_SUPPORT,
        width.to_bytes(2, "big") + height.to_bytes(2, "big"),
    )


def battery_response(level: int) -> protocol.Packet:
    return support_response(commands.INFO_BATTERY, bytes([0, level]))


def printer_function_response(film_remaining: int, *, is_charging: bool = False) -> protocol.Packet:
    flags = film_remaining & 0x0F
    if is_charging:
        flags |= 0x80
    return support_response(commands.INFO_PRINTER_FUNCTION, bytes([flags]))


def ack(opcode: int, status: int = 0) -> protocol.Packet:
    return protocol.Packet(opcode=opcode, payload=bytes([status]))


@pytest.mark.asyncio
async def test_create_detects_wide_model() -> None:
    transport = MockTransport([image_support_response(1260, 840)])
    client = await InstaxProtocolClient.create(transport, "INSTAX-12345678")
    assert client.model == PrinterModel.WIDE


@pytest.mark.asyncio
async def test_create_detects_mini_link3_from_dis_model() -> None:
    transport = MockTransport([image_support_response(600, 800)], dis_model="FI033")
    client = await InstaxProtocolClient.create(transport, "INSTAX-12345678")
    assert client.model == PrinterModel.MINI_LINK3


@pytest.mark.asyncio
async def test_status_does_not_require_history_for_battery_and_film() -> None:
    transport = MockTransport(
        [
            image_support_response(600, 800),
            battery_response(42),
            printer_function_response(7, is_charging=True),
        ]
    )
    client = await InstaxProtocolClient.create(transport, "INSTAX-12345678")

    status = await client.status()

    assert status.battery == 42
    assert status.film_remaining == 7
    assert status.is_charging is True
    assert status.print_count is None


@pytest.mark.asyncio
async def test_create_honors_compatible_model_override() -> None:
    transport = MockTransport([image_support_response(600, 800)])
    client = await InstaxProtocolClient.create(
        transport,
        "INSTAX-12345678",
        model_override=PrinterModel.MINI_LINK3,
    )

    assert client.model == PrinterModel.MINI_LINK3


@pytest.mark.asyncio
async def test_create_ignores_incompatible_model_override() -> None:
    transport = MockTransport([image_support_response(800, 800)])
    client = await InstaxProtocolClient.create(
        transport,
        "INSTAX-12345678",
        model_override=PrinterModel.MINI,
    )

    assert client.model == PrinterModel.SQUARE


@pytest.mark.asyncio
async def test_print_plan_sends_download_flow() -> None:
    transport = MockTransport(
        [
            image_support_response(600, 800),
            ack(commands.OP_DOWNLOAD_START),
            ack(commands.OP_DATA),
            ack(commands.OP_DOWNLOAD_END),
            protocol.Packet(opcode=commands.OP_LED_PATTERN_SETTINGS, payload=b""),
            ack(commands.OP_PRINT_IMAGE),
        ]
    )
    client = await InstaxProtocolClient.create(transport, "INSTAX-12345678")
    await client.print_plan(
        InstaxPrintPlan(
            jpeg_data=b"\xff\xd8test\xff\xd9",
            chunks=[b"chunk"],
            model=PrinterModel.MINI,
        )
    )
    sent_opcodes = [
        parsed.opcode
        for item in transport.sent
        if (parsed := protocol.parse_packet(item)) is not None
    ]
    assert sent_opcodes == [
        commands.OP_SUPPORT_FUNCTION_INFO,
        commands.OP_DOWNLOAD_START,
        commands.OP_DATA,
        commands.OP_DOWNLOAD_END,
        commands.OP_LED_PATTERN_SETTINGS,
        commands.OP_PRINT_IMAGE,
    ]


@pytest.mark.asyncio
async def test_print_plan_sends_cancel_when_cancelled_during_download() -> None:
    transport = BlockingDataTransport()
    client = InstaxProtocolClient(transport, "INSTAX-12345678", PrinterModel.MINI)
    task = asyncio.create_task(
        client.print_plan(
            InstaxPrintPlan(
                jpeg_data=b"\xff\xd8test\xff\xd9",
                chunks=[b"chunk"],
                model=PrinterModel.MINI,
            )
        )
    )
    await asyncio.wait_for(transport.data_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert commands.OP_DOWNLOAD_CANCEL in transport.sent_opcodes()


@pytest.mark.asyncio
async def test_connected_printer_disconnect_always_disconnects_client() -> None:
    client = DisconnectingClient()
    transport = BleakInstaxTransport(client)
    connected = ConnectedInstaxPrinter(
        client=client,
        transport=transport,
        protocol=cast(InstaxProtocolClient, object()),
    )

    await connected.disconnect()

    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_connect_instax_printer_disconnects_partial_client_after_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_bleak(monkeypatch, BlockingConnectBleakClient)

    with pytest.raises(TimeoutError):
        await connect_instax_printer("FA:AB:BC:51:CC:E2", timeout_s=0.01)

    assert len(BlockingConnectBleakClient.instances) == 1
    assert BlockingConnectBleakClient.instances[0].disconnect_calls == 1


@pytest.mark.asyncio
async def test_connect_instax_printer_prefers_fresh_scanned_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_device = object()
    client_module._DISCOVERED_DEVICE_CACHE.clear()
    client_module._cache_discovered_device("FA:AB:BC:51:CC:E2", cached_device)
    _install_fake_bleak(monkeypatch, BlockingConnectBleakClient)

    with pytest.raises(TimeoutError):
        await connect_instax_printer("FA:AB:BC:51:CC:E2", timeout_s=0.01)

    assert BlockingConnectBleakClient.instances[0].address is cached_device


@pytest.mark.asyncio
async def test_connect_instax_printer_disconnects_partial_client_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_bleak(monkeypatch, BlockingConnectBleakClient)
    task = asyncio.create_task(connect_instax_printer("FA:AB:BC:51:CC:E2"))
    await asyncio.wait_for(BlockingConnectBleakClient.created.wait(), timeout=1)
    client = BlockingConnectBleakClient.instances[0]
    await asyncio.wait_for(client.connect_started.wait(), timeout=1)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_connect_cleanup_cancels_timed_out_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("instantlink_bridge.ble.client.BLE_CLEANUP_TIMEOUT_S", 0.01)
    _install_fake_bleak(monkeypatch, BlockingCleanupBleakClient)

    with pytest.raises(TimeoutError):
        await connect_instax_printer("FA:AB:BC:51:CC:E2", timeout_s=0.01)

    client = cast(BlockingCleanupBleakClient, BlockingCleanupBleakClient.instances[0])
    assert client.disconnect_calls == 1
    assert client.disconnect_cancelled.is_set()


@pytest.mark.asyncio
async def test_print_file_to_printer_reuses_cached_session_without_reconnecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"placeholder")
    endpoint = PrinterEndpoint(address="FA:AB:BC:51:CC:E2", name="INSTAX-1N034655")
    client = DisconnectingClient()
    transport = BleakInstaxTransport(client)
    print_protocol = PrintingProtocol()
    connected = ConnectedInstaxPrinter(
        client=client,
        transport=transport,
        protocol=cast(InstaxProtocolClient, print_protocol),
    )
    connect_calls = 0

    async def connector(
        _endpoint: PrinterEndpoint,
        _model_override: PrinterModel | None,
    ) -> ConnectedInstaxPrinter:
        nonlocal connect_calls
        connect_calls += 1
        return connected

    async def prepare(
        source_path: Path,
        model: PrinterModel,
        *,
        fit: FitMode,
        quality: int,
        edit: PrintEdit | None,
        adjustments: object = None,
        timeout_s: float | None,
    ) -> PreparedImage:
        assert source_path == image_path
        assert model is PrinterModel.MINI
        assert fit is FitMode.AUTO
        assert quality == 100
        assert edit is None
        assert timeout_s is not None
        return PreparedImage(
            data=b"\xff\xd8cached\xff\xd9",
            model=model,
            width=600,
            height=800,
            quality=quality,
            fit=fit,
        )

    session_manager = InstaxBleSessionManager(
        connector,
        connected_model=lambda active: active.protocol.model,
    )
    status_lease = await session_manager.acquire_status(endpoint)
    await status_lease.release(keep_connected=True)
    monkeypatch.setattr("instantlink_bridge.ble.client.prepare_for_instax_async", prepare)

    await print_file_to_printer(
        endpoint.address,
        image_path,
        name=endpoint.name,
        session_manager=session_manager,
    )

    assert connect_calls == 1
    assert print_protocol.print_calls == 1
    assert client.disconnect_calls == 1


def _install_fake_bleak(
    monkeypatch: pytest.MonkeyPatch,
    bleak_client: type[BlockingConnectBleakClient],
) -> None:
    bleak_client.instances = []
    bleak_client.created = asyncio.Event()
    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakClient=bleak_client))


class BlockingConnectBleakClient:
    instances: ClassVar[list[BlockingConnectBleakClient]] = []
    created: ClassVar[asyncio.Event]

    def __init__(self, address: object, services: list[str]) -> None:
        self.address = address
        self.services = services
        self.connect_started = asyncio.Event()
        self.disconnect_calls = 0
        self._never_connected = asyncio.Event()
        type(self).instances.append(self)
        type(self).created.set()

    async def connect(self, **_kwargs: object) -> bool:
        self.connect_started.set()
        await self._never_connected.wait()
        return True

    async def disconnect(self) -> bool:
        self.disconnect_calls += 1
        return True


class BlockingCleanupBleakClient(BlockingConnectBleakClient):
    instances: ClassVar[list[BlockingConnectBleakClient]] = []
    created: ClassVar[asyncio.Event]

    def __init__(self, address: object, services: list[str]) -> None:
        super().__init__(address, services)
        self.disconnect_cancelled = asyncio.Event()

    async def disconnect(self) -> bool:
        self.disconnect_calls += 1
        try:
            await self._never_connected.wait()
        except asyncio.CancelledError:
            self.disconnect_cancelled.set()
            raise
        return True


class DisconnectingClient:
    def __init__(self) -> None:
        self.disconnect_calls = 0

    async def connect(self, **_kwargs: object) -> bool:
        return True

    async def disconnect(self) -> bool:
        self.disconnect_calls += 1
        return True

    async def read_gatt_char(self, _char_specifier: str) -> bytearray:
        return bytearray()

    async def start_notify(
        self,
        _char_specifier: str,
        _callback: Callable[[object, bytearray], None],
    ) -> None:
        return None

    async def stop_notify(self, _char_specifier: str) -> None:
        raise RuntimeError("notify failed")

    async def write_gatt_char(
        self,
        _char_specifier: str,
        _data: bytes,
        *,
        response: bool,
    ) -> None:
        return None


class BlockingDataTransport:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.data_started = asyncio.Event()
        self._never = asyncio.Event()

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive(self, timeout_s: float = 10.0) -> protocol.Packet:
        _ = timeout_s
        raise AssertionError("receive should not be called")

    async def send_and_receive(
        self,
        data: bytes,
        timeout_s: float = 10.0,
    ) -> protocol.Packet:
        _ = timeout_s
        await self.send(data)
        parsed = protocol.parse_packet(data)
        assert parsed is not None
        if parsed.opcode == commands.OP_DOWNLOAD_START:
            return ack(commands.OP_DOWNLOAD_START)
        if parsed.opcode == commands.OP_DATA:
            self.data_started.set()
            await self._never.wait()
        raise AssertionError(f"unexpected opcode {parsed.opcode:#x}")

    def model_number_hint(self) -> str | None:
        return None

    def sent_opcodes(self) -> list[int]:
        opcodes: list[int] = []
        for item in self.sent:
            parsed = protocol.parse_packet(item)
            if parsed is not None:
                opcodes.append(parsed.opcode)
        return opcodes


class PrintingProtocol:
    def __init__(self) -> None:
        self.model = PrinterModel.MINI
        self.print_calls = 0

    async def print_prepared(
        self,
        prepared: PreparedImage,
        print_option: int = 0,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        assert prepared.model is PrinterModel.MINI
        assert print_option == 0
        self.print_calls += 1
        if progress is not None:
            progress(1, 1)
