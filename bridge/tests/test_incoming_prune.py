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
