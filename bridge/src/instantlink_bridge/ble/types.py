"""Transport-neutral Printer records and failures shared by both backends."""

from __future__ import annotations

import re
from dataclasses import dataclass

from instantlink_bridge.ble.models import PrinterModel


class PrinterError(RuntimeError):
    """Base printer protocol error."""


class UnexpectedResponseError(PrinterError):
    """Raised when a printer response does not match the command."""


class PrintRejectedError(PrinterError):
    """Raised when the printer rejects a print operation."""


class NoFilmError(PrintRejectedError):
    """Raised when no film remains."""


class CoverOpenError(PrintRejectedError):
    """Raised when the printer cover is open."""


class PrinterBusyError(PrintRejectedError):
    """Raised when the printer is busy."""


class LowPrinterBatteryError(PrintRejectedError):
    """Raised when the printer battery is too low."""


@dataclass(frozen=True, slots=True)
class PrinterStatus:
    """Printer status summary."""

    battery: int
    is_charging: bool
    film_remaining: int
    print_count: int | None
    model: PrinterModel
    name: str


@dataclass(frozen=True, slots=True)
class DiscoveredPrinter:
    """BLE advertisement summary."""

    name: str
    address: str
    device: object | None = None


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


def _normalize_instax_name(name: str) -> str:
    return re.sub(r"\s*\((IOS|ANDROID)\)$", "", name.strip(), flags=re.IGNORECASE).strip()
