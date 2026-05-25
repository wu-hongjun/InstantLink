"""systemd sd_notify integration."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Protocol, cast

LOGGER = logging.getLogger(__name__)


class _Notifier(Protocol):
    def notify(self, payload: str) -> object:
        """Send one sd_notify payload."""


class WatchdogNotifier:
    """Small wrapper around sdnotify with no-op behavior outside systemd."""

    def __init__(self) -> None:
        self._notifier = _create_notifier()
        self._enabled = "NOTIFY_SOCKET" in os.environ
        self.watchdog_interval_seconds = _watchdog_interval_seconds(os.environ)

    def ready(self) -> None:
        """Tell systemd the service is ready."""

        self._notify("READY=1")

    def watchdog(self) -> None:
        """Tell systemd the service is still healthy."""

        self._notify("WATCHDOG=1")

    def stopping(self) -> None:
        """Tell systemd the service is stopping."""

        self._notify("STOPPING=1")

    def _notify(self, payload: str) -> None:
        if not self._enabled or self._notifier is None:
            return
        try:
            self._notifier.notify(payload)
        except OSError:
            LOGGER.exception("systemd.notify_failed payload=%s", payload)


async def run_watchdog_heartbeat(
    stop_event: asyncio.Event,
    notifier: WatchdogNotifier,
) -> None:
    """Send watchdog pings while systemd watchdog support is enabled."""

    interval = notifier.watchdog_interval_seconds
    if interval is None:
        return

    while not stop_event.is_set():
        notifier.watchdog()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue


def _watchdog_interval_seconds(environ: Mapping[str, str]) -> float | None:
    raw_value = environ.get("WATCHDOG_USEC")
    if raw_value is None:
        return None
    try:
        watchdog_usec = int(raw_value)
    except ValueError:
        LOGGER.warning("systemd.invalid_watchdog_usec value=%s", raw_value)
        return None
    if watchdog_usec <= 0:
        return None
    return max(watchdog_usec / 2_000_000, 1.0)


def _create_notifier() -> _Notifier | None:
    try:
        from sdnotify import SystemdNotifier
    except ImportError:
        LOGGER.debug("systemd.sdnotify_unavailable")
        return None
    return cast(_Notifier, SystemdNotifier())
