"""Destination-aware FTP STOR preflight gate + shared printer predicate (plan 050)."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from instantlink_bridge.camera.ftp import FtpReceiveService, printer_usable_for_print
from instantlink_bridge.config import FtpConfig
from instantlink_bridge.ui.models import PairedPrinter, UiMode, UiSnapshot

# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_ftp_signal.py)
# ---------------------------------------------------------------------------

_PAIRED = PairedPrinter(address="AA:BB:CC:DD:EE:FF", name="INSTAX-12345678")

# Printer-path failure conditions the print-only preflight rejects. Each maps
# to the expected reply prefix in print mode; iphone/both must accept them all.
_PRINTER_FAULTS: dict[str, tuple[dict[str, object], str]] = {
    "unpaired": (
        {"mode": UiMode.NEEDS_PAIRING, "paired_printer": None, "printer_status_fresh": False},
        "501",
    ),
    "offline": ({"mode": UiMode.PRINTER_OFFLINE, "printer_status_fresh": False}, "451"),
    "no_film": ({"film_remaining": 0}, "552"),
    "printing": ({"mode": UiMode.PRINTING}, "450"),
}


def _make_snap(**kwargs: object) -> UiSnapshot:
    defaults: dict[str, object] = dict(
        mode=UiMode.READY,
        ftp_host="192.168.8.1",
        paired_printer=_PAIRED,
        printer_status_fresh=True,
        film_remaining=10,
        allow_print_without_film=False,
        sync_destination="print",
    )
    defaults.update(kwargs)
    return UiSnapshot(**defaults)  # type: ignore[arg-type]


def _make_service(snap: UiSnapshot) -> FtpReceiveService:
    queue: asyncio.Queue[object] = asyncio.Queue()
    loop = asyncio.new_event_loop()
    return FtpReceiveService(
        FtpConfig(incoming_dir=pathlib.Path("/tmp/ftp-test")),
        queue,  # type: ignore[arg-type]
        loop,
        bridge_snapshot_provider=lambda: snap,
    )


# ---------------------------------------------------------------------------
# BOOTING rejects for every destination (the only sync-mode gate)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("destination", ["print", "iphone"])
def test_preflight_booting_rejects_for_all_destinations(destination: str) -> None:
    snap = _make_snap(
        mode=UiMode.BOOTING,
        printer_status_fresh=False,
        sync_destination=destination,
    )

    reply = _make_service(snap)._ftp_preflight_reply()

    assert reply is not None
    assert reply.startswith("451")


# ---------------------------------------------------------------------------
# Ready state falls through for every destination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("destination", ["print", "iphone"])
def test_preflight_ready_state_accepts_for_all_destinations(destination: str) -> None:
    snap = _make_snap(sync_destination=destination)

    assert _make_service(snap)._ftp_preflight_reply() is None


# ---------------------------------------------------------------------------
# print destination: existing rejection matrix unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshot_kwargs", "reply_prefix"),
    _PRINTER_FAULTS.values(),
    ids=_PRINTER_FAULTS.keys(),
)
def test_preflight_print_destination_keeps_printer_rejections(
    snapshot_kwargs: dict[str, object],
    reply_prefix: str,
) -> None:
    snap = _make_snap(sync_destination="print", **snapshot_kwargs)

    reply = _make_service(snap)._ftp_preflight_reply()

    assert reply is not None
    assert reply.startswith(reply_prefix)
    assert len(reply) <= 50


# ---------------------------------------------------------------------------
# Sync mode: only BOOTING gates; printer faults all accept
# (sync spooling is not serialized by printing, so PRINTING accepts too)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_kwargs",
    [kwargs for kwargs, _prefix in _PRINTER_FAULTS.values()],
    ids=_PRINTER_FAULTS.keys(),
)
def test_preflight_sync_destinations_accept_despite_printer_faults(
    snapshot_kwargs: dict[str, object],
) -> None:
    snap = _make_snap(sync_destination="iphone", **snapshot_kwargs)

    assert _make_service(snap)._ftp_preflight_reply() is None


# ---------------------------------------------------------------------------
# Unpaired copy no longer claims a Mac is required
# ---------------------------------------------------------------------------


def test_preflight_unpaired_copy_offers_iphone_sync() -> None:
    snap = _make_snap(
        mode=UiMode.NEEDS_PAIRING,
        paired_printer=None,
        printer_status_fresh=False,
        sync_destination="print",
    )

    reply = _make_service(snap)._ftp_preflight_reply()

    assert reply is not None
    assert reply.startswith("501")
    assert "Mac" not in reply
    assert "iPhone sync" in reply
    assert len(reply) <= 50


# ---------------------------------------------------------------------------
# printer_usable_for_print: the shared app.py / ftp.py readiness predicate
# ---------------------------------------------------------------------------


def test_printer_usable_when_paired_fresh_reachable_with_film() -> None:
    assert printer_usable_for_print(_make_snap()) is True


@pytest.mark.parametrize(
    "snapshot_kwargs",
    [
        {"paired_printer": None},
        {"printer_status_fresh": False},
        {"mode": UiMode.PRINTER_OFFLINE},
        {"mode": UiMode.NEEDS_PAIRING},
        {"film_remaining": 0},
    ],
    ids=["unpaired", "stale_status", "offline_mode", "needs_pairing_mode", "no_film"],
)
def test_printer_not_usable_for_faults(snapshot_kwargs: dict[str, object]) -> None:
    assert printer_usable_for_print(_make_snap(**snapshot_kwargs)) is False


def test_printer_usable_with_no_film_test_override() -> None:
    snap = _make_snap(film_remaining=0, allow_print_without_film=True)

    assert printer_usable_for_print(snap) is True


def test_printer_usable_with_unknown_film_count() -> None:
    # film_remaining=None means "not yet polled"; the BLE layer is the final
    # arbiter, matching the preflight's unknown-film fall-through.
    snap = _make_snap(film_remaining=None)

    assert printer_usable_for_print(snap) is True
