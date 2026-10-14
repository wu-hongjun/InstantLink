"""Native idle startup does not initialize the optional diagnostic print graph."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _clean_python(source: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    subprocess.run([sys.executable, "-c", source], env=env, check=True, timeout=30)


def test_native_import_and_unused_cleanup_do_not_load_diagnostics() -> None:
    _clean_python(
        """
import asyncio
import sys
import typing
from instantlink_bridge import app
from instantlink_bridge.ui import status

optional = [
    "instantlink_bridge.ble.client", "instantlink_bridge.ble.instax",
    "instantlink_bridge.ble.protocol", "instantlink_bridge.ble.commands",
    "instantlink_bridge.ble.session", "instantlink_bridge.imaging.pipeline",
    "instantlink_bridge.imaging.postprocess",
]
assert not [name for name in optional if name in sys.modules]
# Public callable annotations resolve without loading fallback implementation classes.
for function in [status.BlePrinterStatusProvider.__init__, status.connect_instax_printer,
                 app.scan_instax_printers, app.print_file_to_printer_bleak,
                 app.read_exif_datestamp_text]:
    typing.get_type_hints(function)
async def close():
    await app.close_default_ble_session_manager()
    await app.close_default_image_preparation_worker()
asyncio.run(close())
assert not [name for name in optional if name in sys.modules]
"""
    )


def test_original_printer_record_and_error_exports_keep_identity() -> None:
    from instantlink_bridge.ble import client, instax, session, types

    assert client.DiscoveredPrinter is types.DiscoveredPrinter
    assert session.PrinterEndpoint is types.PrinterEndpoint
    for name in (
        "PrinterStatus",
        "PrinterError",
        "UnexpectedResponseError",
        "PrintRejectedError",
        "NoFilmError",
        "CoverOpenError",
        "PrinterBusyError",
        "LowPrinterBatteryError",
    ):
        assert getattr(instax, name) is getattr(types, name)
    selected = session.PrinterEndpoint("aa:bb", "INSTAX-1 (IOS)")
    assert selected.normalized() == types.PrinterEndpoint("AA:BB", "INSTAX-1")
    assert selected.matches(types.PrinterEndpoint("CC:DD", "instax-1 (ANDROID)"))


def test_first_fallback_scanner_import_is_off_event_loop() -> None:
    _clean_python(
        """
import asyncio
import threading
import types
from instantlink_bridge import app
from instantlink_bridge.ui import status

main_thread = threading.get_ident()
loaded = []
async def scan(timeout_s):
    assert threading.get_ident() == main_thread
    assert timeout_s == 0.2
    return []
module = types.ModuleType("instantlink_bridge.ble.client")
module.scan_instax_printers = scan

def load(name):
    assert threading.get_ident() != main_thread
    assert name == module.__name__
    loaded.append(name)
    import sys
    sys.modules[name] = module
    return module
app.import_module = load
status.import_module = load
async def run():
    assert await app.scan_instax_printers(0.2) == []
    assert await status.scan_instax_printers(0.2) == []
asyncio.run(run())
assert len(loaded) == 2
"""
    )


def test_first_exif_helper_import_runs_in_metadata_thread() -> None:
    _clean_python(
        """
import asyncio
import builtins
import sys
import threading
from pathlib import Path
from instantlink_bridge import app

assert "instantlink_bridge.imaging.postprocess" not in sys.modules
main_thread = threading.get_ident()
original_import = builtins.__import__
loaded = []
def tracked_import(name, *args, **kwargs):
    if name == "instantlink_bridge.imaging.postprocess":
        loaded.append(threading.get_ident())
    return original_import(name, *args, **kwargs)
builtins.__import__ = tracked_import
async def run():
    result = await asyncio.to_thread(app.read_exif_datestamp_text, Path("/missing/photo.jpg"), "en")
    assert result == ""
asyncio.run(run())
assert loaded and all(thread != main_thread for thread in loaded)
"""
    )


def test_diagnostic_wrappers_forward_injected_session_and_connection_options() -> None:
    _clean_python(
        """
import asyncio
import sys
import threading
import types
from pathlib import Path
from instantlink_bridge import app
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.ui import status

main_thread = threading.get_ident()
manager = object()
connected = object()
module = types.ModuleType("instantlink_bridge.ble.client")
calls = []
async def print_file(address, image_path, **kwargs):
    assert threading.get_ident() == main_thread
    assert address == "AA:BB" and image_path == Path("photo.jpg")
    assert kwargs["session_manager"] is manager
    assert kwargs["quality"] == 99
    calls.append("print")
async def connect(address, name, **kwargs):
    assert address == "AA:BB" and name == "INSTAX-1"
    assert kwargs == {"timeout_s": 2.5, "model_override": PrinterModel.SQUARE}
    calls.append("connect")
    return connected
async def close(*, forget_endpoint):
    assert forget_endpoint is False
    calls.append("close")
module.print_file_to_printer = print_file
module.connect_instax_printer = connect
module.close_default_ble_session_manager = close
def load(name):
    assert threading.get_ident() != main_thread
    assert name == module.__name__
    sys.modules[name] = module
    return module
app.import_module = load
status.import_module = load
async def run():
    await app.print_file_to_printer_bleak(
        "AA:BB", Path("photo.jpg"), quality=99, session_manager=manager)
    result = await status.connect_instax_printer(
        "AA:BB", "INSTAX-1", timeout_s=2.5, model_override=PrinterModel.SQUARE)
    assert result is connected
    await app.close_default_ble_session_manager(forget_endpoint=False)
asyncio.run(run())
assert calls == ["print", "connect", "close"]
"""
    )


def test_cancelled_first_import_cleanup_keeps_event_loop_responsive() -> None:
    _clean_python(
        """
import asyncio
import importlib.abc
import importlib.util
import sys
import threading
from instantlink_bridge import app

name = "instantlink_bridge.ble.client"
started = threading.Event()
release = threading.Event()
closed = []
class Loader(importlib.abc.Loader):
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        started.set()
        assert release.wait(3), "test import gate timed out"
        async def close(*, forget_endpoint=True):
            closed.append(forget_endpoint)
        module.close_default_ble_session_manager = close
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == name:
            return importlib.util.spec_from_loader(fullname, Loader())
sys.meta_path.insert(0, Finder())
async def run():
    importing = asyncio.create_task(app.scan_instax_printers())
    assert await asyncio.to_thread(started.wait, 2)
    assert name in sys.modules
    importing.cancel()
    try:
        await importing
    except asyncio.CancelledError:
        pass
    # A safety timer releases a buggy synchronous import without hanging the suite.
    timer = threading.Timer(0.5, release.set)
    timer.start()
    closing = asyncio.create_task(app.close_default_ble_session_manager(forget_endpoint=False))
    try:
        for _ in range(5):
            await asyncio.sleep(0.01)
            assert not release.is_set(), "cleanup blocked the event loop on the import lock"
            assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 2)
    finally:
        release.set()
        timer.cancel()
        await closing
asyncio.run(run())
assert closed == [False]
"""
    )
