from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wifi-mode.sh"


@pytest.mark.parametrize(
    ("interface_present", "pi_model", "driver_loaded", "reload_succeeds", "expected_success"),
    [
        (True, True, True, True, True),
        (False, True, True, True, True),
        (False, True, False, True, True),
        (False, False, True, True, False),
        (False, True, True, False, False),
    ],
)
def test_wifi_driver_recovery(
    tmp_path: Path,
    interface_present: bool,
    pi_model: bool,
    driver_loaded: bool,
    reload_succeeds: bool,
    expected_success: bool,
) -> None:
    net = tmp_path / "net"
    net.mkdir()
    if interface_present:
        (net / "wlan0").mkdir()
    modules = tmp_path / "modules"
    modules.mkdir()
    if driver_loaded:
        (modules / "brcmfmac").mkdir()
    model = tmp_path / "model"
    model.write_bytes(b"Raspberry Pi Zero 2 W\x00" if pi_model else b"Other computer\x00")
    calls = tmp_path / "calls"
    source = SCRIPT.read_text().split("\nrequire_nmcli\n", maxsplit=1)[0]
    source += """
run_root() {
  printf '%s\\n' "$*" >> "$TEST_CALLS"
  if [[ "$*" == "modprobe brcmfmac" && "$TEST_RELOAD_SUCCEEDS" == "1" ]]; then
    mkdir -p "$INSTANTLINK_BRIDGE_NET_SYSFS/wlan0"
  fi
}
sleep() { :; }
ensure_wifi_interface
"""
    env = dict(os.environ)
    env.update(
        INSTANTLINK_BRIDGE_NET_SYSFS=str(net),
        INSTANTLINK_BRIDGE_MODEL_PATH=str(model),
        INSTANTLINK_BRIDGE_MODULE_SYSFS=str(modules),
        TEST_CALLS=str(calls),
        TEST_RELOAD_SUCCEEDS="1" if reload_succeeds else "0",
    )
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is expected_success, result.stderr
    operations = calls.read_text().splitlines()
    assert operations[0] == "nmcli radio wifi on"
    if interface_present or not pi_model:
        assert operations == ["nmcli radio wifi on"]
    else:
        expected = ["nmcli radio wifi on"]
        if driver_loaded:
            expected.append("modprobe -r brcmfmac")
        expected.append("modprobe brcmfmac")
        assert operations == expected


def test_cancelling_helper_terminates_its_running_command(tmp_path: Path) -> None:
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text('#!/bin/sh\nexec "$@"\n')
    fake_sudo.chmod(0o755)
    worker_pid = tmp_path / "worker.pid"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(worker_pid)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    source = SCRIPT.read_text().split("\nrequire_nmcli\n", maxsplit=1)[0]
    source += '\nrun_root "$TEST_PYTHON" "$TEST_WORKER"\n'
    env = dict(os.environ)
    env.update(
        PATH=f"{tmp_path}:{env['PATH']}", TEST_PYTHON=sys.executable, TEST_WORKER=str(worker)
    )
    process = subprocess.Popen(
        ["bash", "-c", source], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 3
        while not worker_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker_pid.exists(), "helper did not start its command"
        process.terminate()
        process.communicate(timeout=2)
        assert process.returncode == 143
    finally:
        if process.poll() is None:
            process.kill()
        if worker_pid.exists():
            try:
                os.kill(int(worker_pid.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
        process.communicate(timeout=2)
