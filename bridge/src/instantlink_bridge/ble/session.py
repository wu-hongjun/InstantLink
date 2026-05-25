"""Shared BLE session ownership for Instax printers."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Generic, Protocol, TypeVar

from instantlink_bridge.ble.models import PrinterModel, spec_for

LOGGER = logging.getLogger(__name__)


class ManagedInstaxPrinter(Protocol):
    """Connected printer object owned by the BLE session manager."""

    async def disconnect(self) -> None:
        """Disconnect from the printer."""


ConnectedT = TypeVar("ConnectedT", bound=ManagedInstaxPrinter)
SessionConnector = Callable[["PrinterEndpoint", PrinterModel | None], Awaitable[ConnectedT]]
SessionSleep = Callable[[float], Awaitable[None]]
ConnectedModel = Callable[[ConnectedT], PrinterModel | None]


class SessionRole(StrEnum):
    """Caller role for a leased BLE session."""

    STATUS = "status"
    PRINT = "print"


@dataclass(frozen=True, slots=True)
class PrinterEndpoint:
    """Resolved BLE endpoint for a selected Instax printer."""

    address: str
    name: str
    model: PrinterModel | None = None

    def normalized(self) -> PrinterEndpoint:
        """Return a stable endpoint representation."""

        return PrinterEndpoint(
            address=self.address.upper(),
            name=_normalize_instax_name(self.name),
            model=self.model,
        )

    def matches(self, other: PrinterEndpoint) -> bool:
        """Return true when two endpoints identify the same selected printer."""

        if self.address.upper() == other.address.upper():
            return True
        self_name = _normalize_instax_name(self.name).casefold()
        other_name = _normalize_instax_name(other.name).casefold()
        return bool(self_name and other_name and self_name == other_name)


@dataclass(frozen=True, slots=True)
class SessionRetryPolicy:
    """Bounded connection retry policy."""

    max_attempts: int = 3
    backoff_s: tuple[float, ...] = (1.0, 2.0, 5.0, 15.0)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if any(not math.isfinite(delay) or delay < 0 for delay in self.backoff_s):
            raise ValueError("backoff delays must be finite and non-negative")

    def delay_before_retry(self, failed_attempt: int) -> float:
        """Return the delay after a failed one-based attempt."""

        if not self.backoff_s:
            return 0.0
        return self.backoff_s[min(failed_attempt - 1, len(self.backoff_s) - 1)]


class InstaxBleSessionLease(Generic[ConnectedT]):
    """Exclusive lease for a managed BLE printer connection."""

    def __init__(
        self,
        manager: InstaxBleSessionManager[ConnectedT],
        *,
        role: SessionRole,
        endpoint: PrinterEndpoint,
        connected: ConnectedT,
    ) -> None:
        self._manager = manager
        self._role = role
        self._endpoint = endpoint
        self._connected = connected
        self._released = False

    @property
    def role(self) -> SessionRole:
        """Return the caller role that owns this lease."""

        return self._role

    @property
    def endpoint(self) -> PrinterEndpoint:
        """Return the endpoint used by this lease."""

        return self._endpoint

    @property
    def connected(self) -> ConnectedT:
        """Return the connected printer."""

        return self._connected

    async def release(
        self,
        *,
        failed: bool = False,
        keep_connected: bool | None = None,
    ) -> None:
        """Release the lease and optionally keep the connection cached."""

        if self._released:
            return
        self._released = True
        await self._manager._release(self, failed=failed, keep_connected=keep_connected)

    async def __aenter__(self) -> InstaxBleSessionLease[ConnectedT]:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = traceback
        await self.release(failed=exc_type is not None or exc is not None)


class InstaxBleSessionManager(Generic[ConnectedT]):
    """Own and hand off a cached Instax BLE connection between status and print flows."""

    def __init__(
        self,
        connector: SessionConnector[ConnectedT],
        *,
        connect_timeout_s: float | None = None,
        retry_policy: SessionRetryPolicy | None = None,
        sleep: SessionSleep = asyncio.sleep,
        connected_model: ConnectedModel[ConnectedT] | None = None,
    ) -> None:
        self._connector = connector
        self._connect_timeout_s = connect_timeout_s
        self._retry_policy = retry_policy if retry_policy is not None else SessionRetryPolicy()
        self._sleep = sleep
        self._connected_model = connected_model
        self._lease_lock = asyncio.Lock()
        self._connected: ConnectedT | None = None
        self._connected_endpoint: PrinterEndpoint | None = None
        self._known_endpoint: PrinterEndpoint | None = None

    def known_endpoint(self) -> PrinterEndpoint | None:
        """Return the last successfully connected endpoint, if any."""

        return self._known_endpoint

    def cached_endpoint_for(self, selected: PrinterEndpoint) -> PrinterEndpoint | None:
        """Return a cached endpoint for the selected printer identity, if one is known."""

        normalized = selected.normalized()
        connected_endpoint = self._connected_endpoint
        if connected_endpoint is not None and connected_endpoint.matches(normalized):
            return connected_endpoint
        known_endpoint = self._known_endpoint
        if known_endpoint is not None and known_endpoint.matches(normalized):
            return known_endpoint
        return None

    async def acquire_status(
        self,
        endpoint: PrinterEndpoint,
        *,
        connect_timeout_s: float | None = None,
        model_override: PrinterModel | None = None,
    ) -> InstaxBleSessionLease[ConnectedT]:
        """Acquire the session for a short status operation."""

        return await self.acquire(
            endpoint,
            SessionRole.STATUS,
            connect_timeout_s=connect_timeout_s,
            model_override=model_override,
        )

    async def acquire_print(
        self,
        endpoint: PrinterEndpoint,
        *,
        connect_timeout_s: float | None = None,
        model_override: PrinterModel | None = None,
    ) -> InstaxBleSessionLease[ConnectedT]:
        """Acquire the session for a print operation."""

        return await self.acquire(
            endpoint,
            SessionRole.PRINT,
            connect_timeout_s=connect_timeout_s,
            model_override=model_override,
        )

    async def acquire(
        self,
        endpoint: PrinterEndpoint,
        role: SessionRole,
        *,
        connect_timeout_s: float | None = None,
        model_override: PrinterModel | None = None,
    ) -> InstaxBleSessionLease[ConnectedT]:
        """Acquire exclusive access to a connected printer session."""

        await self._lease_lock.acquire()
        try:
            normalized = endpoint.normalized()
            connected_endpoint = self._endpoint_for_acquire(normalized)
            connected = await self._connected_for_endpoint(
                connected_endpoint,
                connect_timeout_s=connect_timeout_s,
                model_override=model_override,
            )
            return InstaxBleSessionLease(
                self,
                role=role,
                endpoint=connected_endpoint,
                connected=connected,
            )
        except BaseException:
            self._lease_lock.release()
            raise

    async def close(self, *, forget_endpoint: bool = True) -> None:
        """Disconnect the cached session."""

        await self._lease_lock.acquire()
        try:
            await self._clear_cached_locked(forget_endpoint=forget_endpoint)
        finally:
            self._lease_lock.release()

    async def _release(
        self,
        lease: InstaxBleSessionLease[ConnectedT],
        *,
        failed: bool,
        keep_connected: bool | None,
    ) -> None:
        keep = keep_connected
        if keep is None:
            keep = lease.role is SessionRole.STATUS and not failed
        try:
            if failed:
                was_cached = lease.connected is self._connected
                LOGGER.info(
                    "ble.session_release_failed role=%s address=%s name=%s",
                    lease.role.value,
                    lease.endpoint.address,
                    lease.endpoint.name,
                )
                await self._clear_cached_locked(forget_endpoint=True)
                if not was_cached:
                    await self._disconnect(lease.connected)
                return
            if keep:
                LOGGER.debug(
                    "ble.session_release_cached role=%s address=%s name=%s",
                    lease.role.value,
                    lease.endpoint.address,
                    lease.endpoint.name,
                )
                return
            await self._clear_cached_locked(forget_endpoint=False)
        finally:
            self._lease_lock.release()

    def _endpoint_for_acquire(self, endpoint: PrinterEndpoint) -> PrinterEndpoint:
        cached = self.cached_endpoint_for(endpoint)
        return cached if cached is not None else endpoint

    async def _connected_for_endpoint(
        self,
        endpoint: PrinterEndpoint,
        *,
        connect_timeout_s: float | None,
        model_override: PrinterModel | None,
    ) -> ConnectedT:
        connected = self._connected
        connected_endpoint = self._connected_endpoint
        if connected is not None and connected_endpoint is not None:
            if connected_endpoint.matches(endpoint) and self._cached_model_usable(
                connected,
                model_override,
            ):
                return connected
            forget_endpoint = not connected_endpoint.matches(endpoint)
            await self._clear_cached_locked(forget_endpoint=forget_endpoint)

        timeout_s = self._connect_timeout_s if connect_timeout_s is None else connect_timeout_s
        try:
            connected = await self._connect_with_retry(
                endpoint,
                timeout_s=timeout_s,
                model_override=model_override,
            )
        except Exception:
            if self._known_endpoint is not None and self._known_endpoint.matches(endpoint):
                self._known_endpoint = None
            raise
        self._connected = connected
        self._connected_endpoint = endpoint
        self._known_endpoint = endpoint
        return connected

    async def _connect_with_retry(
        self,
        endpoint: PrinterEndpoint,
        *,
        timeout_s: float | None,
        model_override: PrinterModel | None,
    ) -> ConnectedT:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                LOGGER.info(
                    "ble.session_connect address=%s name=%s attempt=%s attempts=%s",
                    endpoint.address,
                    endpoint.name,
                    attempt,
                    self._retry_policy.max_attempts,
                )
                connection = self._connector(endpoint, model_override)
                if timeout_s is None:
                    return await connection
                return await asyncio.wait_for(connection, timeout=timeout_s)
            except Exception as exc:
                last_error = exc
                if attempt >= self._retry_policy.max_attempts:
                    break
                delay_s = self._retry_policy.delay_before_retry(attempt)
                LOGGER.warning(
                    "ble.session_connect_retry address=%s name=%s attempt=%s "
                    "attempts=%s delay_s=%s error_type=%s error=%s",
                    endpoint.address,
                    endpoint.name,
                    attempt,
                    self._retry_policy.max_attempts,
                    delay_s,
                    type(exc).__name__,
                    exc,
                )
                if delay_s > 0:
                    await self._sleep(delay_s)
        if last_error is not None:
            raise last_error
        raise RuntimeError("BLE session connection failed without an exception")

    def _cached_model_usable(
        self,
        connected: ConnectedT,
        requested_model: PrinterModel | None,
    ) -> bool:
        if requested_model is None or self._connected_model is None:
            return True
        cached_model = self._connected_model(connected)
        if cached_model is None or cached_model == requested_model:
            return True
        cached_spec = spec_for(cached_model)
        requested_spec = spec_for(requested_model)
        return (cached_spec.width, cached_spec.height) == (
            requested_spec.width,
            requested_spec.height,
        )

    async def _clear_cached_locked(self, *, forget_endpoint: bool) -> None:
        connected = self._connected
        self._connected = None
        self._connected_endpoint = None
        if forget_endpoint:
            self._known_endpoint = None
        if connected is not None:
            await self._disconnect(connected)

    async def _disconnect(self, connected: ConnectedT) -> None:
        with suppress(Exception):
            await connected.disconnect()


def _normalize_instax_name(name: str) -> str:
    return re.sub(r"\s*\((IOS|ANDROID)\)$", "", name.strip(), flags=re.IGNORECASE).strip()
