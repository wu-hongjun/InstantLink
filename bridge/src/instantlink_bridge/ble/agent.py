"""BlueZ pairing agent for headless Instax printer connections."""

# mypy: ignore-errors
# ruff: noqa: ANN201, F821, UP037

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.aio.message_bus import MessageBus as AioMessageBus
from dbus_fast.errors import DBusError, InterfaceNotFoundError
from dbus_fast.proxy_object import BaseProxyInterface
from dbus_fast.service import ServiceInterface, method

LOGGER = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
BLUEZ_ROOT = "/org/bluez"
DEFAULT_ADAPTER_PATH = "/org/bluez/hci0"
DEFAULT_AGENT_PATH = "/com/instantlink_bridge/agent"
OWNER_MATCH = (
    "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',"
    "member='NameOwnerChanged',path='/org/freedesktop/DBus',arg0='org.bluez'"
)
REGISTRATION_TIMEOUT_S = 10.0
REGISTRATION_RETRY_DELAYS = (0.0, 0.2, 0.5, 1.0, 2.0)
BUS_CALL_TIMEOUT_S = 3.0


class NoInputNoOutputAgent(ServiceInterface):
    """Minimal BlueZ Agent1 implementation for Just-Works BLE bonding."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")

    @method()
    def Release(self):
        """BlueZ released the agent."""

        LOGGER.info("bluetooth.agent_released")

    @method()
    def RequestPinCode(self, device: "o") -> "s":
        """Reject legacy PIN pairing; Instax Link uses BLE Just Works."""

        LOGGER.info("bluetooth.agent_request_pin_code device=%s", device)
        return "0000"

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):
        """Accept display callbacks without UI interaction."""

        LOGGER.info("bluetooth.agent_display_pin_code device=%s pincode=%s", device, pincode)

    @method()
    def RequestPasskey(self, device: "o") -> "u":
        """Return a dummy passkey for stacks that ask despite NoInputNoOutput."""

        LOGGER.info("bluetooth.agent_request_passkey device=%s", device)
        return 0

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        """Accept display callbacks without UI interaction."""

        LOGGER.info(
            "bluetooth.agent_display_passkey device=%s passkey=%s entered=%s",
            device,
            passkey,
            entered,
        )

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):
        """Auto-confirm Just-Works pairing."""

        LOGGER.info("bluetooth.agent_confirm device=%s passkey=%s", device, passkey)

    @method()
    def RequestAuthorization(self, device: "o"):
        """Authorize a pairing request."""

        LOGGER.info("bluetooth.agent_authorize device=%s", device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):
        """Authorize service access for the selected printer."""

        LOGGER.info("bluetooth.agent_authorize_service device=%s uuid=%s", device, uuid)

    @method()
    def Cancel(self):
        """BlueZ cancelled the current pairing request."""

        LOGGER.info("bluetooth.agent_cancel")


@dataclass
class BluezAgentService:
    """Register a process-owned BlueZ NoInputNoOutput agent."""

    adapter_path: str = DEFAULT_ADAPTER_PATH
    agent_path: str = DEFAULT_AGENT_PATH

    def __post_init__(self) -> None:
        self._bus: AioMessageBus | None = None
        self._agent_manager: BaseProxyInterface | None = None
        self._registered = False
        self._owner = ""
        self._generation = 0
        self._lifecycle = 0
        self._stopping = False
        self._watch_installed = False
        self._installed_matches: list[str] = []
        self._handler_installed = False
        self._agent_registered_owner = ""
        self._registration_task: asyncio.Task[None] | None = None
        self._registration_tasks: set[asyncio.Task[None]] = set()
        self._registration_error: Exception | None = None
        self._registration_retry_requested = False
        self._start_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()

    async def start(self) -> None:
        """Export an agent and watch BlueZ ownership on the same system bus."""
        async with self._start_lock:
            try:
                await self._start_owned()
            except BaseException:
                await self.stop()
                raise

    async def _start_owned(self) -> None:
        if self._bus is not None:
            return
        self._stopping = False
        self._lifecycle += 1
        lifecycle = self._lifecycle
        bus = MessageBus(bus_type=BusType.SYSTEM)
        try:
            await bus.connect()
        except BaseException:
            bus.disconnect()
            raise
        if self._stopping or lifecycle != self._lifecycle:
            bus.disconnect()
            return
        self._bus = bus
        bus.export(self.agent_path, NoInputNoOutputAgent())
        bus.add_message_handler(self._owner_changed)
        self._handler_installed = True
        for rule in self._match_rules():
            await self._daemon_call(bus, "AddMatch", "s", [rule])
            if self._bus is not bus or self._stopping:
                return
            self._installed_matches.append(rule)
        self._watch_installed = True
        generation = self._generation
        try:
            reply = await self._daemon_call(bus, "GetNameOwner", "s", [BLUEZ_SERVICE])
            owner = reply.body[0] if reply.signature == "s" and len(reply.body) == 1 else None
            if not isinstance(owner, str) or not owner.startswith(":"):
                raise ValueError("invalid BlueZ owner reply")
        except DBusError as error:
            if error.type != "org.freedesktop.DBus.Error.NameHasNoOwner":
                raise
            owner = ""
        if self._bus is not bus or self._stopping:
            return
        # A signal received during GetNameOwner is newer than its reply.
        if generation == self._generation:
            self._set_owner(owner)
        task = self._registration_task
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                # Owner loss cancelled this registration; the watcher owns
                # any replacement task and the exported agent stays alive.
            if (
                task is self._registration_task
                and self._registration_error is not None
                and not self._registration_can_wait_for_interface(self._registration_error)
            ):
                raise self._registration_error

    def _match_rules(self) -> tuple[str, ...]:
        prefix = (
            "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.ObjectManager',"
            "member='InterfacesAdded',path='/'"
        )
        return (
            OWNER_MATCH,
            f"{prefix},arg0path='{BLUEZ_ROOT}'",
            f"{prefix},arg0path='{self.adapter_path}'",
        )

    @staticmethod
    def _registration_can_wait_for_interface(error: Exception) -> bool:
        return isinstance(error, InterfaceNotFoundError) or (
            isinstance(error, DBusError)
            and error.type
            in {
                "org.freedesktop.DBus.Error.UnknownObject",
                "org.freedesktop.DBus.Error.UnknownInterface",
                "org.freedesktop.DBus.Error.NameHasNoOwner",
                "org.freedesktop.DBus.Error.ServiceUnknown",
                "org.bluez.Error.NotReady",
            }
        )

    async def _daemon_call(
        self, bus: AioMessageBus, member: str, signature: str, body: list[object]
    ) -> Message:
        async with asyncio.timeout(BUS_CALL_TIMEOUT_S):
            reply = await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member=member,
                    signature=signature,
                    body=body,
                )
            )
        if reply is None:
            raise RuntimeError(f"D-Bus {member} returned no reply")
        if reply.message_type is MessageType.ERROR:
            raise DBusError(
                reply.error_name or "org.freedesktop.DBus.Error.Failed",
                str(reply.body[0]) if reply.body else member,
            )
        if reply.message_type is not MessageType.METHOD_RETURN:
            raise ValueError(f"invalid D-Bus {member} reply")
        return reply

    def _owner_changed(self, message: Message) -> None:
        if message.member == "InterfacesAdded":
            self._interfaces_added(message)
            return
        if (
            self._stopping
            or message.message_type is not MessageType.SIGNAL
            or message.sender != "org.freedesktop.DBus"
            or message.path != "/org/freedesktop/DBus"
            or message.interface != "org.freedesktop.DBus"
            or message.member != "NameOwnerChanged"
            or message.signature != "sss"
            or len(message.body) != 3
            or message.body[0] != BLUEZ_SERVICE
            or not all(isinstance(value, str) for value in message.body)
        ):
            return
        owner = message.body[2]
        if owner and not owner.startswith(":"):
            return
        self._set_owner(owner)

    def _interfaces_added(self, message: Message) -> None:
        if (
            self._stopping
            or not self._owner
            or self._registered
            or message.message_type is not MessageType.SIGNAL
            or message.sender != self._owner
            or message.path != "/"
            or message.interface != "org.freedesktop.DBus.ObjectManager"
            or message.signature != "oa{sa{sv}}"
            or len(message.body) != 2
            or not isinstance(message.body[1], dict)
        ):
            return
        path, interfaces = message.body
        relevant = (
            path == BLUEZ_ROOT and isinstance(interfaces.get("org.bluez.AgentManager1"), dict)
        ) or (path == self.adapter_path and isinstance(interfaces.get("org.bluez.Adapter1"), dict))
        if not relevant:
            return
        if self._registration_task is not None and not self._registration_task.done():
            self._registration_retry_requested = True
        else:
            self._schedule_registration()

    def _set_owner(self, owner: str) -> None:
        if owner == self._owner or self._stopping:
            return
        self._owner = owner
        self._generation += 1
        self._registered = False
        self._agent_manager = None
        self._agent_registered_owner = ""
        self._registration_error = None
        self._registration_retry_requested = False
        if self._registration_task is not None:
            self._registration_task.cancel()
        self._registration_task = None
        if not owner or self._bus is None:
            LOGGER.info("bluetooth.agent_owner_lost")
            return
        self._schedule_registration()

    def _schedule_registration(self) -> None:
        if self._stopping or self._bus is None or not self._owner or self._registered:
            return
        self._registration_retry_requested = False
        self._registration_error = None
        task = asyncio.create_task(
            self._register_owner(self._bus, self._owner, self._generation),
            name="bluetooth.agent_register",
        )
        self._registration_task = task
        self._registration_tasks.add(task)
        task.add_done_callback(self._registration_finished)

    def _registration_finished(self, task: asyncio.Task[None]) -> None:
        self._registration_tasks.discard(task)
        if task is self._registration_task and self._registration_retry_requested:
            self._schedule_registration()

    def _current(self, bus: AioMessageBus, owner: str, generation: int) -> bool:
        return (
            not self._stopping
            and self._bus is bus
            and self._owner == owner
            and self._generation == generation
        )

    async def _register_owner(self, bus: AioMessageBus, owner: str, generation: int) -> None:
        try:
            async with asyncio.timeout(REGISTRATION_TIMEOUT_S):
                for index, delay in enumerate(REGISTRATION_RETRY_DELAYS):
                    if delay:
                        await asyncio.sleep(delay)
                    if not self._current(bus, owner, generation):
                        return
                    try:
                        await self._register_attempt(bus, owner, generation)
                        return
                    except Exception:
                        if not self._current(bus, owner, generation):
                            return
                        if index == len(REGISTRATION_RETRY_DELAYS) - 1:
                            raise
                        LOGGER.debug(
                            "bluetooth.agent_registration_retry owner=%s", owner, exc_info=True
                        )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._current(bus, owner, generation):
                self._registration_error = error
                LOGGER.exception("bluetooth.agent_registration_failed owner=%s", owner)

    async def _register_attempt(self, bus: AioMessageBus, owner: str, generation: int) -> None:
        manager = await self._proxy_interface(BLUEZ_ROOT, "org.bluez.AgentManager1", bus, owner)
        if not self._current(bus, owner, generation):
            return
        self._agent_manager = manager
        try:
            await manager.call_register_agent(self.agent_path, "NoInputNoOutput")
        except DBusError as error:
            if error.type != "org.bluez.Error.AlreadyExists":
                raise
        if not self._current(bus, owner, generation):
            return
        self._agent_registered_owner = owner
        await manager.call_request_default_agent(self.agent_path)
        if not self._current(bus, owner, generation):
            return
        properties = await self._proxy_interface(
            self.adapter_path,
            "org.freedesktop.DBus.Properties",
            bus,
            owner,
        )
        for name, value in [
            ("Powered", Variant("b", True)),
            ("Pairable", Variant("b", True)),
            ("PairableTimeout", Variant("u", 0)),
        ]:
            if not self._current(bus, owner, generation):
                return
            await properties.call_set("org.bluez.Adapter1", name, value)
        if not self._current(bus, owner, generation):
            return
        self._registered = True
        LOGGER.info(
            "bluetooth.agent_registered path=%s adapter=%s owner=%s",
            self.agent_path,
            self.adapter_path,
            owner,
        )

    async def managed_objects_snapshot(self) -> object:
        """Read current BlueZ objects on the agent's existing connection.

        Callers impose their own bounded deadline. Cancelling this read must
        leave the shared pairing agent and other bus calls operational.
        """
        if self._bus is None or not self._registered:
            raise RuntimeError("BlueZ pairing agent is not ready")
        bus = self._bus
        owner = self._owner
        generation = self._generation
        reply = await bus.call(
            Message(
                destination=owner or BLUEZ_SERVICE,
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )
        )
        if not self._current(bus, owner, generation) or not self._registered:
            raise RuntimeError("BlueZ pairing agent changed during snapshot")
        if (
            reply is None
            or reply.message_type is not MessageType.METHOD_RETURN
            or reply.signature != "a{oa{sa{sv}}}"
            or len(reply.body) != 1
        ):
            raise ValueError("invalid BlueZ object snapshot reply")
        return reply.body[0]

    async def stop(self) -> None:
        """Remove ownership watch, join registration, and close the owned bus."""
        async with self._stop_lock:
            cleanup = asyncio.create_task(self._stop_owned(), name="bluetooth.agent_stop")
            cancelled = False
            while True:
                try:
                    await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError:
                    if cleanup.done():
                        cleanup.result()
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError

    async def _stop_owned(self) -> None:
        self._stopping = True
        self._lifecycle += 1
        self._generation += 1
        self._registered = False
        bus = self._bus
        try:
            if bus is not None and self._handler_installed:
                bus.remove_message_handler(self._owner_changed)
            self._handler_installed = False
            tasks = tuple(self._registration_tasks)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._registration_tasks.clear()
            self._registration_task = None
            if self._agent_manager is not None and self._agent_registered_owner == self._owner:
                try:
                    async with asyncio.timeout(BUS_CALL_TIMEOUT_S):
                        await self._agent_manager.call_unregister_agent(self.agent_path)
                except DBusError as error:
                    if error.type in {
                        "org.bluez.Error.DoesNotExist",
                        "org.freedesktop.DBus.Error.NameHasNoOwner",
                        "org.freedesktop.DBus.Error.ServiceUnknown",
                    }:
                        LOGGER.debug("bluetooth.agent_already_removed path=%s", self.agent_path)
                    else:
                        LOGGER.exception(
                            "bluetooth.agent_unregister_failed path=%s", self.agent_path
                        )
                except Exception:
                    LOGGER.exception("bluetooth.agent_unregister_failed path=%s", self.agent_path)
            if bus is not None:
                for rule in self._installed_matches:
                    try:
                        await self._daemon_call(bus, "RemoveMatch", "s", [rule])
                    except Exception:
                        LOGGER.debug("bluetooth.agent_watch_remove_failed", exc_info=True)
        finally:
            try:
                if bus is not None:
                    bus.unexport(self.agent_path)
            finally:
                try:
                    if bus is not None:
                        bus.disconnect()
                finally:
                    self._watch_installed = False
                    self._installed_matches.clear()
                    self._handler_installed = False
                    self._bus = None
                    self._agent_manager = None
                    self._agent_registered_owner = ""
                    self._owner = ""

    async def _proxy_interface(
        self,
        path: str,
        interface_name: str,
        bus: AioMessageBus,
        owner: str,
    ) -> BaseProxyInterface:
        introspection = await bus.introspect(owner, path)
        proxy = bus.get_proxy_object(owner, path, introspection)
        return proxy.get_interface(interface_name)
