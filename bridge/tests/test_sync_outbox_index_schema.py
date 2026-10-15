"""Persistence compatibility for the scalar outbox index serializer."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from instantlink_bridge.sync import outbox as outbox_module
from instantlink_bridge.sync.outbox import INDEX_VERSION, SyncOutbox


def test_index_bytes_match_dataclass_schema_after_add_ack_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "outbox"
    outbox = SyncOutbox(root, budget_mb=64)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    timestamps = [0.0, 1_734_424_552.125, 9_000_000_000.5]
    # Exercise JSON escaping, Unicode, empty optional metadata, and zero size.
    fixtures = [
        ('photo"\\name.jpg', b"", ""),
        ("旅の写真.HIF", b"camera-original", "fe80::1234%wlan0"),
        ("last.jpg", b"last-original", "192.168.8.20"),
    ]
    for timestamp, (name, content, remote_ip) in zip(timestamps, fixtures, strict=True):
        monkeypatch.setattr(outbox_module.time, "time", lambda timestamp=timestamp: timestamp)
        source = uploads / name
        source.write_bytes(content)
        outbox.add(source, remote_ip=remote_ip)
        expected = {
            "version": INDEX_VERSION,
            "items": [asdict(item) for item in outbox.pending()],
        }
        assert (root / "index.json").read_bytes() == json.dumps(expected, indent=2).encode()
        assert SyncOutbox(root, budget_mb=64).pending() == outbox.pending()

    # Each subsequent publication must reflect the current queue in arrival order.
    first, second, third = outbox.pending()
    for removed, remaining in [(second, [first, third]), (first, [third]), (third, [])]:
        assert outbox.ack(removed.item_id)
        expected = {"version": INDEX_VERSION, "items": [asdict(item) for item in remaining]}
        assert (root / "index.json").read_bytes() == json.dumps(expected, indent=2).encode()
        assert SyncOutbox(root, budget_mb=64).pending() == remaining
