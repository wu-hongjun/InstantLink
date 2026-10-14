"""BlueZ pairing agent for headless Instax printer connections."""

# mypy: ignore-errors
# ruff: noqa: ANN201, F821, UP037

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.aio.message_bus import MessageBus as AioMessageBus
from dbus_fast.errors import DBusError, InterfaceNotFoundError
from dbus_fast.proxy_object import BaseProxyInterface
from dbus_fast.service import ServiceInterface, method

from instantlink_bridge.ble.instantlink import normalize_printer_name

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
DEVICE_CACHE_LIMIT = 512


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
class _DisconnectWatch:
    name: str
    callback: Callable[[], None]
    owner: str
    generation: int
    lifecycle: int
    paths: set[str]
    changed: dict[str, bool | None]
    active: bool = True
    fired: bool = False
    seeded: bool = False
    overflowed: bool = False


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
        self._message_handler: Callable[[Message], None] | None = None
        self._agent_registered_owner = ""
        self._registration_task: asyncio.Task[None] | None = None
        self._registration_tasks: set[asyncio.Task[None]] = set()
        self._registration_error: Exception | None = None
        self._registration_retry_requested = False
        self._start_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self._disconnect_watches: list[_DisconnectWatch] = []
        self._device_cache: dict[str, dict[str, object]] = {}
        self._device_cache_complete = False
        self._device_revision = 0

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

        def handle_owned_message(message: Message) -> None:
            if self._bus is bus and lifecycle == self._lifecycle and not self._stopping:
                self._owner_changed(message)

        self._message_handler = handle_owned_message
        bus.add_message_handler(handle_owned_message)
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
            "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',"
            f"member='PropertiesChanged',path_namespace='{self.adapter_path}',"
            "arg0='org.bluez.Device1'",
            "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.ObjectManager',"
            f"member='InterfacesRemoved',path='/',arg0path='{self.adapter_path}'",
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
        self._device_cache_signal(message)
        self._disconnect_signal(message)
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
        for watch in tuple(self._disconnect_watches):
            self._notify_disconnect(watch)
        self._invalidate_device_cache()
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

    def _invalidate_device_cache(self) -> None:
        self._device_cache.clear()
        self._device_cache_complete = False
        self._device_revision += 1

    @classmethod
    def _device_properties(cls, properties: object) -> dict[str, object] | None:
        if not isinstance(properties, dict):
            return None
        result = {
            key: properties[key] for key in ("Name", "Alias", "Connected") if key in properties
        }
        if cls._connected_value(result.get("Connected")) is None:
            return None
        names = [result[key] for key in ("Name", "Alias") if key in result]
        if not names or not all(
            isinstance(value, Variant) and value.signature == "s" and isinstance(value.value, str)
            for value in names
        ):
            return None
        return {key: Variant(value.signature, value.value) for key, value in result.items()}

    def _cache_device_tree(self, objects: object, revision: int) -> None:
        # Any relevant signal arriving during the call is newer than its reply.
        # Keep the signal-maintained tree, or remain incomplete, rather than
        # restoring a removed object or an earlier Connected/Name property.
        if revision != self._device_revision:
            return
        if not isinstance(objects, dict):
            self._invalidate_device_cache()
            return
        devices: dict[str, dict[str, object]] = {}
        for path, interfaces in objects.items():
            if not self._device_path(path):
                continue
            if not isinstance(interfaces, dict):
                self._invalidate_device_cache()
                return
            if "org.bluez.Device1" not in interfaces:
                continue
            properties = self._device_properties(interfaces["org.bluez.Device1"])
            if properties is None or len(devices) >= DEVICE_CACHE_LIMIT:
                self._invalidate_device_cache()
                return
            devices[path] = properties
        self._device_cache = devices
        self._device_cache_complete = True
        self._device_revision += 1

    def _device_cache_signal(self, message: Message) -> None:
        if (
            self._stopping
            or not self._owner
            or message.message_type is not MessageType.SIGNAL
            or message.sender != self._owner
        ):
            return
        if (
            message.interface == "org.freedesktop.DBus.Properties"
            and message.member == "PropertiesChanged"
        ):
            if not self._device_path(message.path):
                return
            if message.signature != "sa{sv}as" or len(message.body) != 3:
                self._invalidate_device_cache()
                return
            if message.body[0] != "org.bluez.Device1":
                return
            changed, invalidated = message.body[1:]
            if (
                not isinstance(changed, dict)
                or not isinstance(invalidated, list)
                or not all(isinstance(key, str) for key in invalidated)
            ):
                self._invalidate_device_cache()
                return
            # Full-tree callers also use Trusted to avoid redundant writes. Even
            # though the disconnect cache does not store it, a newer trust signal
            # must prevent a pending older snapshot from being accepted.
            relevant = {"Name", "Alias", "Connected", "Address", "Adapter", "Trusted"}
            if not (relevant.intersection(changed) or relevant.intersection(invalidated)):
                return
            self._device_revision += 1
            old = self._device_cache.get(message.path)
            if old is None or relevant.intersection(invalidated):
                # A previously unknown path could be another selected identity;
                # do not grow partial rows or trust a now-incomplete tree.
                self._invalidate_device_cache()
                return
            properties = self._device_properties(old | changed)
            if properties is None:
                self._invalidate_device_cache()
                return
            self._device_cache[message.path] = properties
        elif (
            message.interface == "org.freedesktop.DBus.ObjectManager"
            and message.path == "/"
            and message.member in {"InterfacesAdded", "InterfacesRemoved"}
        ):
            if len(message.body) != 2:
                self._invalidate_device_cache()
                return
            path, interfaces = message.body
            expected = "oa{sa{sv}}" if message.member == "InterfacesAdded" else "oas"
            if message.signature != expected:
                if self._device_path(path) or path == self.adapter_path:
                    self._invalidate_device_cache()
                return
            if message.member == "InterfacesAdded" and message.signature == "oa{sa{sv}}":
                if isinstance(interfaces, dict) and "org.bluez.Adapter1" in interfaces:
                    # Adapter inventory also determines mutation callers' scope.
                    self._invalidate_device_cache()
                    return
                if not self._device_path(path):
                    return
                if not isinstance(interfaces, dict):
                    self._invalidate_device_cache()
                    return
                if "org.bluez.Device1" not in interfaces:
                    return
                self._device_revision += 1
                properties = self._device_properties(interfaces["org.bluez.Device1"])
                if properties is None or (
                    path not in self._device_cache and len(self._device_cache) >= DEVICE_CACHE_LIMIT
                ):
                    self._invalidate_device_cache()
                    return
                self._device_cache[path] = properties
            elif message.member == "InterfacesRemoved" and message.signature == "oas":
                if not isinstance(interfaces, list) or not all(
                    isinstance(key, str) for key in interfaces
                ):
                    if self._device_path(path) or path == self.adapter_path:
                        self._invalidate_device_cache()
                    return
                if "org.bluez.Adapter1" in interfaces:
                    self._invalidate_device_cache()
                elif self._device_path(path) and "org.bluez.Device1" in interfaces:
                    self._device_revision += 1
                    self._device_cache.pop(path, None)

    def _matching_devices(self, name: str, objects: object) -> dict[str, bool | None]:
        if not isinstance(objects, dict):
            raise ValueError("invalid BlueZ object snapshot tree")
        candidates: dict[str, bool | None] = {}
        for path, interfaces in objects.items():
            if not self._device_path(path) or not isinstance(interfaces, dict):
                continue
            properties = interfaces.get("org.bluez.Device1")
            if not isinstance(properties, dict):
                continue
            names = [properties.get("Name"), properties.get("Alias")]
            if any(
                isinstance(value, Variant)
                and value.signature == "s"
                and isinstance(value.value, str)
                and normalize_printer_name(value.value).casefold() == name
                for value in names
            ):
                candidates[path] = self._connected_value(properties.get("Connected"))
        return candidates

    def _cached_watch_candidates(self, name: str) -> dict[str, bool | None] | None:
        if self._bus is not None and not self._bus.connected:
            self._invalidate_device_cache()
            return None
        if (
            not self._device_cache_complete
            or self._bus is None
            or not self._registered
            or self._stopping
        ):
            return None
        objects = {path: {"org.bluez.Device1": row} for path, row in self._device_cache.items()}
        candidates = self._matching_devices(name, objects)
        # Only a single live identity can establish the just-successful session.
        # Missing, false-only and ambiguous cached identities require a fresh read.
        if sum(value is True for value in candidates.values()) != 1:
            return None
        return candidates

    def _device_path(self, path: object) -> bool:
        return (
            isinstance(path, str)
            and re.fullmatch(
                re.escape(self.adapter_path) + r"/dev_[0-9A-Fa-f]{2}(?:_[0-9A-Fa-f]{2}){5}", path
            )
            is not None
        )

    @staticmethod
    def _connected_value(value: object) -> bool | None:
        if isinstance(value, Variant) and value.signature == "b" and type(value.value) is bool:
            return value.value
        return None

    def _watch_current(self, watch: _DisconnectWatch) -> bool:
        return (
            watch.active
            and not self._stopping
            and watch.lifecycle == self._lifecycle
            and watch.owner == self._owner
            and watch.generation == self._generation
        )

    def _notify_disconnect(self, watch: _DisconnectWatch) -> None:
        if not self._watch_current(watch) or watch.fired:
            return
        watch.fired = True
        try:
            watch.callback()
        except Exception:
            LOGGER.exception("bluetooth.disconnect_callback_failed")

    def _disconnect_signal(self, message: Message) -> None:
        if (
            self._stopping
            or not self._disconnect_watches
            or not self._owner
            or message.message_type is not MessageType.SIGNAL
            or message.sender != self._owner
        ):
            return
        path: str
        connected: bool | None
        if (
            message.interface == "org.freedesktop.DBus.Properties"
            and message.member == "PropertiesChanged"
            and message.signature == "sa{sv}as"
            and len(message.body) == 3
            and message.body[0] == "org.bluez.Device1"
            and isinstance(message.body[1], dict)
            and isinstance(message.body[2], list)
            and all(isinstance(item, str) for item in message.body[2])
            and self._device_path(message.path)
        ):
            connected = self._connected_value(message.body[1].get("Connected"))
            if connected is None:
                return
            path = message.path
        elif (
            message.interface == "org.freedesktop.DBus.ObjectManager"
            and message.member == "InterfacesRemoved"
            and message.path == "/"
            and message.signature == "oas"
            and len(message.body) == 2
            and isinstance(message.body[1], list)
            and all(isinstance(item, str) for item in message.body[1])
        ):
            path, interfaces = message.body
            if path == self.adapter_path and "org.bluez.Adapter1" in interfaces:
                for watch in tuple(self._disconnect_watches):
                    self._notify_disconnect(watch)
                return
            if not self._device_path(path) or "org.bluez.Device1" not in interfaces:
                return
            connected = None
        else:
            return
        for watch in tuple(self._disconnect_watches):
            if (
                not self._watch_current(watch)
                or watch.fired
                or (watch.seeded and path not in watch.paths)
            ):
                continue
            # Keep changes received while the initial tree is in flight. Its
            # older reply must never overwrite a newer disconnect/removal.
            if path not in watch.changed and len(watch.changed) >= DEVICE_CACHE_LIMIT:
                # Dropping a pending row could hide the selected session's loss.
                # Abandon this registration and retain ordinary status polling.
                watch.overflowed = True
                watch.active = False
                watch.changed.clear()
                self._disconnect_watches.remove(watch)
                continue
            if path not in watch.changed or watch.changed[path] is True:
                watch.changed[path] = connected
            if path in watch.paths and connected is not True:
                self._notify_disconnect(watch)

    async def watch_printer_disconnect(
        self, printer_name: str, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Arm one selected Printer session after a successful status request.

        A complete owner-scoped, signal-maintained tree usually resolves its
        physical BlueZ path immediately. Missing or ambiguous identities retain
        the bounded fresh-tree fallback; status polling remains independent.
        """
        if self._bus is None or not self._registered or self._stopping:
            raise RuntimeError("BlueZ pairing agent is not ready")
        normalized_name = normalize_printer_name(printer_name).casefold()
        if not normalized_name:
            raise ValueError("selected Printer name is empty")
        watch = _DisconnectWatch(
            normalized_name,
            callback,
            self._owner,
            self._generation,
            self._lifecycle,
            set(),
            {},
        )
        self._disconnect_watches.append(watch)

        def disarm() -> None:
            watch.active = False
            if watch in self._disconnect_watches:
                self._disconnect_watches.remove(watch)

        try:
            async with asyncio.timeout(BUS_CALL_TIMEOUT_S):
                candidates = self._cached_watch_candidates(watch.name)
                if candidates is None:
                    objects = await self.managed_objects_snapshot()
                    candidates = self._matching_devices(watch.name, objects)
            if watch.overflowed:
                raise RuntimeError("BlueZ disconnect watch pending changes exceeded limit")
            if not self._watch_current(watch):
                disarm()
                return disarm
            live_paths = [path for path, connected in candidates.items() if connected is True]
            # BlueZ can retain a disconnected IOS/ANDROID identity for the same
            # Printer. Only its one live identity belongs to the current session.
            # If there is no live identity, a unique false-only row can establish
            # that the session ended during arming. Ambiguous identities retain
            # status polling rather than invalidating a healthy native session.
            if len(live_paths) == 1:
                watch.paths.add(live_paths[0])
            elif not live_paths and len(candidates) == 1:
                watch.paths.update(candidates)
            for path in watch.paths:
                connected = watch.changed.get(path, candidates[path])
                if connected is False or (path in watch.changed and connected is None):
                    self._notify_disconnect(watch)
            watch.seeded = True
            # Once paths are resolved, unrelated devices need no retained state.
            watch.changed = {
                path: state for path, state in watch.changed.items() if path in watch.paths
            }
            return disarm
        except BaseException:
            disarm()
            raise

    async def managed_objects_snapshot(self) -> object:
        """Read current BlueZ objects on the agent's existing connection.

        Callers impose their own bounded deadline. Cancelling this read must
        leave the shared pairing agent and other bus calls operational.
        """
        if self._bus is None or not self._registered or not self._owner or not self._bus.connected:
            raise RuntimeError("BlueZ pairing agent is not ready")
        bus = self._bus
        owner = self._owner
        generation = self._generation
        for _attempt in range(2):
            revision = self._device_revision
            reply = await bus.call(
                Message(
                    destination=owner,
                    path="/",
                    interface="org.freedesktop.DBus.ObjectManager",
                    member="GetManagedObjects",
                )
            )
            if (
                not self._current(bus, owner, generation)
                or not self._registered
                or not bus.connected
            ):
                raise RuntimeError("BlueZ pairing agent changed during snapshot")
            if (
                reply is None
                or reply.message_type is not MessageType.METHOD_RETURN
                or reply.signature != "a{oa{sa{sv}}}"
                or len(reply.body) != 1
            ):
                raise ValueError("invalid BlueZ object snapshot reply")
            if reply.sender != owner:
                raise ValueError("BlueZ object snapshot reply has wrong owner")
            # A reader can resolve the reply Future and process later signals
            # before this coroutine resumes. Reject that tree for callers too,
            # including consumers that need full Address/Adapter properties.
            if revision != self._device_revision:
                continue
            self._cache_device_tree(reply.body[0], revision)
            return reply.body[0]
        raise RuntimeError("BlueZ device state changed during snapshot")

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
        for watch in self._disconnect_watches:
            watch.active = False
        self._disconnect_watches.clear()
        self._invalidate_device_cache()
        self._lifecycle += 1
        self._generation += 1
        self._registered = False
        bus = self._bus
        try:
            if bus is not None and self._handler_installed and self._message_handler is not None:
                bus.remove_message_handler(self._message_handler)
            self._message_handler = None
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
