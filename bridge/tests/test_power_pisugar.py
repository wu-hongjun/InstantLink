from __future__ import annotations

from datetime import datetime
from pathlib import Path

from instantlink_bridge.power.pisugar import (
    BATTERY_STATE_COMMANDS,
    BatteryState,
    PiSugarClient,
    PiSugarProtocolError,
    PiSugarResponse,
    parse_pisugar_response,
)


def test_parse_pisugar_response_accepts_key_value_lines() -> None:
    assert parse_pisugar_response("battery: 81.5\n") == PiSugarResponse(
        key="battery",
        value="81.5",
    )
    assert parse_pisugar_response("echo\n%battery: 80%\n") == PiSugarResponse(
        key="battery",
        value="80%",
    )
    assert parse_pisugar_response("not a response") is None


def test_client_reads_typed_battery_state_from_fake_socket() -> None:
    transport = FakeTransport(
        {
            "get battery": "battery: 19.5",
            "get battery_v": "battery_v: 3.82",
            "get battery_charging": "battery_charging: false",
            "get battery_power_plugged": "battery_power_plugged: true",
            "get battery_allow_charging": "battery_allow_charging: true",
            "get model": "model: PiSugar 3",
            "get firmware_version": "firmware_version: 1.2.3",
            "get rtc_time": "rtc_time: 2026-05-20T12:34:56+00:00",
        }
    )
    client = PiSugarClient(socket_path=Path("/tmp/fake-pisugar.sock"), transport=transport)

    state = client.read_battery_state()

    assert state == BatteryState(
        available=True,
        percentage=19.5,
        voltage_v=3.82,
        is_charging=False,
        power_plugged=True,
        charging_allowed=True,
        model="PiSugar 3",
        firmware_version="1.2.3",
        rtc_time=datetime.fromisoformat("2026-05-20T12:34:56+00:00"),
        socket_path=Path("/tmp/fake-pisugar.sock"),
    )
    assert state.external_power is True
    assert transport.commands == [field.command for field in BATTERY_STATE_COMMANDS]


def test_client_derives_new_model_charging_when_legacy_field_is_missing() -> None:
    transport = FakeTransport(
        {
            "get battery": "battery: 88",
            "get battery_power_plugged": "battery_power_plugged: true",
            "get battery_allow_charging": "battery_allow_charging: true",
        }
    )
    client = PiSugarClient(transport=transport)

    state = client.read_battery_state()

    assert state.available
    assert state.percentage == 88.0
    assert state.is_charging is True
    assert state.external_power is True


def test_client_tolerates_missing_socket(tmp_path: Path) -> None:
    client = PiSugarClient(socket_path=tmp_path / "missing-pisugar.sock")

    state = client.read_battery_state()

    assert state.available is False
    assert state.error is not None
    assert "missing" in state.error


def test_client_keeps_partial_state_when_optional_commands_fail() -> None:
    transport = FakeTransport(
        {
            "get battery": "battery: 83",
            "get model": "model: PiSugar 3",
        }
    )
    client = PiSugarClient(transport=transport)

    state = client.read_battery_state()

    assert state.available
    assert state.percentage == 83.0
    assert state.model == "PiSugar 3"
    assert state.voltage_v is None


class FakeTransport:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.commands: list[str] = []

    def request(self, command: str) -> str:
        self.commands.append(command)
        try:
            return self._responses[command]
        except KeyError as exc:
            raise PiSugarProtocolError(f"no fake response for {command}") from exc
