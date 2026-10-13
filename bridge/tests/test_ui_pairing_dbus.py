from __future__ import annotations

import asyncio

import pytest
from dbus_fast import Message, MessageType, Variant

from instantlink_bridge.ble.agent import BluezAgentService
from instantlink_bridge.ui import pairing
from instantlink_bridge.ui.models import PairedPrinter

ADDRESS = "FA:AB:BC:51:CC:E2"
OTHER_ADDRESS = "88:B4:36:51:CC:E2"
ADAPTER = "/org/bluez/hci0"
SELECTED = PairedPrinter(address="INSTANTLINK:1N034655", name="INSTAX-1N034655")


def device(
    address: str = ADDRESS,
    alias: str = "INSTAX-1N034655(IOS)",
    connected: bool = True,
    *,
    adapter: str = ADAPTER,
) -> dict[str, object]:
    return {
        "Address": Variant("s", address),
        "Alias": Variant("s", alias),
        "Name": Variant("s", "INSTAX-1N034655"),
        "Connected": Variant("b", connected),
        "Adapter": Variant("o", adapter),
    }


def objects(*devices: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {ADAPTER: {"org.bluez.Adapter1": {}}}
    for properties in devices:
        address = properties["Address"]
        assert isinstance(address, Variant)
        path = f"{ADAPTER}/dev_{address.value.replace(':', '_')}"
        result[path] = {"org.bluez.Device1": properties}
    return result


class FakeBus:
    def __init__(self, reply: Message | None) -> None:
        self.reply = reply
        self.disconnects = 0
        self.calls: list[Message] = []
        self.call_error: Exception | None = None
        self.block_at: str | None = None
        self.waiting = asyncio.Event()

    async def call(self, request: Message) -> Message | None:
        self.calls.append(request)
        if self.call_error is not None:
            raise self.call_error
        if self.block_at == "call":
            self.waiting.set()
            await asyncio.Future[None]()
        return self.reply

    def disconnect(self) -> None:
        self.disconnects += 1


def reply(value: object) -> Message:
    # dbus-fast validates bodies on encoding, not construction. Tests also
    # exercise malformed server values before any mutation can run.
    return Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=1,
        signature="a{oa{sa{sv}}}",
        body=[value],
    )


def install_bus(monkeypatch: pytest.MonkeyPatch, bus: FakeBus) -> BluezAgentService:
    agent = BluezAgentService()
    agent._bus = bus
    agent._registered = True
    original_lookup = pairing._connected_bluez_addresses_from_dbus

    async def lookup(
        selected: PairedPrinter, provider: pairing.BluezObjectsProvider | None = None
    ) -> list[str]:
        return await original_lookup(selected, provider or agent.managed_objects_snapshot)

    monkeypatch.setattr(pairing, "_connected_bluez_addresses_from_dbus", lookup)
    return agent


@pytest.mark.asyncio
async def test_fresh_snapshot_only_connected_alias_matches_and_no_discovery_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus(
        reply(objects(device(), device(OTHER_ADDRESS, "INSTAX-1N034655(ANDROID)", False)))
    )
    install_bus(monkeypatch, bus)
    calls: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        calls.append(args)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    assert await pairing._disconnect_bluez_link_for_identity(SELECTED)
    assert calls == [("disconnect", ADDRESS)]
    assert bus.disconnects == 0
    request = bus.calls[0]
    assert (request.destination, request.path, request.interface, request.member) == (
        "org.bluez",
        "/",
        "org.freedesktop.DBus.ObjectManager",
        "GetManagedObjects",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [{}, objects(), objects(device(connected=False))])
async def test_empty_or_disconnected_authoritative_snapshot_never_uses_cli(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, object]
) -> None:
    bus = FakeBus(reply(snapshot))
    install_bus(monkeypatch, bus)

    async def forbidden(*_args: str, **_kwargs: object) -> pairing._CommandResult:
        raise AssertionError("authoritative negative must not invoke CLI")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", forbidden)
    assert not await pairing._disconnect_bluez_link_for_identity(SELECTED)
    assert bus.disconnects == 0


def test_alias_not_name_and_exact_address_bypasses_alias_filter() -> None:
    renamed = device(alias="Renamed Printer")
    assert pairing._connected_addresses_from_bluez_objects(SELECTED, objects(renamed)) == []
    exact = PairedPrinter(address=ADDRESS.lower(), name="different")
    renamed.pop("Alias")
    assert pairing._connected_addresses_from_bluez_objects(exact, objects(renamed)) == [ADDRESS]


@pytest.mark.parametrize(
    "alias", ["INSTAX-1N034655", " INSTAX-1N034655 (ios) ", "INSTAX-1N034655(ANDROID)"]
)
def test_alias_normalization_matches_existing_cli_identity(alias: str) -> None:
    assert pairing._connected_addresses_from_bluez_objects(
        SELECTED, objects(device(alias=alias))
    ) == [ADDRESS]


@pytest.mark.parametrize(
    "key,value",
    [
        ("Connected", None),
        ("Connected", Variant("s", "false")),
        ("Address", None),
        ("Address", Variant("s", "INSTANTLINK:1N034655")),
        ("Alias", None),
        ("Alias", Variant("b", True)),
        ("Adapter", None),
        ("Adapter", Variant("o", "/org/bluez/hci9")),
    ],
)
def test_unknown_relevant_properties_cannot_mean_disconnected(key: str, value: object) -> None:
    properties = device()
    properties[key] = value
    snapshot = {
        ADAPTER: {"org.bluez.Adapter1": {}},
        ADAPTER + "/dev_FA_AB_BC_51_CC_E2": {"org.bluez.Device1": properties},
    }
    with pytest.raises(ValueError):
        pairing._connected_addresses_from_bluez_objects(SELECTED, snapshot)


def test_multiple_adapters_fall_back_to_cli_default_adapter_scope() -> None:
    snapshot = objects(device())
    snapshot["/org/bluez/hci1"] = {"org.bluez.Adapter1": {}}
    with pytest.raises(ValueError, match="ambiguous"):
        pairing._connected_addresses_from_bluez_objects(SELECTED, snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["unavailable", "malformed", "unknown_connected", "error_reply"]
)
async def test_failed_snapshot_preserves_devices_info_fallback(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    bus = FakeBus(reply(objects(device())))
    if failure == "unavailable":
        bus.call_error = OSError("bus unavailable")
    elif failure == "malformed":
        bus.reply = reply([])
    elif failure == "unknown_connected":
        properties = device()
        properties.pop("Connected")
        bus.reply = reply(objects(properties))
    else:
        bus.reply = Message.new_error(
            Message(serial=1, path="/", member="Test"), "org.bluez.Error.Failed", "failed"
        )
    install_bus(monkeypatch, bus)
    calls: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        calls.append(args)
        if args == ("devices",):
            return pairing._CommandResult(0, f"Device {ADDRESS} INSTAX-1N034655(IOS)")
        if args == ("info", ADDRESS):
            return pairing._CommandResult(0, "Connected: yes")
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    assert await pairing._disconnect_bluez_link_for_identity(SELECTED)
    assert calls == [("devices",), ("info", ADDRESS), ("disconnect", ADDRESS)]
    assert bus.disconnects == 0


@pytest.mark.asyncio
async def test_cancellation_preserves_shared_bus_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus(reply({}))
    bus.block_at = "call"
    install_bus(monkeypatch, bus)

    async def forbidden(*_args: str, **_kwargs: object) -> pairing._CommandResult:
        raise AssertionError("cancellation must not invoke CLI")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", forbidden)
    task = asyncio.create_task(pairing._disconnect_bluez_link_for_identity(SELECTED))
    await bus.waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bus.disconnects == 0


@pytest.mark.asyncio
async def test_timeout_preserves_shared_bus_and_uses_existing_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus(reply({}))
    bus.block_at = "call"
    install_bus(monkeypatch, bus)
    original_timeout = asyncio.timeout
    timeouts: list[float | None] = []

    def short_timeout(delay: float | None) -> asyncio.Timeout:
        timeouts.append(delay)
        return original_timeout(0.001)

    monkeypatch.setattr(pairing.asyncio, "timeout", short_timeout)
    calls: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        calls.append(args)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    assert not await pairing._disconnect_bluez_link_for_identity(SELECTED)
    assert timeouts == [2.0]
    assert calls == [("devices",)]
    assert bus.disconnects == 0


def test_irrelevant_unknown_connection_state_is_ignored() -> None:
    unrelated = device(alias="Other Device")
    unrelated.pop("Connected")
    assert pairing._connected_addresses_from_bluez_objects(SELECTED, objects(unrelated)) == []


def test_boolean_variant_value_is_strict() -> None:
    properties = device()
    # Reject a malformed variant even if its signature still claims boolean.
    value = Variant("b", False)
    value.value = 1
    properties["Connected"] = value
    with pytest.raises(ValueError, match="connection state"):
        pairing._connected_addresses_from_bluez_objects(SELECTED, objects(properties))


@pytest.mark.asyncio
async def test_empty_snapshot_does_not_cache_a_later_connected_result() -> None:
    snapshots = iter(({}, objects(device())))
    calls = 0

    async def provider() -> object:
        nonlocal calls
        calls += 1
        return next(snapshots)

    assert await pairing._connected_bluez_addresses_from_dbus(SELECTED, provider) == []
    assert await pairing._connected_bluez_addresses_from_dbus(SELECTED, provider) == [ADDRESS]
    assert calls == 2


@pytest.mark.asyncio
async def test_pairer_injection_uses_existing_agent_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BluezAgentService()
    bus = FakeBus(reply(objects(device(connected=False))))
    agent._bus = bus
    agent._registered = True

    async def forbidden(*_args: str, **_kwargs: object) -> pairing._CommandResult:
        raise AssertionError("connected-state query must not spawn CLI")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", forbidden)
    pairer = pairing.BluetoothctlPrinterPairer(
        bluez_objects_provider=agent.managed_objects_snapshot
    )
    assert not await pairer.disconnect_bluez_link(SELECTED)
    assert len(bus.calls) == 1
    assert bus.disconnects == 0


@pytest.mark.asyncio
async def test_unready_agent_rejected_without_call_or_disconnection() -> None:
    agent = BluezAgentService()
    bus = FakeBus(reply({}))
    agent._bus = bus
    with pytest.raises(RuntimeError, match="not ready"):
        await agent.managed_objects_snapshot()
    assert bus.calls == []
    assert bus.disconnects == 0


@pytest.mark.asyncio
async def test_missing_provider_uses_legacy_cli_without_constructing_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from instantlink_bridge.ble import agent as agent_module

    def forbidden(**_kwargs: object) -> object:
        raise AssertionError("lookup must not construct a D-Bus connection")

    monkeypatch.setattr(agent_module, "MessageBus", forbidden)
    calls: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        calls.append(args)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    assert not await pairing.BluetoothctlPrinterPairer().disconnect_bluez_link(SELECTED)
    assert calls == [("devices",)]


@pytest.mark.asyncio
async def test_cancelled_query_does_not_cancel_other_shared_bus_call() -> None:
    agent = BluezAgentService()
    calls: list[asyncio.Future[Message]] = []
    two_calls = asyncio.Event()

    class ConcurrentBus:
        async def call(self, _request: Message) -> Message:
            pending: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
            calls.append(pending)
            if len(calls) == 2:
                two_calls.set()
            return await pending

        def disconnect(self) -> None:
            raise AssertionError("a query cannot close the shared pairing agent bus")

    agent._bus = ConcurrentBus()
    agent._registered = True
    first = asyncio.create_task(
        pairing._connected_bluez_addresses_from_dbus(SELECTED, agent.managed_objects_snapshot)
    )
    second = asyncio.create_task(
        pairing._connected_bluez_addresses_from_dbus(SELECTED, agent.managed_objects_snapshot)
    )
    await two_calls.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert calls[0].cancelled()
    assert not calls[1].cancelled()
    calls[1].set_result(reply(objects(device())))
    assert await second == [ADDRESS]
    assert agent._registered


@pytest.mark.asyncio
async def test_instantlink_selector_provider_preserves_cached_backend_when_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider() -> object:
        return objects(device(connected=False))

    class Backend:
        async def scan(self, _timeout_s: float = 1.0) -> list[str]:
            return []

        async def disconnect(self) -> None:
            raise AssertionError("an offline Printer cannot drop a cached backend")

    async def forbidden(*_args: str, **_kwargs: object) -> pairing._CommandResult:
        raise AssertionError("authoritative negative cannot spawn CLI")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", forbidden)
    selector = pairing.InstantLinkPrinterSelector(
        backend=Backend(), bluez_objects_provider=provider
    )
    assert not await selector.disconnect_bluez_link(SELECTED)
