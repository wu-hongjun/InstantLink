"""Plan 056 — incoming/ is bounded by a disk budget.

The directory was never pruned; a live unit held 94 MB of camera originals
dating back two months despite bridge/CLAUDE.md declaring the storage
ephemeral. These tests pin the budget behaviour and, more importantly, the
two exemptions that keep an in-flight file from being deleted underneath a
print.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from instantlink_bridge.camera.ftp import prune_incoming_dir

MB = 1024 * 1024


def _write(directory: Path, name: str, *, size: int, age_s: float) -> Path:
    path = directory / name
    path.write_bytes(b"\0" * size)
    stamp = time.time() - age_s
    import os

    os.utime(path, (stamp, stamp))
    return path


def test_prunes_oldest_first_until_within_budget(tmp_path: Path) -> None:
    old = _write(tmp_path, "old.hif", size=3 * MB, age_s=90_000)
    mid = _write(tmp_path, "mid.hif", size=3 * MB, age_s=80_000)
    new = _write(tmp_path, "new.hif", size=3 * MB, age_s=70_000)

    removed = prune_incoming_dir(tmp_path, budget_bytes=7 * MB, keep_newest=0)

    assert removed == [old]
    assert not old.exists()
    assert mid.exists() and new.exists()


def test_no_op_when_already_within_budget(tmp_path: Path) -> None:
    kept = _write(tmp_path, "a.hif", size=1 * MB, age_s=90_000)

    assert prune_incoming_dir(tmp_path, budget_bytes=512 * MB, keep_newest=0) == []
    assert kept.exists()


def test_recent_files_are_exempt_even_over_budget(tmp_path: Path) -> None:
    """The guarantee that protects a queued or mid-print file."""

    fresh = _write(tmp_path, "in-flight.hif", size=50 * MB, age_s=5)

    removed = prune_incoming_dir(tmp_path, budget_bytes=1 * MB, keep_newest=0, grace_s=300.0)

    assert removed == []
    assert fresh.exists(), "a file received seconds ago must never be pruned"


def test_keep_newest_is_exempt_even_when_old(tmp_path: Path) -> None:
    for index in range(5):
        _write(tmp_path, f"f{index}.hif", size=10 * MB, age_s=90_000 + index)

    removed = prune_incoming_dir(tmp_path, budget_bytes=1 * MB, keep_newest=3, grace_s=0.0)

    # 5 files, 3 newest protected -> at most the 2 oldest can go.
    assert len(removed) == 2
    assert len(list(tmp_path.iterdir())) == 3


def test_budget_can_be_unreachable_without_error(tmp_path: Path) -> None:
    """Protected files can exceed the budget; that must not loop or raise."""

    _write(tmp_path, "big.hif", size=40 * MB, age_s=10)

    assert prune_incoming_dir(tmp_path, budget_bytes=1 * MB, keep_newest=0) == []


DAY = 24 * 3600.0


def test_age_retires_files_even_when_far_under_budget(tmp_path: Path) -> None:
    """The rule that actually fires on a real unit.

    The live Bridge sat at 98 MB against a 512 MB budget with originals back
    to May — bounded, but nothing a size budget would ever remove.
    """

    stale = _write(tmp_path, "may.hif", size=5 * MB, age_s=70 * DAY)
    fresh = _write(tmp_path, "today.hif", size=5 * MB, age_s=1 * DAY)

    removed = prune_incoming_dir(tmp_path, budget_bytes=512 * MB, max_age_s=14 * DAY)

    assert removed == [stale]
    assert fresh.exists()


def test_age_ignores_keep_newest(tmp_path: Path) -> None:
    """Otherwise a unit holding only old originals would never retire any."""

    for index in range(3):
        _write(tmp_path, f"old{index}.hif", size=1 * MB, age_s=70 * DAY + index)

    removed = prune_incoming_dir(tmp_path, budget_bytes=512 * MB, keep_newest=8, max_age_s=14 * DAY)

    assert len(removed) == 3
    assert list(tmp_path.iterdir()) == []


def test_age_still_respects_the_in_flight_grace(tmp_path: Path) -> None:
    # Contrived: mtime older than max_age but inside the grace window. Grace
    # wins, because grace is the in-flight guarantee.
    fresh = _write(tmp_path, "in-flight.hif", size=1 * MB, age_s=10)

    removed = prune_incoming_dir(
        tmp_path, budget_bytes=512 * MB, max_age_s=1.0, grace_s=300.0, keep_newest=0
    )

    assert removed == []
    assert fresh.exists()


def test_age_and_budget_both_apply(tmp_path: Path) -> None:
    stale = _write(tmp_path, "stale.hif", size=2 * MB, age_s=70 * DAY)
    big_old = _write(tmp_path, "big-old.hif", size=9 * MB, age_s=3 * DAY)
    recent = _write(tmp_path, "recent.hif", size=2 * MB, age_s=2 * DAY)

    removed = prune_incoming_dir(tmp_path, budget_bytes=10 * MB, keep_newest=0, max_age_s=14 * DAY)

    # stale goes on age; that leaves 11 MB against a 10 MB budget, so the
    # oldest survivor goes on budget too.
    assert removed == [stale, big_old]
    assert recent.exists()


def test_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    # Pruning must never fail a receive.
    assert prune_incoming_dir(tmp_path / "nope", budget_bytes=1 * MB) == []


def test_subdirectories_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    _write(tmp_path / "sub", "nested.hif", size=20 * MB, age_s=90_000)
    old = _write(tmp_path, "old.hif", size=20 * MB, age_s=90_000)

    removed = prune_incoming_dir(tmp_path, budget_bytes=1 * MB, keep_newest=0)

    assert removed == [old]
    assert (tmp_path / "sub" / "nested.hif").exists()


def test_receive_survives_a_pruner_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Housekeeping must never be the reason an upload fails.

    prune_incoming_dir handles expected OSErrors itself; this covers the
    unexpected, which the receive path swallows at the call site.
    """

    from instantlink_bridge.camera import ftp as ftp_module

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected pruner bug")

    monkeypatch.setattr(ftp_module, "prune_incoming_dir", boom)

    service = ftp_module.FtpReceiveService.__new__(ftp_module.FtpReceiveService)
    service._config = SimpleNamespace(incoming_dir=tmp_path, incoming_budget_mb=1)

    service._prune_incoming()  # must not raise
