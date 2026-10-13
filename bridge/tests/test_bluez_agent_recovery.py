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

    async def connect(self) -> FakeBus:
        self.connects += 1
        await self.stage("bus", "connect")
        return self

    def export(self, path: str, _interface: object) -> None:
        self.exports.append(path)

    def unexport(self, path: str) -> None:
        self.unexports.append(path)

    def disconnect(self) -> None:
        self.disconnects += 1

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
                body=[{}],
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
    assert [call.member for call in bus.calls] == ["AddMatch"] * 3 + ["GetNameOwner"]
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
