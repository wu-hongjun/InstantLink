from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dbus_fast import Variant

from instantlink_bridge.ui import pairing
from instantlink_bridge.ui.models import PairedPrinter

ADAPTER = "/org/bluez/hci0"
ADDRESS = "FA:AB:BC:51:CC:E2"
OTHER_ADDRESS = "88:B4:36:51:CC:E2"
SELECTED = PairedPrinter(address=ADDRESS, name="INSTAX-1N034655")


def snapshot(
    *, address: str = ADDRESS, alias: str = SELECTED.name, trusted: bool = True
) -> dict[str, object]:
    return {
        ADAPTER: {"org.bluez.Adapter1": {}},
        f"{ADAPTER}/dev_{address.replace(':', '_')}": {
            "org.bluez.Device1": {
                "Address": Variant("s", address),
                "Alias": Variant("s", alias),
                "Connected": Variant("b", False),
                "Trusted": Variant("b", trusted),
                "Adapter": Variant("o", ADAPTER),
            }
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted", [True, False])
async def test_saved_selection_uses_fresh_trust_state_without_devices_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trusted: bool
) -> None:
    store = pairing.SelectedPrinterStore(tmp_path / "printer.json")
    store.save(SELECTED)
    calls: list[tuple[str, ...]] = []
    reads = 0

    async def provider() -> object:
        nonlocal reads
        reads += 1
        # Each invocation is authoritative; a later refresh must not reuse trust state.
        return snapshot(trusted=trusted if reads == 1 else not trusted)

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        calls.append(args)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    pairer = pairing.BluetoothctlPrinterPairer(store=store, bluez_objects_provider=provider)
    assert await pairer.list_paired() == [SELECTED]
    assert calls == ([] if trusted else [("trust", ADDRESS)])
    assert await pairer.list_paired() == [SELECTED]
    assert calls == [("trust", ADDRESS)]
    assert reads == 2
    assert store.load() == SELECTED


@pytest.mark.asyncio
async def test_trust_snapshot_preserves_exact_address_and_normalized_alias_identity() -> None:
    tree = snapshot(alias="Renamed Printer", trusted=False)
    tree.update(snapshot(address=OTHER_ADDRESS, alias="INSTAX-1N034655 (ANDROID)", trusted=False))
    tree.update(snapshot(address="AA:BB:CC:DD:EE:FF", alias="INSTAX-OTHER", trusted=False))

    async def provider() -> object:
        return tree

    assert await pairing._untrusted_bluez_addresses_from_dbus(SELECTED, provider) == [
        OTHER_ADDRESS,
        ADDRESS,
    ]


@pytest.mark.asyncio
async def test_absent_saved_device_does_not_spawn_an_ineffective_trust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider() -> object:
        return {ADAPTER: {"org.bluez.Adapter1": {}}}

    async def forbidden(*_args: str, **_kwargs: object) -> pairing._CommandResult:
        raise AssertionError("absent device has no BlueZ property to change")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", forbidden)
    pairer = pairing.BluetoothctlPrinterPairer(bluez_objects_provider=provider)
    await pairer._trust_selected_bluez_devices(SELECTED)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["missing", "malformed", "multi_adapter", "unknown_trust", "wrong_trust", "error"]
)
async def test_uncertain_snapshot_retains_existing_cli_inventory_and_trust_fallback(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    tree = snapshot()
    if fault == "multi_adapter":
        tree["/org/bluez/hci1"] = {"org.bluez.Adapter1": {}}
    elif fault in {"unknown_trust", "wrong_trust"}:
        interfaces = tree[f"{ADAPTER}/dev_{ADDRESS.replace(':', '_')}"]
        assert isinstance(interfaces, dict)
        properties = interfaces["org.bluez.Device1"]
        if fault == "unknown_trust":
            properties.pop("Trusted")
        else:
            properties["Trusted"] = Variant("s", "true")
    calls: list[tuple[str, ...]] = []

    async def provider() -> object:
        if fault == "error":
            raise OSError("bus unavailable")
        return [] if fault == "malformed" else tree

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        calls.append(args)
        return pairing._CommandResult(
            0, f"Device {OTHER_ADDRESS} INSTAX-1N034655(ANDROID)" if args == ("devices",) else ""
        )

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    pairer = pairing.BluetoothctlPrinterPairer(
        bluez_objects_provider=None if fault == "missing" else provider
    )
    await pairer._trust_selected_bluez_devices(SELECTED)
    assert calls == [("devices",), ("trust", OTHER_ADDRESS), ("trust", ADDRESS)]


@pytest.mark.asyncio
async def test_cancelled_snapshot_does_not_start_cli_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def provider() -> object:
        started.set()
        await asyncio.Future[None]()

    async def forbidden(*_args: str, **_kwargs: object) -> pairing._CommandResult:
        raise AssertionError("cancellation must not launch CLI fallback")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", forbidden)
    pairer = pairing.BluetoothctlPrinterPairer(bluez_objects_provider=provider)
    task = asyncio.create_task(pairer._trust_selected_bluez_devices(SELECTED))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_snapshot_timeout_cleans_up_read_before_cli_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = asyncio.Event()
    calls: list[tuple[str, ...]] = []
    original_timeout = asyncio.timeout
    monkeypatch.setattr(pairing.asyncio, "timeout", lambda _delay: original_timeout(0.01))

    async def provider() -> object:
        try:
            await asyncio.Future[None]()
        finally:
            completed.set()

    async def command(*args: str, **_kwargs: object) -> pairing._CommandResult:
        assert completed.is_set()
        calls.append(args)
        return pairing._CommandResult(0, "")

    monkeypatch.setattr(pairing, "_run_bluetoothctl", command)
    pairer = pairing.BluetoothctlPrinterPairer(bluez_objects_provider=provider)
    await pairer._trust_selected_bluez_devices(SELECTED)
    assert calls == [("devices",), ("trust", ADDRESS)]
