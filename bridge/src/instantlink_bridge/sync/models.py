"""Typed items for the iPhone sync outbox."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutboxItem:
    """One spooled original awaiting pickup by the iOS app.

    ``item_id`` is a stable unique hex id; ``file_name`` is the original
    upload file name (duplicates allowed — spool names are keyed by
    ``item_id``); ``received_at`` is epoch seconds.
    """

    item_id: str
    file_name: str
    size_bytes: int
    sha256: str
    received_at: float
    source_remote_ip: str
