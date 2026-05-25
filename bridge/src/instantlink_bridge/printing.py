"""Print progress events shared by orchestration, BLE, and UI layers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class PrintStage(StrEnum):
    """User-visible stages for one print job."""

    SELECTING_PRINTER = "selecting_printer"
    CONNECTING = "connecting"
    PREPARING = "preparing"
    SENDING = "sending"
    FINISHING = "finishing"


@dataclass(frozen=True, slots=True)
class PrintProgress:
    """Progress update for the 240x240 LCD print screen."""

    stage: PrintStage
    title: str
    detail: str | None = None
    percent: int | None = None


PrintProgressCallback = Callable[[PrintProgress], None]
