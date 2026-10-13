from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from dbus_fast import Message, MessageType, Variant
from dbus_fast.errors import DBusError

from instantlink_bridge.ble import agent as module


class Manager:
    def __init__(self, bus: FakeBus, owner: str) -> None:
        self.bus = bus
        self.owner = owner
        self.registered = False

    async def call_register_agent(self, path: str, capability: str) -> None:
        self.bus.operations.append((self.owner, "register", path, capability))
        await self.bus.stage(self.owner, "register")
        if self.registered:
            raise DBusError("org.bluez.Error.AlreadyExists", "already owned")
        self.registered = True

    async def call_request_default_agent(self, path: str) -> None:
        self.bus.operations.append((self.owner, "default", path))
        await self.bus.stage(self.owner, "default")

    async def call_unregister_agent(self, path: str) -> None:
        self.bus.operations.append((self.owner, "unregister", path))
        await self.bus.stage(self.owner, "unregister")
        if self.bus.unregister_error is not None:
            raise self.bus.unregister_error
        self.registered = False


class Properties:
    def __init__(self, bus: FakeBus, owner: str) -> None:
        self.bus = bus
        self.owner = owner

    async def call_set(self, interface: str, name: str, value: Variant) -> None:
        self.bus.operations.append((self.owner, name, interface, value.value))
        await self.bus.stage(self.owner, name)


class Proxy:
    def __init__(self, bus: FakeBus, owner: str) -> None:
        self.bus = bus
        self.owner = owner

    def get_interface(self, name: str) -> Manager | Properties:
        if name == "org.bluez.AgentManager1":
            return self.bus.managers.setdefault(self.owner, Manager(self.bus, self.owner))
        return Properties(self.bus, self.owner)


class FakeBus:
    def __init__(self, owner: str = ":1.10") -> None:
        self.owner = owner
        self.connected = True
        self.handlers: list[Callable[[Message], object]] = []
        self.calls: list[Message] = []
        self.operations: list[tuple[Any, ...]] = []
        self.managers: dict[str, Manager] = {}
        self.exports: list[str] = []
        self.unexports: list[str] = []
        self.disconnects = 0
        self.connects = 0
        self.block: tuple[str, str] | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.ignore_cancel_once = False
        self.fail_once: str | None = None
        self.fail_always: str | None = None
        self.unregister_error: Exception | None = None
        self.snapshot_wait = False
        self.owner_query_change: str | None = None
        self.snapshot: dict[str, object] = {}

    async def connect(self) -> FakeBus:
        self.connects += 1
        self.connected = True
        await self.stage("bus", "connect")
        return self

    def export(self, path: str, _interface: object) -> None:
        self.exports.append(path)

    def unexport(self, path: str) -> None:
        self.unexports.append(path)

    def disconnect(self) -> None:
        self.disconnects += 1
        self.connected = False

    def add_message_handler(self, handler: Callable[[Message], object]) -> None:
        self.handlers.append(handler)

    def remove_message_handler(self, handler: Callable[[Message], object]) -> None:
        self.handlers.remove(handler)

    async def call(self, request: Message) -> Message:
        self.calls.append(request)
        await self.stage("bus", request.member or "")
        if request.member == "GetNameOwner":
            owner = self.owner
            if self.owner_query_change is not None:
                self.change_owner(self.owner_query_change)
            if not owner:
                return Message(
                    message_type=MessageType.ERROR,
                    reply_serial=1,
                    error_name="org.freedesktop.DBus.Error.NameHasNoOwner",
                    signature="s",
                    body=["no owner"],
                )
            return Message(
                message_type=MessageType.METHOD_RETURN, reply_serial=1, signature="s", body=[owner]
            )
        if request.member == "GetManagedObjects":
            if self.snapshot_wait:
                self.entered.set()
                await self.release.wait()
            return Message(
                message_type=MessageType.METHOD_RETURN,
                reply_serial=1,
                signature="a{oa{sa{sv}}}",
                sender=self.owner,
                body=[self.snapshot],
            )
        return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1)

    async def introspect(self, owner: str, path: str) -> object:
        self.operations.append((owner, "introspect", path))
        await self.stage(owner, "introspect")
        return object()

    def get_proxy_object(self, owner: str, _path: str, _introspection: object) -> Proxy:
        return Proxy(self, owner)

    async def stage(self, owner: str, stage: str) -> None:
        if self.fail_always == stage:
            raise DBusError("org.freedesktop.DBus.Error.UnknownObject", "not exported yet")
        if self.fail_once == stage:
            self.fail_once = None
            raise DBusError("org.freedesktop.DBus.Error.UnknownObject", "not exported yet")
        if self.block == (owner, stage):
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                if not self.ignore_cancel_once:
                    raise
                self.ignore_cancel_once = False
                await self.release.wait()

    def change_owner(self, owner: str) -> None:
        old = self.owner
        self.owner = owner
        signal = Message(
            message_type=MessageType.SIGNAL,
            sender="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="NameOwnerChanged",
            signature="sss",
            body=["org.bluez", old, owner],
        )
        for handler in tuple(self.handlers):
            assert handler(signal) is None

    def interfaces_added(
        self,
        path: str,
        interface: str,
        *,
        sender: str | None = None,
    ) -> None:
        signal = Message(
            message_type=MessageType.SIGNAL,
            sender=sender or self.owner,
            path="/",
            interface="org.freedesktop.DBus.ObjectManager",
            member="InterfacesAdded",
            signature="oa{sa{sv}}",
            body=[path, {interface: {}}],
        )
        for handler in tuple(self.handlers):
            assert handler(signal) is None


def install(monkeypatch: pytest.MonkeyPatch, bus: FakeBus) -> module.BluezAgentService:
    monkeypatch.setattr(module, "MessageBus", lambda **_kwargs: bus)
    monkeypatch.setattr(module, "REGISTRATION_RETRY_DELAYS", (0.0, 0.0, 0.0))
    return module.BluezAgentService()


async def settled(service: module.BluezAgentService) -> None:
    task = service._registration_task
    if task is not None:
        await task


@pytest.mark.asyncio
async def test_owner_loss_and_return_restore_on_same_bus_without_duplicate_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    service = install(monkeypatch, bus)
    await service.start()
    assert service._registered
    assert [call.member for call in bus.calls] == ["AddMatch"] * 5 + ["GetNameOwner"]
    bus.change_owner("")
    assert not service._registered
    with pytest.raises(RuntimeError, match="not ready"):
        await service.managed_objects_snapshot()
    bus.change_owner(":1.20")
    bus.change_owner(":1.20")
    await settled(service)
    await service.start()
    assert service._registered
    assert bus.connects == 1
    assert len([op for op in bus.operations if op[1] == "register"]) == 2
    assert await service.managed_objects_snapshot() == {}
    assert bus.calls[-1].destination == ":1.20"
    await asyncio.gather(service.stop(), service.stop())
    assert bus.disconnects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["unregister", "RemoveMatch"])
async def test_cancelling_stop_finishes_cleanup_before_propagating_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    bus = FakeBus()
    service = install(monkeypatch, bus)
    await service.start()
    bus.block = (":1.10" if stage == "unregister" else "bus", stage)
    stopping = asyncio.create_task(service.stop())
    await bus.entered.wait()
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done() and bus.disconnects == 0
    bus.release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert bus.disconnects == 1 and not bus.handlers
    assert service._bus is None and not service._registered
    assert not service._registration_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "AddMatch", "register"])
async def test_cancelling_start_cleans_own_connection_and_registration(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    bus = FakeBus()
    bus.block = (":1.10" if stage == "register" else "bus", stage)
    service = install(monkeypatch, bus)
    startup = asyncio.create_task(service.start())
    await bus.entered.wait()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert bus.disconnects == 1 and not bus.handlers
    assert service._bus is None and not service._registration_tasks


@pytest.mark.asyncio
async def test_add_match_failure_cleans_direct_start_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.fail_once = "AddMatch"
    service = install(monkeypatch, bus)
    with pytest.raises(DBusError, match="not exported"):
        await service.start()
    assert bus.disconnects == 1 and not bus.handlers
    assert service._bus is None


@pytest.mark.asyncio
async def test_registration_timeout_is_explicit_and_releases_owned_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.block = (":1.10", "default")
    service = install(monkeypatch, bus)
    monkeypatch.setattr(module, "REGISTRATION_TIMEOUT_S", 0.01)
    with pytest.raises(TimeoutError):
        await service.start()
    assert bus.disconnects == 1 and not bus.handlers
    assert service._bus is None and not service._registration_tasks
    assert any(operation[1] == "unregister" for operation in bus.operations)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "late_path,late_interface",
    [
        (module.BLUEZ_ROOT, "org.bluez.AgentManager1"),
        (module.DEFAULT_ADAPTER_PATH, "org.bluez.Adapter1"),
    ],
)
async def test_late_interface_retries_after_bounded_registration_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    late_path: str,
    late_interface: str,
) -> None:
    bus = FakeBus()
    bus.fail_always = "introspect"
    service = install(monkeypatch, bus)
    await service.start()
    assert not service._registered and bus.disconnects == 0
    attempts = len(bus.operations)
    await asyncio.sleep(0)
    assert len(bus.operations) == attempts
    for path, interface, sender in [
        (module.DEFAULT_ADAPTER_PATH + "/dev_FA_AB_BC_C7_95_64", "org.bluez.Device1", None),
        ("/org/bluez/hci1", "org.bluez.Adapter1", None),
        (late_path, late_interface, ":1.99"),
        (module.BLUEZ_ROOT, "org.bluez.Device1", None),
    ]:
        bus.interfaces_added(path, interface, sender=sender)
    await asyncio.sleep(0)
    assert len(bus.operations) == attempts
    bus.fail_always = None
    bus.interfaces_added(late_path, late_interface)
    bus.interfaces_added(late_path, late_interface)
    await settled(service)
    assert service._registered and bus.connects == 1
    assert len([op for op in bus.operations if op[1] == "register"]) == 1
    rules = [call.body[0] for call in bus.calls if call.member == "AddMatch"]
    assert f"arg0path='{late_path}'" in " ".join(rules)
    assert all("arg0path='/org/bluez/'" not in rule for rule in rules)
    await service.stop()
    assert [call.body[0] for call in bus.calls if call.member == "RemoveMatch"] == rules


@pytest.mark.asyncio
async def test_interface_event_coalesces_during_last_failed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.block = (":1.10", "introspect")
    service = install(monkeypatch, bus)
    monkeypatch.setattr(module, "REGISTRATION_RETRY_DELAYS", (0.0,))
    startup = asyncio.create_task(service.start())
    await bus.entered.wait()
    old = service._registration_task
    bus.interfaces_added(module.DEFAULT_ADAPTER_PATH, "org.bluez.Adapter1")
    bus.fail_once = "register"
    bus.block = None
    bus.release.set()
    await startup
    await asyncio.sleep(0)
    await settled(service)
    assert service._registration_task is not old
    assert service._registered and bus.connects == 1
    assert len([op for op in bus.operations if op[1] == "register"]) == 2
    await service.stop()
    assert bus.handlers == []
    assert bus.unexports == [service.agent_path]
    assert bus.calls[-1].member == "RemoveMatch"
    assert service._registration_tasks == set()


@pytest.mark.asyncio
async def test_initial_absence_retains_watch_and_recovers_without_reopening_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus("")
    service = install(monkeypatch, bus)
    await service.start()
    assert not service._registered
    assert bus.handlers and bus.disconnects == 0
    bus.change_owner(":1.30")
    await settled(service)
    assert service._registered and bus.connects == 1
    await service.stop()


@pytest.mark.asyncio
async def test_owner_signal_during_initial_query_overrides_stale_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.owner_query_change = ":1.20"
    service = install(monkeypatch, bus)
    await service.start()
    assert service._owner == ":1.20" and service._registered
    assert all(operation[0] == ":1.20" for operation in bus.operations)
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["introspect", "register", "default", "Powered", "Pairable"])
async def test_owner_change_during_registration_never_publishes_stale_readiness(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    bus = FakeBus()
    bus.block = (":1.10", stage)
    bus.ignore_cancel_once = True
    service = install(monkeypatch, bus)
    startup = asyncio.create_task(service.start())
    await bus.entered.wait()
    bus.change_owner(":1.20")
    await settled(service)
    assert service._registered and service._owner == ":1.20"
    before = len(bus.operations)
    bus.release.set()
    await startup
    assert len(bus.operations) == before
    assert service._agent_registered_owner == ":1.20"
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["introspect", "default", "Powered"])
async def test_transient_export_and_partial_registration_retry(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    bus = FakeBus()
    bus.fail_once = stage
    service = install(monkeypatch, bus)
    await service.start()
    assert service._registered
    assert service._agent_registered_owner == ":1.10"
    assert bus.connects == 1
    await service.stop()


@pytest.mark.asyncio
async def test_stop_joins_registration_and_prevents_resurrection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    service = install(monkeypatch, bus)
    await service.start()
    bus.block = (":1.20", "default")
    bus.change_owner(":1.20")
    await bus.entered.wait()
    await service.stop()
    assert not service._registered and not service._registration_tasks
    assert bus.disconnects == 1 and bus.handlers == []
    bus.change_owner(":1.30")
    await asyncio.sleep(0)
    assert not service._registered and bus.connects == 1


@pytest.mark.asyncio
async def test_snapshot_rejects_reply_after_owner_generation_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    service = install(monkeypatch, bus)
    await service.start()
    bus.snapshot_wait = True
    query = asyncio.create_task(service.managed_objects_snapshot())
    await bus.entered.wait()
    bus.change_owner(":1.20")
    await settled(service)
    bus.release.set()
    with pytest.raises(RuntimeError, match="changed during snapshot"):
        await query
    assert bus.disconnects == 0 and service._registered
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("expected", [True, False])
async def test_expected_missing_agent_is_quiet_but_unexpected_unregister_error_visible(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    expected: bool,
) -> None:
    bus = FakeBus()
    service = install(monkeypatch, bus)
    await service.start()
    bus.unregister_error = DBusError(
        "org.bluez.Error.DoesNotExist" if expected else "org.bluez.Error.Failed", "test"
    )
    await service.stop()
    assert ("agent_unregister_failed" in caplog.text) is not expected
    assert bus.disconnects == 1


DEVICE_PATH = module.DEFAULT_ADAPTER_PATH + "/dev_FA_AB_BC_C7_95_64"
OTHER_PATH = module.DEFAULT_ADAPTER_PATH + "/dev_00_11_22_33_44_55"


def selected_tree(connected: bool = True) -> dict[str, object]:
    return {
        DEVICE_PATH: {
            "org.bluez.Device1": {
                "Name": Variant("s", "INSTAX-52006924 (IOS)"),
                "Alias": Variant("s", "My Printer"),
                "Connected": Variant("b", connected),
            }
        }
    }


def emit(bus: FakeBus, message: Message) -> None:
    for handler in tuple(bus.handlers):
        assert handler(message) is None


def connection_signal(
    bus: FakeBus,
    value: Variant | None = None,
    *,
    path: str = DEVICE_PATH,
    sender: str | None = None,
) -> Message:
    return Message(
        message_type=MessageType.SIGNAL,
        sender=sender or bus.owner,
        path=path,
        interface="org.freedesktop.DBus.Properties",
        member="PropertiesChanged",
        signature="sa{sv}as",
        body=["org.bluez.Device1", {"Connected": value or Variant("b", False)}, []],
    )


def removal_signal(bus: FakeBus, path: str, interface: str) -> Message:
    return Message(
        message_type=MessageType.SIGNAL,
        sender=bus.owner,
        path="/",
        interface="org.freedesktop.DBus.ObjectManager",
        member="InterfacesRemoved",
        signature="oas",
        body=[path, [interface]],
    )


@pytest.mark.asyncio
async def test_selected_disconnect_watch_uses_one_seed_then_signals_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    disarm = await service.watch_printer_disconnect(
        "instax-52006924 (ANDROID)", lambda: edges.append(None)
    )
    calls = len(bus.calls)
    for path, value in [(OTHER_PATH, False), (DEVICE_PATH, True), (OTHER_PATH, True)]:
        emit(bus, connection_signal(bus, Variant("b", value), path=path))
    await asyncio.sleep(0)
    assert not edges and len(bus.calls) == calls
    assert service._disconnect_watches[0].changed == {DEVICE_PATH: True}
    emit(bus, connection_signal(bus))
    emit(bus, connection_signal(bus))
    emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.Device1"))
    assert edges == [None] and len(bus.calls) == calls
    disarm()
    disarm()
    assert not service._disconnect_watches
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["device", "adapter", "owner"])
async def test_selected_watch_invalidates_on_removal_or_owner_change(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    disarm = await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    emit(bus, removal_signal(bus, OTHER_PATH, "org.bluez.Device1"))
    emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.GattService1"))
    assert not edges
    if kind == "device":
        emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.Device1"))
    elif kind == "adapter":
        emit(bus, removal_signal(bus, service.adapter_path, "org.bluez.Adapter1"))
    else:
        bus.change_owner(":1.20")
        await settled(service)
    assert edges == [None]
    emit(bus, connection_signal(bus))
    assert edges == [None]
    disarm()
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["old_owner", "wrong_path", "non_boolean", "invalidated", "wrong_interface", "wrong_signature"],
)
async def test_disconnect_watch_rejects_untrusted_or_inconclusive_signal(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    signal = connection_signal(bus)
    if kind == "old_owner":
        signal.sender = ":1.99"
    elif kind == "wrong_path":
        signal.path = DEVICE_PATH + "/service0001"
    elif kind == "non_boolean":
        signal.body[1]["Connected"] = Variant("s", "false")
    elif kind == "invalidated":
        signal.body = ["org.bluez.Device1", {}, ["Connected"]]
    elif kind == "wrong_interface":
        signal.body[0] = "org.bluez.Adapter1"
    elif kind == "wrong_signature":
        signal.signature = "ss"
    emit(bus, signal)
    assert not edges
    emit(bus, connection_signal(bus))
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("removal", [False, True])
async def test_signal_during_seed_cannot_be_overwritten_by_older_connected_snapshot(
    monkeypatch: pytest.MonkeyPatch, removal: bool
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    bus.snapshot_wait = True
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    arming = asyncio.create_task(
        service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    )
    await bus.entered.wait()
    emit(
        bus,
        removal_signal(bus, DEVICE_PATH, "org.bluez.Device1")
        if removal
        else connection_signal(bus),
    )
    assert not edges
    bus.release.set()
    disarm = await arming
    assert edges == [None]
    disarm()
    await service.stop()


@pytest.mark.asyncio
async def test_seed_false_catches_disconnect_before_watch_and_rearm_is_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree(False)
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    disarm = await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert edges == [None]
    disarm()
    bus.snapshot = selected_tree(True)
    disarm = await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert edges == [None]
    emit(bus, connection_signal(bus))
    assert edges == [None, None]
    disarm()
    await service.stop()


@pytest.mark.asyncio
async def test_watch_cancel_and_stop_clear_callbacks_and_late_owner_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    bus.snapshot_wait = True
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    arming = asyncio.create_task(
        service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    )
    await bus.entered.wait()
    arming.cancel()
    with pytest.raises(asyncio.CancelledError):
        await arming
    assert not service._disconnect_watches
    bus.snapshot_wait = False
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    await service.stop()
    assert not service._disconnect_watches
    service._owner_changed(connection_signal(bus))
    bus.change_owner(":1.20")
    assert not edges


@pytest.mark.asyncio
async def test_disconnect_then_connect_during_seed_still_invalidates_cached_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    bus.snapshot_wait = True
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    arming = asyncio.create_task(
        service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    )
    await bus.entered.wait()
    emit(bus, connection_signal(bus))
    emit(bus, connection_signal(bus, Variant("b", True)))
    bus.release.set()
    disarm = await arming
    assert edges == [None]
    disarm()
    await service.stop()


@pytest.mark.asyncio
async def test_owner_loss_during_seed_notifies_and_rejects_old_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    bus.snapshot_wait = True
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    arming = asyncio.create_task(
        service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    )
    await bus.entered.wait()
    bus.change_owner(":1.20")
    await settled(service)
    assert edges == [None]
    bus.release.set()
    with pytest.raises(RuntimeError, match="changed during snapshot"):
        await arming
    assert not service._disconnect_watches
    emit(bus, connection_signal(bus, sender=":1.10"))
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
async def test_seed_timeout_removes_watch_and_preserves_pairing_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot_wait = True
    service = install(monkeypatch, bus)
    await service.start()
    monkeypatch.setattr(module, "BUS_CALL_TIMEOUT_S", 0.01)
    edges: list[None] = []
    with pytest.raises(TimeoutError):
        await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert not service._disconnect_watches and service._registered
    assert not bus.disconnects
    emit(bus, connection_signal(bus))
    assert not edges
    await service.stop()


@pytest.mark.asyncio
async def test_unknown_identity_and_disarmed_watch_do_not_emit_false_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    disarm = await service.watch_printer_disconnect("INSTAX-99999999", lambda: edges.append(None))
    emit(bus, connection_signal(bus))
    emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.Device1"))
    assert not edges
    disarm()
    disarm = await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    disarm()
    emit(bus, connection_signal(bus))
    bus.change_owner(":1.20")
    await settled(service)
    assert not edges
    await service.stop()


@pytest.mark.asyncio
async def test_callback_failure_cannot_break_owner_recovery_or_duplicate_edge(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    calls: list[None] = []

    def broken_callback() -> None:
        calls.append(None)
        raise RuntimeError("consumer failure")

    await service.watch_printer_disconnect("INSTAX-52006924", broken_callback)
    emit(bus, connection_signal(bus))
    bus.change_owner(":1.20")
    await settled(service)
    assert calls == [None] and service._registered
    assert "disconnect_callback_failed" in caplog.text
    await service.stop()


@pytest.mark.asyncio
async def test_stale_platform_identity_cannot_invalidate_live_selected_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    bus.snapshot[OTHER_PATH] = {
        "org.bluez.Device1": {
            "Alias": Variant("s", "INSTAX-52006924 (ANDROID)"),
            "Connected": Variant("b", False),
        }
    }
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert not edges and service._disconnect_watches[0].paths == {DEVICE_PATH}
    emit(bus, connection_signal(bus, path=OTHER_PATH))
    emit(bus, removal_signal(bus, OTHER_PATH, "org.bluez.Device1"))
    assert not edges
    emit(bus, connection_signal(bus))
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [False, True])
async def test_ambiguous_platform_identities_retain_conservative_polling_fallback(
    monkeypatch: pytest.MonkeyPatch, connected: bool
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree(connected)
    bus.snapshot[OTHER_PATH] = {
        "org.bluez.Device1": {
            "Name": Variant("s", "INSTAX-52006924 (ANDROID)"),
            "Connected": Variant("b", connected),
        }
    }
    service = install(monkeypatch, bus)
    await service.start()
    edges: list[None] = []
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    emit(bus, connection_signal(bus))
    assert not edges and not service._disconnect_watches[0].paths
    bus.change_owner("")
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
async def test_old_bus_lifecycle_handler_cannot_invalidate_restarted_watch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    old_handler = bus.handlers[0]
    await service.stop()
    await service.start()
    edges: list[None] = []
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    old_handler(connection_signal(bus))
    old_handler(removal_signal(bus, service.adapter_path, "org.bluez.Adapter1"))
    assert not edges
    emit(bus, connection_signal(bus))
    assert edges == [None]
    await service.stop()


def addition_signal(bus: FakeBus, path: str, properties: object) -> Message:
    return Message(
        message_type=MessageType.SIGNAL,
        sender=bus.owner,
        path="/",
        interface="org.freedesktop.DBus.ObjectManager",
        member="InterfacesAdded",
        signature="oa{sa{sv}}",
        body=[path, {"org.bluez.Device1": properties}],
    )


def tree_calls(bus: FakeBus) -> int:
    return sum(call.member == "GetManagedObjects" for call in bus.calls)


@pytest.mark.asyncio
async def test_first_watch_reuses_prior_bond_snapshot_and_connection_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree(False)
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    emit(bus, connection_signal(bus, Variant("b", True)))
    # A fresh query would now stall. Arming must complete directly from the
    # owner-scoped tree updated by signals received before any watch existed.
    bus.snapshot_wait = True
    edges: list[None] = []
    disarm = await asyncio.wait_for(
        service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None)), 0.1
    )
    assert tree_calls(bus) == 1 and not bus.entered.is_set()
    assert service._disconnect_watches[0].paths == {DEVICE_PATH}
    emit(bus, connection_signal(bus))
    assert edges == [None]
    disarm()
    # A disconnect followed by a native reconnect before arming belongs only
    # to the old session. The cache tracks the latest state, not sticky edges.
    emit(bus, connection_signal(bus, Variant("b", True)))
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert tree_calls(bus) == 1 and edges == [None]
    emit(bus, connection_signal(bus))
    assert edges == [None, None]
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["false", "missing", "ambiguous", "connected", "name", "alias", "malformed", "unknown"]
)
async def test_inconclusive_cached_tree_requires_fresh_watch_snapshot(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    if kind == "false":
        emit(bus, connection_signal(bus))
    elif kind == "missing":
        emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.Device1"))
    elif kind == "ambiguous":
        emit(
            bus,
            addition_signal(
                bus,
                OTHER_PATH,
                {"Name": Variant("s", "INSTAX-52006924(ANDROID)"), "Connected": Variant("b", True)},
            ),
        )
    elif kind == "unknown":
        emit(bus, connection_signal(bus, Variant("b", True), path=OTHER_PATH))
    else:
        signal = connection_signal(bus)
        if kind == "malformed":
            signal.body[1]["Connected"] = Variant("s", "true")
        else:
            signal.body = [
                "org.bluez.Device1",
                {},
                [{"connected": "Connected", "name": "Name", "alias": "Alias"}[kind]],
            ]
        emit(bus, signal)
    edges: list[None] = []
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert tree_calls(bus) == 2 and not edges
    assert service._disconnect_watches[0].paths == {DEVICE_PATH}
    emit(bus, connection_signal(bus))
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
async def test_cache_tracks_alias_addition_and_removal_without_extra_tree_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = {}
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    emit(
        bus,
        addition_signal(
            bus,
            DEVICE_PATH,
            {"Alias": Variant("s", "INSTAX-52006924(IOS)"), "Connected": Variant("b", True)},
        ),
    )
    emit(
        bus,
        addition_signal(
            bus,
            OTHER_PATH,
            {"Alias": Variant("s", "INSTAX-52006924(ANDROID)"), "Connected": Variant("b", False)},
        ),
    )
    emit(bus, removal_signal(bus, OTHER_PATH, "org.bluez.Device1"))
    edges: list[None] = []
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert tree_calls(bus) == 1
    assert service._disconnect_watches[0].paths == {DEVICE_PATH}
    emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.Device1"))
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "adapter", "restart", "bus"])
async def test_transport_or_owner_transition_prevents_cached_watch_arm(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    old_handler = bus.handlers[0]
    if kind == "owner":
        bus.change_owner(":1.20")
        await settled(service)
    elif kind == "adapter":
        emit(bus, removal_signal(bus, service.adapter_path, "org.bluez.Adapter1"))
    elif kind == "restart":
        await service.stop()
        await service.start()
        old_handler(connection_signal(bus, Variant("b", True)))
    else:
        bus.connected = False
    assert service._cached_watch_candidates("instax-52006924") is None
    edges: list[None] = []
    if kind == "bus":
        with pytest.raises(RuntimeError, match="not ready"):
            await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
        assert tree_calls(bus) == 1 and not service._disconnect_watches
        assert not service._device_cache_complete
        await service.stop()
        return
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: edges.append(None))
    assert tree_calls(bus) == 2 and not edges
    emit(bus, connection_signal(bus))
    assert edges == [None]
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["disconnect", "remove", "rename", "add"])
async def test_snapshot_in_flight_cannot_overwrite_newer_cached_identity_state(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    bus.snapshot_wait = True
    query = asyncio.create_task(service.managed_objects_snapshot())
    await bus.entered.wait()
    if kind == "disconnect":
        emit(bus, connection_signal(bus))
    elif kind == "remove":
        emit(bus, removal_signal(bus, DEVICE_PATH, "org.bluez.Device1"))
    elif kind == "rename":
        signal = connection_signal(bus, Variant("b", True))
        signal.body[1] = {"Name": Variant("s", "INSTAX-99999999")}
        emit(bus, signal)
    else:
        emit(
            bus,
            addition_signal(
                bus,
                OTHER_PATH,
                {
                    "Alias": Variant("s", "INSTAX-52006924(ANDROID)"),
                    "Connected": Variant("b", True),
                },
            ),
        )
    bus.release.set()
    await query
    assert service._cached_watch_candidates("instax-52006924") is None
    await service.stop()


@pytest.mark.asyncio
async def test_untrusted_owner_signals_do_not_mutate_authoritative_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    signal = connection_signal(bus, sender=":1.99")
    emit(bus, signal)
    assert service._cached_watch_candidates("instax-52006924") == {DEVICE_PATH: True}
    await service.stop()


@pytest.mark.asyncio
async def test_unknown_signal_flood_and_large_snapshot_cache_remain_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    for index in range(module.DEVICE_CACHE_LIMIT + 5):
        path = (
            module.DEFAULT_ADAPTER_PATH + f"/dev_00_11_22_33_{index // 256:02X}_{index % 256:02X}"
        )
        emit(bus, connection_signal(bus, Variant("b", True), path=path))
    assert not service._device_cache_complete and not service._device_cache
    for index in range(module.DEVICE_CACHE_LIMIT + 5):
        path = (
            module.DEFAULT_ADAPTER_PATH + f"/dev_00_11_22_33_{index // 256:02X}_{index % 256:02X}"
        )
        bus.snapshot[path] = {
            "org.bluez.Device1": {
                "Name": Variant("s", f"INSTAX-{index}"),
                "Connected": Variant("b", True),
            }
        }
    await service.managed_objects_snapshot()
    assert not service._device_cache_complete and not service._device_cache
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "properties_signature",
        "properties_shape",
        "added_signature",
        "removed_shape",
        "removed_signature",
        "added_row",
    ],
)
async def test_malformed_authenticated_device_event_degrades_cached_tree(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    await service.managed_objects_snapshot()
    if kind.startswith("properties"):
        signal = connection_signal(bus)
    elif kind.startswith("removed"):
        signal = removal_signal(bus, DEVICE_PATH, "org.bluez.Device1")
    else:
        signal = addition_signal(bus, DEVICE_PATH, {})
    if kind.endswith("signature"):
        signal.signature = "ss"
    elif kind.endswith("shape"):
        signal.body = [DEVICE_PATH]
    emit(bus, signal)
    assert service._cached_watch_candidates("instax-52006924") is None
    await service.watch_printer_disconnect("INSTAX-52006924", lambda: None)
    assert tree_calls(bus) == 2
    await service.stop()


@pytest.mark.asyncio
async def test_cache_does_not_share_mutable_snapshot_property_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FakeBus()
    bus.snapshot = selected_tree()
    service = install(monkeypatch, bus)
    await service.start()
    tree = await service.managed_objects_snapshot()
    tree[DEVICE_PATH]["org.bluez.Device1"]["Connected"].value = False
    assert service._cached_watch_candidates("instax-52006924") == {DEVICE_PATH: True}
    await service.stop()
