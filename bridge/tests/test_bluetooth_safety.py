"""Regression coverage for authenticated snapshots and destructive bond gates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from dbus_fast import Message, MessageType, Variant
from test_bluez_agent_recovery import (
    DEVICE_PATH,
    OTHER_PATH,
    FakeBus,
    addition_signal,
    connection_signal,
    emit,
    install,
    selected_tree,
    tree_calls,
)
from test_ui_pairing_dbus import (
    ADDRESS,
    OTHER_ADDRESS,
    SELECTED,
    BondBackend,
    device,
    objects,
    reply,
)

from instantlink_bridge.ble import agent as agent_module
from instantlink_bridge.ble.agent import BluezAgentService
from instantlink_bridge.ui import pairing


def pairer_for(
    native: bool,
    provider: pairing.BluezObjectsProvider | None,
    backend: BondBackend,
) -> pairing.PrinterPairer:
    if native:
        return pairing.InstantLinkPrinterSelector(backend=backend, bluez_objects_provider=provider)
    return pairing.BluetoothctlPrinterPairer(bluez_objects_provider=provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("connected", [False, True])
async def test_buffered_reply_then_signal_refreshes_bond_gate(
    monkeypatch: pytest.MonkeyPatch, native: bool, connected: bool
) -> None:
    service = BluezAgentService()
    service._owner = ":1.10"
    service._registered = True
    pending: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
    entered = asyncio.Event()

    class Bus:
        connected = True
        calls = 0

        async def call(self, _request: Message) -> Message:
            self.calls += 1
            if self.calls == 1:
                entered.set()
                return await pending
            return reply(objects(device(connected=connected)))

    bus = Bus()
    service._bus = bus
    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(0, f"Device {ADDRESS} INSTAX-1N034655(IOS)")
        if args == ("info", ADDRESS):
            return pairing._CommandResult(0, "Connected: yes" if connected else "Connected: no")
        assert args == ("remove", ADDRESS)
        assert not connected
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    task = asyncio.create_task(
        pairer_for(native, service.managed_objects_snapshot, backend).reset_bond_if_disconnected(
            SELECTED
        )
    )
    await entered.wait()
    # Match dbus-fast's buffered reader: resolve the older reply, then handle
    # its later signal synchronously before the awaiting query resumes.
    pending.set_result(reply(objects(device(connected=not connected))))
    service._owner_changed(
        Message(
            message_type=MessageType.SIGNAL,
            sender=service._owner,
            path="/org/bluez/hci0/dev_" + ADDRESS.replace(":", "_"),
            interface="org.freedesktop.DBus.Properties",
            member="PropertiesChanged",
            signature="sa{sv}as",
            body=["org.bluez.Device1", {"Connected": Variant("b", connected)}, []],
        )
    )
    assert await task is not connected
    assert bus.calls == 2
    assert commands == ([] if connected else [("remove", ADDRESS)])
    assert backend.disconnect_calls == int(native and not connected)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_reset_never_enlarges_snapshot_authorized_targets(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    async def provider() -> object:
        return objects(device(connected=False))

    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            # A later inventory exposes an unchecked live platform identity.
            return pairing._CommandResult(0, f"Device {OTHER_ADDRESS} INSTAX-1N034655(ANDROID)")
        if args == ("info", OTHER_ADDRESS):
            return pairing._CommandResult(0, "Connected: yes")
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    assert await pairer_for(native, provider, BondBackend()).reset_bond_if_disconnected(SELECTED)
    assert commands == [("remove", ADDRESS)]


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("change", ["live", "new_identity", "uncertain"])
async def test_reset_refreshes_before_second_deletion_and_aborts_changed_inventory(
    monkeypatch: pytest.MonkeyPatch, native: bool, change: str
) -> None:
    queries = 0

    async def provider() -> object:
        nonlocal queries
        queries += 1
        first = device(connected=False)
        other = device(OTHER_ADDRESS, "INSTAX-1N034655(ANDROID)", False)
        if queries == 1:
            return objects(first, other)
        if change == "uncertain":
            raise OSError("owner unavailable")
        if change == "live":
            first["Connected"] = Variant("b", True)
            return objects(first)
        return objects(first, device("AA:BB:CC:DD:EE:FF", connected=False))

    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(1, "BlueZ unavailable")
        assert args == ("remove", OTHER_ADDRESS)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    pairer = pairer_for(native, provider, backend)
    assert await pairer.reset_bond_if_disconnected(SELECTED)
    assert backend.disconnect_calls == int(native)
    assert ("remove", ADDRESS) not in commands
    assert queries == 2


async def pending_watch(
    monkeypatch: pytest.MonkeyPatch, old: dict[str, object]
) -> tuple[
    BluezAgentService,
    FakeBus,
    asyncio.Future[Message],
    asyncio.Task[Callable[[], None]],
    list[None],
]:
    bus = FakeBus()
    bus.snapshot = old
    service = install(monkeypatch, bus)
    await service.start()
    pending: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
    entered = asyncio.Event()
    original = bus.call
    first = True

    async def call(request: Message) -> Message:
        nonlocal first
        if request.member == "GetManagedObjects" and first:
            first = False
            bus.calls.append(request)
            entered.set()
            return await pending
        return await original(request)

    bus.call = call
    edges: list[None] = []
    task = asyncio.create_task(
        service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    )
    await entered.wait()
    return service, bus, pending, task, edges


@pytest.mark.asyncio
@pytest.mark.parametrize("renamed", [False, True])
async def test_watch_buffered_reply_then_new_live_alias_uses_current_identity(
    monkeypatch: pytest.MonkeyPatch, renamed: bool
) -> None:
    old = selected_tree(renamed)
    service, bus, pending, task, edges = await pending_watch(monkeypatch, old)
    pending.set_result(
        Message(
            message_type=MessageType.METHOD_RETURN,
            sender=bus.owner,
            reply_serial=1,
            signature="a{oa{sa{sv}}}",
            body=[old],
        )
    )
    current = selected_tree(False)
    if renamed:
        properties = {"Name": Variant("s", "Other Device"), "Connected": Variant("b", False)}
        current[DEVICE_PATH] = {"org.bluez.Device1": properties}
        signal = connection_signal(bus)
        signal.body[1] = properties
        emit(bus, signal)
    properties = {
        "Alias": Variant("s", "INSTAX-52006924(ANDROID)"),
        "Connected": Variant("b", True),
    }
    current[OTHER_PATH] = {"org.bluez.Device1": properties}
    emit(bus, addition_signal(bus, OTHER_PATH, properties))
    bus.snapshot = current
    disarm = await task
    assert not edges
    assert service._disconnect_watches[0].paths == {OTHER_PATH}
    assert tree_calls(bus) == 2
    emit(bus, connection_signal(bus, path=OTHER_PATH))
    assert edges == [None]
    disarm()
    await service.stop()


@pytest.mark.asyncio
async def test_wrong_owner_snapshot_cannot_seed_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    service, bus, pending, task, edges = await pending_watch(monkeypatch, selected_tree(False))
    pending.set_result(
        Message(
            message_type=MessageType.METHOD_RETURN,
            sender=":1.99",
            reply_serial=1,
            signature="a{oa{sa{sv}}}",
            body=[selected_tree(False)],
        )
    )
    with pytest.raises(ValueError, match="wrong owner"):
        await task
    assert not service._disconnect_watches
    assert not edges
    assert bus.connected
    await service.stop()


@pytest.mark.asyncio
async def test_pending_watch_overflow_abandons_registration_without_losing_rows_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, bus, pending, task, edges = await pending_watch(monkeypatch, selected_tree())
    watch = service._disconnect_watches[0]
    for index in range(agent_module.DEVICE_CACHE_LIMIT + 2):
        path = "/org/bluez/hci0/dev_00_00_00_00_" + f"{index >> 8:02X}_{index & 255:02X}"
        emit(bus, connection_signal(bus, path=path))
        assert len(watch.changed) <= agent_module.DEVICE_CACHE_LIMIT
    assert watch.overflowed
    assert not watch.active
    assert not service._disconnect_watches
    pending.set_result(reply(selected_tree()))
    with pytest.raises(RuntimeError, match="exceeded limit"):
        await task
    assert not edges
    assert bus.connected
    await service.stop()


@pytest.mark.asyncio
async def test_continuously_superseded_snapshot_has_bounded_attempts() -> None:
    service = BluezAgentService()
    service._owner = ":1.10"
    service._registered = True

    class Bus:
        connected = True
        calls = 0

        async def call(self, _request: Message) -> Message:
            self.calls += 1
            old = reply(objects(device(connected=False)))
            service._owner_changed(
                Message(
                    message_type=MessageType.SIGNAL,
                    sender=service._owner,
                    path="/org/bluez/hci0/dev_" + ADDRESS.replace(":", "_"),
                    interface="org.freedesktop.DBus.Properties",
                    member="PropertiesChanged",
                    signature="sa{sv}as",
                    body=["org.bluez.Device1", {"Connected": Variant("b", True)}, []],
                )
            )
            return old

    bus = Bus()
    service._bus = bus
    with pytest.raises(RuntimeError, match="state changed"):
        await service.managed_objects_snapshot()
    assert bus.calls == 2
    assert not service._device_cache_complete
    assert bus.connected


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_wrong_owner_snapshot_uses_fresh_cli_live_guard(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    service = BluezAgentService()
    service._registered = True
    service._owner = ":1.10"

    class Bus:
        connected = True

        async def call(self, _request: Message) -> Message:
            result = reply(objects(device(connected=False)))
            result.sender = ":1.99"
            return result

    service._bus = Bus()
    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(0, f"Device {ADDRESS} INSTAX-1N034655(IOS)")
        assert args == ("info", ADDRESS)
        return pairing._CommandResult(0, "Connected: yes")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    assert not await pairer_for(
        native, service.managed_objects_snapshot, backend
    ).reset_bond_if_disconnected(SELECTED)
    assert commands == [("devices",), ("info", ADDRESS)]
    assert not backend.disconnect_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_cli_reset_does_not_reenumerate_and_remove_new_unchecked_address(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    inventories = iter([ADDRESS, OTHER_ADDRESS])
    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(0, f"Device {next(inventories)} INSTAX-1N034655(IOS)")
        if args == ("info", ADDRESS):
            return pairing._CommandResult(0, "Connected: no")
        assert args == ("remove", ADDRESS)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    assert await pairer_for(native, None, BondBackend()).reset_bond_if_disconnected(SELECTED)
    assert commands == [("devices",), ("info", ADDRESS), ("remove", ADDRESS)]


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_new_adapter_during_snapshot_cannot_authorize_removal(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    service = BluezAgentService()
    service._registered = True
    service._owner = ":1.10"
    queries = 0

    class Bus:
        connected = True

        async def call(self, _request: Message) -> Message:
            nonlocal queries
            queries += 1
            old = objects(device(connected=False))
            if queries == 1:
                service._owner_changed(
                    Message(
                        message_type=MessageType.SIGNAL,
                        sender=service._owner,
                        path="/",
                        interface="org.freedesktop.DBus.ObjectManager",
                        member="InterfacesAdded",
                        signature="oa{sa{sv}}",
                        body=["/org/bluez/hci1", {"org.bluez.Adapter1": {}}],
                    )
                )
            else:
                old["/org/bluez/hci1"] = {"org.bluez.Adapter1": {}}
            return reply(old)

    service._bus = Bus()
    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(0, f"Device {ADDRESS} INSTAX-1N034655(IOS)")
        assert args == ("info", ADDRESS)
        return pairing._CommandResult(0, "Connected: yes")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    assert not await pairer_for(
        native, service.managed_objects_snapshot, backend
    ).reset_bond_if_disconnected(SELECTED)
    assert queries == 2
    assert commands == [("devices",), ("info", ADDRESS)]
    assert not backend.disconnect_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_cli_target_reconnection_during_other_identity_check_prevents_removal(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    ordered = sorted([ADDRESS, OTHER_ADDRESS])
    connected = {address: False for address in ordered}
    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(
                0, "\n".join(f"Device {address} INSTAX-1N034655(IOS)" for address in ordered)
            )
        if args == ("info", ordered[1]):
            connected[ordered[0]] = True
            return pairing._CommandResult(0, "Connected: no")
        if args == ("info", ordered[0]):
            return pairing._CommandResult(
                0, "Connected: yes" if connected[ordered[0]] else "Connected: no"
            )
        if args[0] == "remove":
            assert not connected[args[1]], "a later info call superseded the removal target's check"
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    assert not await pairer_for(native, None, backend).reset_bond_if_disconnected(SELECTED)
    assert commands == [("devices",), ("info", ordered[1]), ("info", ordered[0])]
    assert not backend.disconnect_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_cli_each_removed_target_is_the_last_fresh_identity_check(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    remaining = {ADDRESS, OTHER_ADDRESS}
    commands: list[tuple[str, ...]] = []

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        if args[0] == "remove":
            assert commands[-1] == ("info", args[1])
            remaining.remove(args[1])
        commands.append(args)
        if args == ("devices",):
            return pairing._CommandResult(
                0, "\n".join(f"Device {address} INSTAX-1N034655(IOS)" for address in remaining)
            )
        if args[0] == "info":
            return pairing._CommandResult(0, "Connected: no")
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    assert await pairer_for(native, None, backend).reset_bond_if_disconnected(SELECTED)
    assert not remaining
    assert backend.disconnect_calls == int(native)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("results", [(1,), (1, 0), (0, 1), (1, 1)])
async def test_failed_removal_does_not_count_as_success_and_partial_progress_is_preserved(
    monkeypatch: pytest.MonkeyPatch, native: bool, results: tuple[int, ...]
) -> None:
    addresses = [ADDRESS] if len(results) == 1 else sorted([ADDRESS, OTHER_ADDRESS])
    remaining = set(addresses)
    return_codes = dict(zip(addresses, results, strict=True))
    commands: list[tuple[str, ...]] = []

    async def provider() -> object:
        return objects(*(device(address, connected=False) for address in remaining))

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        commands.append(args)
        assert args[0] == "remove"
        code = return_codes[args[1]]
        if code == 0:
            remaining.remove(args[1])
        return pairing._CommandResult(code, "" if code == 0 else "Failed to remove device")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    backend = BondBackend()
    succeeded = 0 in results
    assert (
        await pairer_for(native, provider, backend).reset_bond_if_disconnected(SELECTED)
        is succeeded
    )
    assert commands == [("remove", address) for address in addresses]
    assert backend.disconnect_calls == int(native and succeeded)
