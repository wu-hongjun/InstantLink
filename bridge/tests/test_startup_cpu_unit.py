"""Keep the pre-interpreter CPU boost limited and nonfatal on unsupported boards."""

import configparser
import shlex
from pathlib import Path

BRIDGE_ROOT = Path(__file__).resolve().parents[1]


def test_service_boosts_before_python_and_restores_scaling_on_stop() -> None:
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(BRIDGE_ROOT / "systemd/instantlink-bridge.service")
    service = unit["Service"]
    helper = "/usr/local/sbin/instantlink-bridge-cpu-mode"

    # systemd executes this hook before ExecStart. Its '-' prefix ignores an
    # unavailable scaling policy/helper, and '-n' prevents sudo prompting.
    assert shlex.split(service["ExecStartPre"]) == [
        "-/usr/bin/sudo",
        "-n",
        helper,
        "performance",
    ]
    assert shlex.split(service["ExecStart"])[0].endswith("/.venv/bin/instantlink-bridge")
    # ExecStopPost also runs after failed startup and SIGKILL; ExecStop would
    # leave an unsuccessful start boosted because no running service exists.
    assert shlex.split(service["ExecStopPost"]) == [
        "-/usr/bin/sudo",
        "-n",
        helper,
        "ondemand",
    ]
    assert service["User"] == "ib"
    assert service["Type"] == "notify"
    assert service["WatchdogSec"] == "30"


def test_boot_boost_uses_existing_exact_sudo_policy() -> None:
    policy = (BRIDGE_ROOT / "config/sudoers-instantlink-bridge-cpu").read_text()
    assert "ib ALL=(root) NOPASSWD: /usr/local/sbin/instantlink-bridge-cpu-mode performance" in (
        policy.splitlines()
    )
    assert "ib ALL=(root) NOPASSWD: /usr/local/sbin/instantlink-bridge-cpu-mode ondemand" in (
        policy.splitlines()
    )
