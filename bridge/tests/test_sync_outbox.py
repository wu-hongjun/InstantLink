"""Tests for the iPhone sync outbox spool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from instantlink_bridge.sync.outbox import SyncOutbox


def _write_source(directory: Path, name: str, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / name
    source.write_bytes(payload)
    return source


def _make_outbox(tmp_path: Path, *, budget_mb: int = 64) -> SyncOutbox:
    return SyncOutbox(tmp_path / "outbox", budget_mb=budget_mb)


def test_add_pending_get_ack_depth_round_trip(tmp_path: Path) -> None:
    outbox = _make_outbox(tmp_path)
    payload = b"jpeg-bytes-round-trip"
    source = _write_source(tmp_path / "uploads", "DSC00001.JPG", payload)

    item = outbox.add(source, remote_ip="192.168.8.20")

    assert len(item.item_id) == 16
    assert item.file_name == "DSC00001.JPG"
    assert item.size_bytes == len(payload)
    assert item.sha256 == hashlib.sha256(payload).hexdigest()
    assert item.received_at > 0
    assert item.source_remote_ip == "192.168.8.20"

    assert outbox.depth() == 1
    assert outbox.pending() == [item]
    assert outbox.get(item.item_id) == item
    assert outbox.get("missing") is None
    assert outbox.path_for("missing") is None

    spool_path = outbox.path_for(item.item_id)
    assert spool_path is not None
    assert spool_path.read_bytes() == payload

    assert outbox.ack(item.item_id) is True
    assert outbox.depth() == 0
    assert outbox.pending() == []
    assert not spool_path.exists()
    assert outbox.ack(item.item_id) is False


def test_add_never_mutates_source(tmp_path: Path) -> None:
    outbox = _make_outbox(tmp_path)
    payload = b"original-must-survive"
    source = _write_source(tmp_path / "uploads", "DSC00002.JPG", payload)

    item = outbox.add(source)
    assert source.read_bytes() == payload

    outbox.ack(item.item_id)
    assert source.read_bytes() == payload


def test_duplicate_file_names_get_unique_spool_paths(tmp_path: Path) -> None:
    outbox = _make_outbox(tmp_path)
    first = _write_source(tmp_path / "a", "DSC00003.JPG", b"first-body")
    second = _write_source(tmp_path / "b", "DSC00003.JPG", b"second-body-longer")

    item_a = outbox.add(first)
    item_b = outbox.add(second)

    assert item_a.item_id != item_b.item_id
    assert item_a.file_name == item_b.file_name == "DSC00003.JPG"
    path_a = outbox.path_for(item_a.item_id)
    path_b = outbox.path_for(item_b.item_id)
    assert path_a is not None and path_b is not None
    assert path_a != path_b
    assert path_a.read_bytes() == b"first-body"
    assert path_b.read_bytes() == b"second-body-longer"
    assert outbox.pending() == [item_a, item_b]


def test_index_persists_across_reinstantiation(tmp_path: Path) -> None:
    root = tmp_path / "outbox"
    outbox = SyncOutbox(root, budget_mb=64)
    first = outbox.add(_write_source(tmp_path / "u", "one.jpg", b"one"))
    second = outbox.add(_write_source(tmp_path / "u", "two.jpg", b"two-two"))

    reloaded = SyncOutbox(root, budget_mb=64)
    assert reloaded.pending() == [first, second]
    assert reloaded.get(first.item_id) == first
    path = reloaded.path_for(second.item_id)
    assert path is not None
    assert path.read_bytes() == b"two-two"


def test_reload_drops_entries_whose_spool_file_vanished(tmp_path: Path) -> None:
    root = tmp_path / "outbox"
    outbox = SyncOutbox(root, budget_mb=64)
    gone = outbox.add(_write_source(tmp_path / "u", "gone.jpg", b"gone"))
    kept = outbox.add(_write_source(tmp_path / "u", "kept.jpg", b"kept"))

    spool_path = outbox.path_for(gone.item_id)
    assert spool_path is not None
    spool_path.unlink()

    reloaded = SyncOutbox(root, budget_mb=64)
    assert reloaded.pending() == [kept]
    assert reloaded.get(gone.item_id) is None

    # The rewritten index no longer references the vanished item.
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert [entry["item_id"] for entry in index["items"]] == [kept.item_id]


def test_corrupt_index_starts_empty(tmp_path: Path) -> None:
    root = tmp_path / "outbox"
    root.mkdir()
    (root / "index.json").write_text("{not json", encoding="utf-8")

    outbox = SyncOutbox(root, budget_mb=64)
    assert outbox.depth() == 0


def test_budget_evicts_oldest_items(tmp_path: Path) -> None:
    outbox = _make_outbox(tmp_path, budget_mb=1)
    chunk = 400 * 1024  # three files exceed the 1 MiB budget
    first = outbox.add(_write_source(tmp_path / "u", "a.jpg", b"a" * chunk))
    second = outbox.add(_write_source(tmp_path / "u", "b.jpg", b"b" * chunk))
    first_path = outbox.path_for(first.item_id)
    assert first_path is not None

    third = outbox.add(_write_source(tmp_path / "u", "c.jpg", b"c" * chunk))

    assert outbox.pending() == [second, third]
    assert outbox.get(first.item_id) is None
    assert not first_path.exists()

    # Survivors and their spool files stay intact.
    for survivor in (second, third):
        path = outbox.path_for(survivor.item_id)
        assert path is not None
        assert path.stat().st_size == chunk


def test_budget_eviction_persists_to_index(tmp_path: Path) -> None:
    root = tmp_path / "outbox"
    outbox = SyncOutbox(root, budget_mb=1)
    chunk = 700 * 1024
    outbox.add(_write_source(tmp_path / "u", "old.jpg", b"o" * chunk))
    newest = outbox.add(_write_source(tmp_path / "u", "new.jpg", b"n" * chunk))

    reloaded = SyncOutbox(root, budget_mb=1)
    assert reloaded.pending() == [newest]


@pytest.mark.asyncio
async def test_pending_photo_preparation_overlaps_existing_photo_reads_and_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    from instantlink_bridge.sync import outbox as outbox_module

    outbox = _make_outbox(tmp_path)
    existing = outbox.add(_write_source(tmp_path / "uploads", "old.jpg", b"old photo"))
    incoming = _write_source(tmp_path / "uploads", "new.hif", b"new photo")
    started = threading.Event()
    release = threading.Event()
    original_hash = outbox_module._hash_file

    def slow_hash(path: Path) -> str:
        started.set()
        if not release.wait(2):
            raise AssertionError("hash held the metadata lock")
        return original_hash(path)

    monkeypatch.setattr(outbox_module, "_hash_file", slow_hash)
    adding = asyncio.create_task(asyncio.to_thread(outbox.add, incoming))
    try:
        assert await asyncio.to_thread(started.wait, 1)

        def use_existing_photo() -> None:
            assert outbox.depth() == 1
            assert outbox.pending() == [existing]
            assert outbox.get(existing.item_id) == existing
            path = outbox.path_for(existing.item_id)
            assert path is not None and path.read_bytes() == b"old photo"
            assert outbox.ack(existing.item_id)
            assert outbox.depth() == 0

        await asyncio.wait_for(asyncio.to_thread(use_existing_photo), 0.3)
        assert not adding.done()
        release.set()
        item = await asyncio.wait_for(adding, 1)
        assert outbox.pending() == [item]
        assert item.sha256 == hashlib.sha256(b"new photo").hexdigest()
        assert SyncOutbox(tmp_path / "outbox", budget_mb=64).pending() == [item]
    finally:
        release.set()
        await adding


def test_failed_new_photo_checksum_keeps_index_and_removes_unpublished_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from instantlink_bridge.sync import outbox as outbox_module

    outbox = _make_outbox(tmp_path)
    existing = outbox.add(_write_source(tmp_path / "uploads", "old.jpg", b"old"))
    before = set((tmp_path / "outbox").iterdir())
    incoming = _write_source(tmp_path / "uploads", "new.hif", b"new")

    def fail_hash(path: Path) -> str:
        raise OSError("read failed")

    monkeypatch.setattr(outbox_module, "_hash_file", fail_hash)
    with pytest.raises(OSError, match="read failed"):
        outbox.add(incoming)
    assert outbox.pending() == [existing]
    assert set((tmp_path / "outbox").iterdir()) == before
    assert incoming.read_bytes() == b"new"
