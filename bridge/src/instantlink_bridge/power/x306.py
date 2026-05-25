"""SupTronics/Geekworm X306 UPS power backend.

The X306 18650 shield provides power-path management, charging, LEDs, and a
hardware power button. It does not expose a host-readable fuel gauge to Linux, so
the firmware must not invent battery percentage or charging state.
"""

from __future__ import annotations

from dataclasses import dataclass

from instantlink_bridge.power.pisugar import BatteryState

X306_MODEL_NAME = "SupTronics X306 18650 UPS"
X306_NO_TELEMETRY = "X306 has LED-only battery indication; no host telemetry"


@dataclass(frozen=True, slots=True)
class X306BatteryClient:
    """Battery provider for X306 hardware without software telemetry."""

    model: str = X306_MODEL_NAME

    def read_battery_state(self) -> BatteryState:
        """Return a truthful unavailable telemetry snapshot for X306."""

        return BatteryState(
            available=False,
            model=self.model,
            error=X306_NO_TELEMETRY,
        )


@dataclass(frozen=True, slots=True)
class NoBatteryClient:
    """Battery provider for systems where bridge telemetry is intentionally off."""

    def read_battery_state(self) -> BatteryState:
        """Return a disabled telemetry snapshot."""

        return BatteryState.unavailable(error="battery telemetry disabled")
