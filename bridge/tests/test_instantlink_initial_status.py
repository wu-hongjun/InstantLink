from __future__ import annotations

import asyncio
import ctypes
import threading
from typing import Any, cast

import pytest

from instantlink_bridge.ble.instantlink import (
    ERROR_BLE,
    ERROR_NO_FILM,
    ERROR_PRINTER_NOT_FOUND,
    InstantLinkBackend,
    InstantLinkBleError,
    InstantLinkPrinterNotFoundError,
    _configure_library,
)
from instantlink_bridge.ble.models import PrinterModel


class _LegacyLibrary:
    def __init__(self) -> None:
        self.name: bytes | None = None
        self.closed = False
        self.connect_calls = self.status_calls = self.disconnect_calls = self.battery_calls = 0
        self.values = (70, 6, 1, 321)
        self.status_rc = 0

    def instantlink_connect_named(self, name: bytes, duration: int) -> int:
        assert duration >= 1
        self.connect_calls += 1
        self.name, self.closed = name, False
        return 0

    def instantlink_status(self, *outputs: object) -> int:
        self.status_calls += 1
        if self.status_rc < 0:
            return self.status_rc
        self.write_outputs(outputs, self.values)
        return 0

    @staticmethod
    def write_outputs(outputs: tuple[object, ...], values: tuple[int, int, int, int]) -> None:
        for output, value in zip(outputs, values, strict=True):
            cast(Any, output)._obj.value = value

    def instantlink_device_name(self, out: object, _length: int) -> int:
        if self.name is None:
            return ERROR_PRINTER_NOT_FOUND
        cast(Any, out).value = self.name
        return len(self.name)

    def instantlink_device_model(self, out: object, _length: int) -> int:
        cast(Any, out).value = b"Square Link"
        return len(b"Square Link")

    def instantlink_is_connected(self) -> int:
        return int(self.name is not None and not self.closed)

    def instantlink_disconnect(self) -> int:
        self.disconnect_calls += 1
        self.name = None
        return 0

    def instantlink_battery(self) -> int:
        self.battery_calls += 1
        return self.values[0]


class _InitialStatusLibrary(_LegacyLibrary):
    def __init__(self) -> None:
        super().__init__()
        self.initial_calls = self.initial_rc = 0

    def instantlink_connect_named_with_status(
        self, name: bytes, duration: int, progress: object, *outputs: object
    ) -> int:
        assert duration >= 1
        self.initial_calls += 1
        emit = cast(Any, progress)
        for stage in (0, 3, 5, 6, 7, 8):
            emit(stage, None)
        if self.initial_rc < 0:
            self.write_outputs(outputs, (99, 99, 1, 999))
            emit(10, None)
            return self.initial_rc
        self.name, self.closed = name, False
        self.write_outputs(outputs, self.values)
        emit(9, name)
        return 0


def _backend(library: _LegacyLibrary) -> InstantLinkBackend:
    backend = InstantLinkBackend()
    backend._lib = cast(Any, library)
    return backend


@pytest.mark.asyncio
async def test_fresh_connect_returns_initial_status_once_and_later_polls_are_fresh() -> None:
    library = _InitialStatusLibrary()
    backend = _backend(library)
    initial = await backend.status("INSTAX-52006924 (IOS)", scan_duration_s=0)
    assert initial.name == "INSTAX-52006924 (IOS)"
    assert initial.model is PrinterModel.SQUARE
    assert (initial.battery, initial.film_remaining, initial.is_charging, initial.print_count) == (
        70,
        6,
        True,
        321,
    )
    assert (library.initial_calls, library.connect_calls, library.status_calls) == (1, 0, 0)
    library.values = (65, 5, 0, 322)
    later = await backend.status("INSTAX-52006924")
    assert (later.battery, later.film_remaining, later.is_charging, later.print_count) == (
        65,
        5,
        False,
        322,
    )
    assert (library.initial_calls, library.status_calls) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("closure", ["disconnect", "known_closed", "selection"])
async def test_reconnect_and_selection_use_the_new_connections_status(closure: str) -> None:
    library = _InitialStatusLibrary()
    backend = _backend(library)
    await backend.status("INSTAX-52006924")
    library.values = (40, 0, 0, 401)
    name = "INSTAX-52006924"
    if closure == "disconnect":
        await backend.disconnect()
    elif closure == "known_closed":
        library.closed = True
    else:
        name = "INSTAX-12345678"
    status = await backend.status(name)
    assert status.name == name
    assert (status.battery, status.film_remaining, status.is_charging, status.print_count) == (
        40,
        0,
        False,
        401,
    )
    assert library.initial_calls == 2
    assert library.status_calls == library.battery_calls == 0


@pytest.mark.asyncio
async def test_legacy_library_keeps_connect_then_status_and_no_film_fallback() -> None:
    library = _LegacyLibrary()
    backend = _backend(library)
    status = await backend.status("INSTAX-52006924")
    assert status.print_count == 321
    assert (library.connect_calls, library.status_calls) == (1, 1)
    library.status_rc = ERROR_NO_FILM
    status = await backend.status("INSTAX-52006924")
    assert status.battery == 70
    assert status.film_remaining == 0
    assert status.print_count is None
    assert (library.connect_calls, library.status_calls, library.battery_calls) == (1, 2, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("rc", [ERROR_BLE, ERROR_PRINTER_NOT_FOUND])
async def test_initial_status_failure_keeps_stage_and_never_retries_legacy_connect(rc: int) -> None:
    library = _InitialStatusLibrary()
    library.initial_rc = rc
    backend = _backend(library)
    error = InstantLinkBleError if rc == ERROR_BLE else InstantLinkPrinterNotFoundError
    with pytest.raises(error) as captured:
        await backend.status("INSTAX-52006924")
    assert captured.value.connect_failure_stage == 8
    assert (library.initial_calls, library.connect_calls, library.status_calls) == (1, 0, 0)
    assert library.disconnect_calls == 1
    library.initial_rc = 0
    library.values = (55, 2, 0, 500)
    status = await backend.status("INSTAX-52006924")
    assert status.print_count == 500
    assert library.initial_calls == 2
    assert backend._consecutive_status_failures == 0


def test_print_connection_does_not_consume_or_retain_initial_status() -> None:
    library = _InitialStatusLibrary()
    backend = _backend(library)
    backend._ensure_connected_blocking("INSTAX-52006924", scan_duration_s=5)
    assert (library.connect_calls, library.initial_calls, library.status_calls) == (1, 0, 0)
    library.values = (60, 4, 0, 322)
    status = backend._status_blocking("INSTAX-52006924", 5)
    assert status.print_count == 322
    assert (library.connect_calls, library.initial_calls, library.status_calls) == (1, 0, 1)


@pytest.mark.asyncio
async def test_cancelled_initial_connect_holds_serialization_and_next_poll_is_fresh() -> None:
    entered, release = threading.Event(), threading.Event()

    class BlockingLibrary(_InitialStatusLibrary):
        def instantlink_connect_named_with_status(
            self, name: bytes, duration: int, progress: object, *outputs: object
        ) -> int:
            entered.set()
            assert release.wait(2)
            return super().instantlink_connect_named_with_status(name, duration, progress, *outputs)

    library = BlockingLibrary()
    backend = _backend(library)
    initial = asyncio.create_task(backend.status("INSTAX-52006924"))
    later: asyncio.Task[object] | None = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        initial.cancel()
        await asyncio.sleep(0)
        later = asyncio.create_task(backend.status("INSTAX-52006924"))
        await asyncio.sleep(0)
        assert backend._lock.locked()
        assert library.status_calls == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(initial, 1)
        status = await asyncio.wait_for(later, 1)
        assert status == backend._status_blocking("INSTAX-52006924", 5)
        assert (library.initial_calls, library.status_calls) == (1, 2)
    finally:
        release.set()
        await asyncio.gather(initial, *([later] if later else []), return_exceptions=True)


def test_optional_connect_status_binding_uses_the_existing_signed_status_slots() -> None:
    class Function:
        argtypes: list[object]
        restype: object

    class Library:
        def __init__(self) -> None:
            self.functions: dict[str, Function] = {}

        def __getattr__(self, name: str) -> Function:
            return self.functions.setdefault(name, Function())

    library = Library()
    _configure_library(cast(Any, library))
    function = library.functions["instantlink_connect_named_with_status"]
    assert function.argtypes[:2] == [ctypes.c_char_p, ctypes.c_int]
    assert function.argtypes[3:] == [ctypes.POINTER(ctypes.c_int)] * 4
    assert function.restype is ctypes.c_int
