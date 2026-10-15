"""Disk spool for camera originals awaiting iPhone pickup.

The outbox is intentionally synchronous and thread-safe; the asyncio
service layer runs its methods via :func:`asyncio.to_thread`. Spool files
live directly under ``root`` and are named by ``item_id`` (plus the
original file suffix), so duplicate upload names never collide. A small
JSON index at ``root/index.json`` is rewritten atomically after every
mutation and reloaded on construction.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import tempfile
import threading
import time
from hashlib import sha256 as sha256_hasher
from pathlib import Path

from instantlink_bridge.sync.models import OutboxItem

LOGGER = logging.getLogger(__name__)

INDEX_FILE_NAME = "index.json"
INDEX_VERSION = 1
_HASH_CHUNK_BYTES = 1024 * 1024


class SyncOutbox:
    """Thread-safe disk spool with a JSON index and a size budget."""

    def __init__(self, root: Path, *, budget_mb: int) -> None:
        self._root = root
        self._budget_bytes = budget_mb * 1024 * 1024
        self._lock = threading.Lock()
        # Index publication serializes mutations, while readers keep using
        # the last committed snapshot during filesystem I/O.
        self._mutation_lock = threading.Lock()
        # Serialize arrivals without making existing-photo reads/acks wait
        # for a new photo's potentially slow copy or checksum.
        self._add_lock = threading.Lock()
        # Insertion order is arrival order (oldest first); the persisted
        # index list preserves it across restarts.
        self._items: dict[str, OutboxItem] = {}
        self._root.mkdir(parents=True, exist_ok=True)
        self._load_index()

    def add(self, source: Path, *, remote_ip: str = "") -> OutboxItem:
        """Spool ``source`` into the outbox without mutating the source.

        Each original has its own inode: a camera may overwrite or append to
        the incoming filename after dispatch releases it. Evicts oldest items
        first when the disk budget would be exceeded.
        """

        with self._add_lock:
            item_id = secrets.token_hex(8)
            spool_path = self._spool_path(item_id, source.name)
            try:
                shutil.copy2(source, spool_path)
                size_bytes = spool_path.stat().st_size
                item = OutboxItem(
                    item_id=item_id,
                    file_name=source.name,
                    size_bytes=size_bytes,
                    sha256=_hash_file(spool_path),
                    received_at=time.time(),
                    source_remote_ip=remote_ip,
                )
                with self._mutation_lock:
                    with self._lock:
                        proposed = dict(self._items)
                    evicted = self._evict_until_fits(proposed, incoming_bytes=size_bytes)
                    proposed[item_id] = item
                    self._write_index_locked(proposed)
                    with self._lock:
                        self._items = proposed
            except BaseException:
                try:
                    spool_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning(
                        "sync.outbox_unpublished_spool_unlink_failed path=%s",
                        spool_path,
                        exc_info=True,
                    )
                raise
            for oldest in evicted:
                self._unlink_spool(oldest)
                LOGGER.warning(
                    "sync.outbox_evicted item=%s file=%s size=%s reason=budget",
                    oldest.item_id,
                    oldest.file_name,
                    oldest.size_bytes,
                )
            LOGGER.info(
                "sync.outbox_added item=%s file=%s size=%s remote_ip=%s",
                item_id,
                item.file_name,
                size_bytes,
                remote_ip,
            )
            return item

    def pending(self) -> list[OutboxItem]:
        """Return all spooled items, oldest first."""

        with self._lock:
            return list(self._items.values())

    def get(self, item_id: str) -> OutboxItem | None:
        """Return one item by id, or ``None`` if unknown."""

        with self._lock:
            return self._items.get(item_id)

    def path_for(self, item_id: str) -> Path | None:
        """Return the spool file path for an item, or ``None`` if unknown."""

        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            return self._spool_path_for_item(item)

    def ack(self, item_id: str) -> bool:
        """Delete the spool file and index entry for a confirmed item."""

        with self._mutation_lock:
            with self._lock:
                proposed = dict(self._items)
            item = proposed.pop(item_id, None)
            if item is None:
                return False
            self._write_index_locked(proposed)
            with self._lock:
                self._items = proposed
            self._unlink_spool(item)
            LOGGER.info("sync.outbox_acked item=%s file=%s", item_id, item.file_name)
            return True

    def depth(self) -> int:
        """Return the number of items awaiting pickup."""

        with self._lock:
            return len(self._items)

    def _load_index(self) -> None:
        index_path = self._root / INDEX_FILE_NAME
        if not index_path.exists():
            return
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("sync.outbox_index_unreadable path=%s", index_path, exc_info=True)
            return
        entries = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            LOGGER.warning("sync.outbox_index_invalid path=%s", index_path)
            return
        dropped = 0
        loaded: dict[str, OutboxItem] = {}
        for entry in entries:
            item = _item_from_json(entry)
            if item is None or not self._spool_path_for_item(item).is_file():
                dropped += 1
                continue
            self._detach_legacy_spool(self._spool_path_for_item(item))
            loaded[item.item_id] = item
        if dropped:
            LOGGER.warning("sync.outbox_index_entries_dropped count=%s", dropped)
            self._write_index_locked(loaded)
        self._items = loaded
        LOGGER.info("sync.outbox_loaded depth=%s root=%s", len(self._items), self._root)

    def _detach_legacy_spool(self, path: Path) -> None:
        """Atomically migrate originals saved by older hard-link spooling."""
        if path.stat().st_nlink <= 1:
            return
        with tempfile.TemporaryDirectory(prefix=".instantlink-detach-", dir=self._root) as temp:
            detached = Path(temp) / "original"
            shutil.copy2(path, detached)
            os.replace(detached, path)
        LOGGER.info("sync.outbox_legacy_spool_detached path=%s", path)

    def _evict_until_fits(
        self, proposed: dict[str, OutboxItem], *, incoming_bytes: int
    ) -> list[OutboxItem]:
        evicted: list[OutboxItem] = []
        total_bytes = sum(item.size_bytes for item in proposed.values())
        while proposed and total_bytes + incoming_bytes > self._budget_bytes:
            oldest_id, oldest = next(iter(proposed.items()))
            del proposed[oldest_id]
            evicted.append(oldest)
            total_bytes -= oldest.size_bytes
        return evicted

    def _write_index_locked(self, proposed: dict[str, OutboxItem]) -> None:
        """Publish a staged index while holding the mutation lock (or constructing)."""
        payload = {
            "version": INDEX_VERSION,
            # OutboxItem contains only immutable scalars; avoid the generic
            # recursive dataclass traversal on every queue mutation.
            "items": [
                {
                    "item_id": item.item_id,
                    "file_name": item.file_name,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "received_at": item.received_at,
                    "source_remote_ip": item.source_remote_ip,
                }
                for item in proposed.values()
            ],
        }
        index_path = self._root / INDEX_FILE_NAME
        tmp_path = self._root / f"{INDEX_FILE_NAME}.tmp"
        try:
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp_path, index_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("sync.outbox_index_temp_unlink_failed", exc_info=True)
            raise

    def _unlink_spool(self, item: OutboxItem) -> None:
        try:
            self._spool_path_for_item(item).unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("sync.outbox_spool_unlink_failed item=%s", item.item_id, exc_info=True)

    def _spool_path_for_item(self, item: OutboxItem) -> Path:
        return self._spool_path(item.item_id, item.file_name)

    def _spool_path(self, item_id: str, file_name: str) -> Path:
        return self._root / f"{item_id}{_safe_suffix(file_name)}"


def _safe_suffix(file_name: str) -> str:
    """Return a filesystem-safe lowercase suffix for a spool file name."""

    suffix = Path(file_name).suffix
    if suffix and all(ch.isalnum() or ch == "." for ch in suffix):
        return suffix.lower()
    return ""


def _hash_file(path: Path) -> str:
    hasher = sha256_hasher()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()


def _item_from_json(value: object) -> OutboxItem | None:
    if not isinstance(value, dict):
        return None
    item_id = value.get("item_id")
    file_name = value.get("file_name")
    size_bytes = value.get("size_bytes")
    sha256 = value.get("sha256")
    received_at = value.get("received_at")
    source_remote_ip = value.get("source_remote_ip")
    if not isinstance(item_id, str) or not item_id:
        return None
    if not isinstance(file_name, str) or not file_name:
        return None
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        return None
    if not isinstance(sha256, str):
        return None
    if isinstance(received_at, bool) or not isinstance(received_at, int | float):
        return None
    if not isinstance(source_remote_ip, str):
        return None
    return OutboxItem(
        item_id=item_id,
        file_name=file_name,
        size_bytes=size_bytes,
        sha256=sha256,
        received_at=float(received_at),
        source_remote_ip=source_remote_ip,
    )
