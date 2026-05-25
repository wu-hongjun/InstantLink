"""PiSugar power-manager Unix socket client."""

from __future__ import annotations

import logging
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Protocol, Self

LOGGER = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = Path("/tmp/pisugar-server.sock")
DEFAULT_SOCKET_TIMEOUT_S = 1.0


class PiSugarError(Exception):
    """Base error for PiSugar socket access."""


class PiSugarSocketUnavailable(PiSugarError):
    """Raised when the PiSugar Unix socket is not reachable."""


class PiSugarProtocolError(PiSugarError):
    """Raised when the PiSugar server returns an unusable response."""


@dataclass(frozen=True, slots=True)
class PiSugarResponse:
    """One parsed `key: value` response line from pisugar-server."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class BatteryState:
    """Typed bridge battery, charging, and RTC snapshot."""

    available: bool
    percentage: float | None = None
    voltage_v: float | None = None
    is_charging: bool | None = None
    power_plugged: bool | None = None
    charging_allowed: bool | None = None
    model: str | None = None
    firmware_version: str | None = None
    rtc_time: datetime | None = None
    socket_path: Path = DEFAULT_SOCKET_PATH
    error: str | None = None

    @classmethod
    def unavailable(
        cls,
        *,
        socket_path: Path = DEFAULT_SOCKET_PATH,
        error: str | None = None,
    ) -> Self:
        """Build a snapshot for systems without readable battery telemetry."""

        return cls(available=False, socket_path=socket_path, error=error)

    @classmethod
    def from_fields(
        cls,
        fields: Mapping[str, str],
        *,
        socket_path: Path = DEFAULT_SOCKET_PATH,
    ) -> Self:
        """Parse known PiSugar response fields into a typed snapshot."""

        power_plugged = _parse_bool(fields.get("battery_power_plugged"))
        charging_allowed = _parse_bool(fields.get("battery_allow_charging"))
        legacy_charging = _parse_bool(fields.get("battery_charging"))
        is_charging = legacy_charging
        if is_charging is None and power_plugged is not None and charging_allowed is not None:
            is_charging = power_plugged and charging_allowed

        return cls(
            available=True,
            percentage=_parse_float(fields.get("battery")),
            voltage_v=_parse_float(fields.get("battery_v")),
            is_charging=is_charging,
            power_plugged=power_plugged,
            charging_allowed=charging_allowed,
            model=_optional_text(fields.get("model")),
            firmware_version=_optional_text(fields.get("firmware_version")),
            rtc_time=_parse_datetime(fields.get("rtc_time")),
            socket_path=socket_path,
        )

    @property
    def external_power(self) -> bool | None:
        """Whether PiSugar currently reports external input power."""

        if self.power_plugged is not None:
            return self.power_plugged
        if self.is_charging is not None:
            return self.is_charging
        return None


class PiSugarTransport(Protocol):
    """Transport for one command/response exchange with pisugar-server."""

    def request(self, command: str) -> str:
        """Send one command and return the raw response text."""


@dataclass(frozen=True, slots=True)
class UnixSocketPiSugarTransport:
    """Synchronous Unix socket transport for `/tmp/pisugar-server.sock`."""

    socket_path: Path = DEFAULT_SOCKET_PATH
    timeout_s: float = DEFAULT_SOCKET_TIMEOUT_S
    read_size: int = 4096

    def request(self, command: str) -> str:
        """Send one command to the PiSugar power manager socket."""

        if not self.socket_path.exists():
            raise PiSugarSocketUnavailable(f"PiSugar socket missing: {self.socket_path}")
        if self.timeout_s <= 0 or not isfinite(self.timeout_s):
            raise ValueError("timeout_s must be a finite value greater than 0")
        if self.read_size <= 0:
            raise ValueError("read_size must be greater than 0")

        payload = f"{command.strip()}\n".encode()
        chunks: list[bytes] = []
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout_s)
                client.connect(str(self.socket_path))
                client.sendall(payload)
                while True:
                    try:
                        chunk = client.recv(self.read_size)
                    except TimeoutError as exc:
                        if chunks:
                            break
                        raise PiSugarSocketUnavailable(
                            f"PiSugar socket timed out: {self.socket_path}"
                        ) from exc
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
        except FileNotFoundError as exc:
            raise PiSugarSocketUnavailable(f"PiSugar socket missing: {self.socket_path}") from exc
        except ConnectionRefusedError as exc:
            raise PiSugarSocketUnavailable(f"PiSugar socket refused: {self.socket_path}") from exc
        except OSError as exc:
            raise PiSugarSocketUnavailable(f"PiSugar socket failed: {self.socket_path}") from exc

        if not chunks:
            raise PiSugarProtocolError(f"PiSugar socket returned no data: {self.socket_path}")
        return b"".join(chunks).decode("utf-8", errors="replace").strip()


@dataclass(frozen=True, slots=True)
class PiSugarFieldCommand:
    """One PiSugar command and the response key expected from it."""

    command: str
    key: str


BATTERY_STATE_COMMANDS: tuple[PiSugarFieldCommand, ...] = (
    PiSugarFieldCommand("get battery", "battery"),
    PiSugarFieldCommand("get battery_v", "battery_v"),
    PiSugarFieldCommand("get battery_charging", "battery_charging"),
    PiSugarFieldCommand("get battery_power_plugged", "battery_power_plugged"),
    PiSugarFieldCommand("get battery_allow_charging", "battery_allow_charging"),
    PiSugarFieldCommand("get model", "model"),
    PiSugarFieldCommand("get firmware_version", "firmware_version"),
    PiSugarFieldCommand("get rtc_time", "rtc_time"),
)


class PiSugarClient:
    """High-level PiSugar socket client with partial-field tolerance."""

    def __init__(
        self,
        *,
        socket_path: Path = DEFAULT_SOCKET_PATH,
        timeout_s: float = DEFAULT_SOCKET_TIMEOUT_S,
        transport: PiSugarTransport | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._transport = (
            transport
            if transport is not None
            else UnixSocketPiSugarTransport(socket_path=socket_path, timeout_s=timeout_s)
        )

    @property
    def socket_path(self) -> Path:
        """Configured PiSugar Unix socket path."""

        return self._socket_path

    def request(self, command: str) -> str:
        """Send a raw command to pisugar-server."""

        return self._transport.request(command)

    def get_value(self, command: str, *, expected_key: str | None = None) -> str | None:
        """Return a parsed response value for one PiSugar command."""

        raw_response = self.request(command)
        parsed = parse_pisugar_response(raw_response)
        if parsed is None:
            LOGGER.debug("pisugar.malformed_response command=%s response=%r", command, raw_response)
            return None
        if expected_key is not None and parsed.key != expected_key:
            LOGGER.debug(
                "pisugar.unexpected_response_key command=%s expected=%s actual=%s",
                command,
                expected_key,
                parsed.key,
            )
            return None
        return parsed.value

    def read_battery_state(self) -> BatteryState:
        """Read battery, charging, model, firmware, and RTC fields."""

        fields: dict[str, str] = {}
        saw_socket_response = False
        for field_command in BATTERY_STATE_COMMANDS:
            try:
                value = self.get_value(
                    field_command.command,
                    expected_key=field_command.key,
                )
            except PiSugarSocketUnavailable as exc:
                if not saw_socket_response:
                    return BatteryState.unavailable(socket_path=self._socket_path, error=str(exc))
                LOGGER.debug(
                    "pisugar.partial_read_unavailable command=%s",
                    field_command.command,
                    exc_info=exc,
                )
                break
            except PiSugarProtocolError as exc:
                if not saw_socket_response:
                    return BatteryState.unavailable(socket_path=self._socket_path, error=str(exc))
                LOGGER.debug(
                    "pisugar.partial_read_protocol_error command=%s",
                    field_command.command,
                    exc_info=exc,
                )
                continue
            saw_socket_response = True
            if value is not None:
                fields[field_command.key] = value

        if not saw_socket_response:
            return BatteryState.unavailable(
                socket_path=self._socket_path,
                error="PiSugar socket returned no parseable response",
            )
        return BatteryState.from_fields(fields, socket_path=self._socket_path)


def parse_pisugar_response(response: str) -> PiSugarResponse | None:
    """Parse the first `key: value` line from a PiSugar response."""

    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        normalized_key = key.strip().lstrip("%")
        if not normalized_key:
            continue
        return PiSugarResponse(key=normalized_key, value=value.strip())
    return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().removesuffix("%").strip()
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not isfinite(parsed):
        return None
    return parsed


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
