from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wifi-mode.sh"
UUID = "12345678-1234-1234-1234-123456789abc"
HOST = "192.168.8.1"
SSID = "InstantLink:Bridge\\Test"
PSK = "88652231"
DEVICE = "/org/freedesktop/NetworkManager/Devices/3"
ACTIVE = "/org/freedesktop/NetworkManager/ActiveConnection/7"


def _stamp_source() -> str:
    source = SCRIPT.read_text().split("python3 -c '\nimport hashlib", 1)[1]
    return "import hashlib" + source.split('\n\' "${operation}"', 1)[0]


def _settings() -> dict[str, Any]:
    def variants(**values: object) -> dict[str, dict[str, object]]:
        return {key.replace("_", "-"): {"data": value} for key, value in values.items()}

    return {
        "connection": variants(uuid=UUID, interface_name="wlan0", autoconnect=False),
        "802-11-wireless": variants(mode="ap", band="bg", channel=6, ssid=list(SSID.encode())),
        "802-11-wireless-security": variants(
            key_mgmt="wpa-psk", proto=["rsn"], pairwise=["ccmp"], group=["ccmp"], wps_method=1
        ),
        "ipv4": variants(
            method="shared",
            never_default=True,
            address_data=[{"address": {"data": HOST}, "prefix": {"data": 24}}],
        ),
        "ipv6": variants(method="disabled"),
    }


class _NetworkManager:
    def __init__(self) -> None:
        self.saved = [
            UUID,
            "wlan0",
            "no",
            "ap",
            "bg",
            "6",
            SSID,
            "wpa-psk",
            "rsn",
            "ccmp",
            "ccmp",
            PSK,
            "0x1 (disabled)",
            "shared",
            f"{HOST}/24",
            "yes",
            "disabled",
        ]
        self.active = ["100 (connected)", UUID, DEVICE, ACTIVE]
        self.addresses = [f"{HOST}/24"]
        self.applied = _settings()
        self.version = 97
        self.version_after: int | None = None
        self.owner = ":1.8"
        self.owner_after: str | None = None
        self.active_after: list[str] | None = None
        self.fail_read = False
        self.commands: list[list[str]] = []

    def run(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 3
        assert kwargs["capture_output"] is True
        assert isinstance(kwargs["env"], dict) and kwargs["env"]["LC_ALL"] == "C"
        self.commands.append(args)
        if self.fail_read:
            raise subprocess.CalledProcessError(1, args, output=f"secret={PSK}")
        if "--show-secrets" in args:
            assert args[-2:] == ["uuid", UUID]
            output = "\n".join(self.saved)
        elif "GENERAL.STATE,GENERAL.CON-UUID,GENERAL.DBUS-PATH,GENERAL.CON-PATH" in args:
            count = sum(
                "GENERAL.STATE,GENERAL.CON-UUID,GENERAL.DBUS-PATH,GENERAL.CON-PATH" in c
                for c in self.commands
            )
            output = "\n".join(
                self.active_after if count > 1 and self.active_after else self.active
            )
        elif "IP4.ADDRESS" in args:
            output = "\n".join(self.addresses)
        elif "GetNameOwner" in args:
            count = sum("GetNameOwner" in c for c in self.commands)
            owner = self.owner_after if count > 1 and self.owner_after else self.owner
            output = json.dumps({"type": "s", "data": [owner]})
        elif "GetAppliedConnection" in args:
            assert args[4] == self.owner
            count = sum("GetAppliedConnection" in c for c in self.commands)
            version = self.version_after if count > 1 and self.version_after else self.version
            output = json.dumps({"type": "a{sa{sv}}t", "data": [self.applied, version]})
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, output + "\n", "")


def _invoke_stamp(
    tmp_path: Path,
    nm: _NetworkManager,
    operation: str,
    *,
    wrong_owner: bool = False,
) -> bool:
    directory = tmp_path / "wifi-state"
    directory.mkdir(mode=0o700, exist_ok=True)
    original_lstat = Path.lstat

    def root_owned(path: Path) -> os.stat_result:
        result = original_lstat(path)
        # CI runs without root. Simulate only the ownership boundary; all mode,
        # symlink, atomic publication, and actual file reads/writes remain real.
        if path == directory or path.parent == directory:
            values = list(result)
            values[4] = 501 if wrong_owner else 0
            return os.stat_result(values)
        return result

    nm.commands.clear()
    with (
        patch.object(sys, "argv", ["stamp", operation, UUID, HOST, SSID, "6", str(directory)]),
        patch.object(sys, "stdin", io.StringIO(PSK + "\n")),
        patch.object(subprocess, "run", nm.run),
        patch.object(Path, "lstat", root_owned),
    ):
        try:
            exec(compile(_stamp_source(), str(SCRIPT), "exec"), {})
        except SystemExit as exc:
            return exc.code == 0
    return True


def test_only_verified_activation_can_establish_reusable_stamp(tmp_path: Path) -> None:
    nm = _NetworkManager()
    assert not _invoke_stamp(tmp_path, nm, "check")
    assert _invoke_stamp(tmp_path, nm, "record")
    path = tmp_path / "wifi-state" / "hotspot-applied.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert PSK not in path.read_text()
    assert _invoke_stamp(tmp_path, nm, "check")


@pytest.mark.parametrize("field", range(17))
def test_every_saved_managed_property_drift_requires_activation(tmp_path: Path, field: int) -> None:
    nm = _NetworkManager()
    assert _invoke_stamp(tmp_path, nm, "record")
    nm.saved[field] = "2" if field == 12 else "different"
    assert not _invoke_stamp(tmp_path, nm, "check")


@pytest.mark.parametrize(
    ("group", "key"),
    [
        ("connection", "uuid"),
        ("connection", "interface-name"),
        ("connection", "autoconnect"),
        ("802-11-wireless", "mode"),
        ("802-11-wireless", "band"),
        ("802-11-wireless", "channel"),
        ("802-11-wireless", "ssid"),
        ("802-11-wireless-security", "key-mgmt"),
        ("802-11-wireless-security", "proto"),
        ("802-11-wireless-security", "pairwise"),
        ("802-11-wireless-security", "group"),
        ("802-11-wireless-security", "wps-method"),
        ("ipv4", "method"),
        ("ipv4", "never-default"),
        ("ipv4", "address-data"),
        ("ipv6", "method"),
    ],
)
def test_saved_profile_match_does_not_hide_applied_drift(
    tmp_path: Path, group: str, key: str
) -> None:
    nm = _NetworkManager()
    assert _invoke_stamp(tmp_path, nm, "record")
    del nm.applied[group][key]
    assert not _invoke_stamp(tmp_path, nm, "check")


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "owner",
        "device",
        "active_path",
        "uuid",
        "inactive",
        "ip",
        "prefix",
        "owner_race",
        "active_race",
        "version_race",
    ],
)
def test_activation_identity_live_address_and_races_invalidate_stamp(
    tmp_path: Path, change: str
) -> None:
    nm = _NetworkManager()
    assert _invoke_stamp(tmp_path, nm, "record")
    if change == "version":
        nm.version += 1
    elif change == "owner":
        nm.owner = ":1.9"
    elif change == "device":
        nm.active[2] = DEVICE + "1"
    elif change == "active_path":
        nm.active[3] = ACTIVE + "1"
    elif change == "uuid":
        nm.active[1] = UUID + "1"
    elif change == "inactive":
        nm.active[0] = "30 (disconnected)"
    elif change == "ip":
        nm.addresses = []
    elif change == "prefix":
        nm.addresses = [HOST + "/16"]
    elif change == "owner_race":
        nm.owner_after = ":1.9"
    elif change == "active_race":
        nm.active_after = ["30 (disconnected)", "", DEVICE, ACTIVE]
    elif change == "version_race":
        nm.version_after = nm.version + 1
    assert not _invoke_stamp(tmp_path, nm, "check")


@pytest.mark.parametrize("bad_stamp", ["malformed", "mode", "symlink", "owner"])
def test_untrusted_stamp_cannot_skip_activation(tmp_path: Path, bad_stamp: str) -> None:
    nm = _NetworkManager()
    assert _invoke_stamp(tmp_path, nm, "record")
    stamp = tmp_path / "wifi-state" / "hotspot-applied.json"
    if bad_stamp == "malformed":
        stamp.write_text("not json")
    elif bad_stamp == "mode":
        stamp.chmod(0o644)
    elif bad_stamp == "symlink":
        target = tmp_path / "target"
        target.write_text(stamp.read_text())
        stamp.unlink()
        stamp.symlink_to(target)
    assert not _invoke_stamp(tmp_path, nm, "check", wrong_owner=bad_stamp == "owner")


def test_failed_secret_read_is_silent_and_preserves_old_stamp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nm = _NetworkManager()
    assert _invoke_stamp(tmp_path, nm, "record")
    path = tmp_path / "wifi-state" / "hotspot-applied.json"
    before = path.read_bytes()
    nm.fail_read = True
    assert not _invoke_stamp(tmp_path, nm, "check")
    assert not _invoke_stamp(tmp_path, nm, "record")
    assert path.read_bytes() == before
    assert capsys.readouterr() == ("", "")


def test_profile_uuid_selection_handles_escaped_names_and_rejects_ambiguity(tmp_path: Path) -> None:
    prefix = SCRIPT.read_text().split("\nrequire_nmcli\n", 1)[0]
    env = dict(os.environ, TEST_NAME=SSID, TEST_UUID=UUID)
    source = (
        prefix
        + """
HOTSPOT_CONNECTION="$TEST_NAME"
nmcli() { printf '%s\\n' "$TEST_ROWS"; }
select_hotspot_uuid
"""
    )
    name = SSID.replace("\\", "\\\\").replace(":", "\\:")
    rows = f"{name}:{UUID}:802-11-wireless:wlan0"
    env["TEST_ROWS"] = rows + f"\n{name}:old:802-11-wireless:"
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == UUID
    env["TEST_ROWS"] = rows.removesuffix("wlan0") + f"\n{name}:other:802-11-wireless:"
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ambiguous" in result.stderr


def test_cleanup_selects_only_inactive_duplicates_and_legacy_profiles() -> None:
    prefix = SCRIPT.read_text().split("\nrequire_nmcli\n", 1)[0]
    name = SSID.replace("\\", "\\\\").replace(":", "\\:")
    rows = "\n".join(
        [
            f"{name}:{UUID}:802-11-wireless:wlan0",
            f"{name}:stale:802-11-wireless:",
            f"{name}:other-active:802-11-wireless:wlan1",
            "InstantBridge-Hotspot:legacy:802-11-wireless:",
            "InstantBridge-Hotspot:legacy-active:802-11-wireless:wlan2",
            "other:other:802-11-wireless:",
        ]
    )
    source = (
        prefix
        + """
HOTSPOT_CONNECTION="$TEST_NAME"
nmcli() { printf '%s\\n' "$TEST_ROWS"; }
select_hotspot_uuid cleanup
"""
    )
    env = dict(os.environ, TEST_NAME=SSID, TEST_ROWS=rows)
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["stale", "legacy"]


@pytest.mark.parametrize("verified", [True, False])
def test_hotspot_keeps_verified_ap_and_activates_on_read_failure(
    tmp_path: Path, verified: bool
) -> None:
    prefix = SCRIPT.read_text().split("\nrequire_nmcli\n", 1)[0]
    calls = tmp_path / "calls"
    source = (
        prefix
        + """
select_hotspot_uuid() { printf '%s\\n' "$TEST_UUID"; }
hotspot_host() { printf '%s\\n' 192.168.8.1; }
hotspot_ssid() { printf '%s\\n' test; }
prepare_hotspot_psk() { :; }
hotspot_psk() { printf '%s\\n' 12345678; }
ensure_wifi_interface() { printf '%s\\n' interface >> "$TEST_CALLS"; }
delete_stale_hotspot_profiles() { printf '%s\\n' cleanup >> "$TEST_CALLS"; }
hotspot_activation_stamp() {
  printf '%s\\n' "stamp $1" >> "$TEST_CALLS"
  [[ "$1" == record || "$TEST_VERIFIED" == 1 ]]
}
run_root() { printf '%s\\n' "$*" >> "$TEST_CALLS"; }
configure_hotspot
"""
    )
    env = dict(
        os.environ,
        TEST_UUID=UUID,
        TEST_CALLS=str(calls),
        TEST_VERIFIED="1" if verified else "0",
    )
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    operations = calls.read_text().splitlines()
    assert operations[0:2] == ["interface", "stamp check"]
    assert operations[-1] == "cleanup"
    if verified:
        assert operations == ["interface", "stamp check", "cleanup"]
    else:
        assert any(f"connection modify uuid {UUID}" in operation for operation in operations)
        assert any("wifi-sec.wps-method 1" in operation for operation in operations)
        assert f"nmcli connection up uuid {UUID} ifname wlan0" in operations
        assert "stamp record" in operations


def test_root_command_preserves_piped_stdin_and_psk_file_contents(tmp_path: Path) -> None:
    # Background commands in a noninteractive shell receive /dev/null unless
    # stdin is explicitly inherited. Exercise the real Bash/Python/tee pipeline.
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    psk_file = tmp_path / "hotspot.psk"
    prefix = SCRIPT.read_text().split("\nrequire_nmcli\n", 1)[0]
    source = (
        prefix
        + """
printf '%s' "$TEST_PSK" | run_root "$TEST_PYTHON" -c \
  'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
PSK_FILE="$TEST_PSK_FILE"
ensure_hotspot_psk_permissions() { chmod 0640 "$PSK_FILE"; }
write_hotspot_psk "$TEST_PSK"
"""
    )
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        TEST_PSK=PSK,
        TEST_PYTHON=sys.executable,
        TEST_PSK_FILE=str(psk_file),
    )
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == hashlib.sha256(PSK.encode()).hexdigest()
    assert psk_file.read_text() == PSK + "\n"
    assert stat.S_IMODE(psk_file.stat().st_mode) == 0o640


@pytest.mark.parametrize(
    ("override", "saved", "expected_success", "expected_generation"),
    [
        (PSK, None, True, False),
        (PSK, "11112222", True, False),
        ("invalid", "11112222", False, False),
        ("", None, True, True),
        ("", "invalid", True, True),
        ("", "11112222", True, False),
    ],
)
def test_psk_preparation_preserves_override_saved_value_generation_and_permissions(
    tmp_path: Path,
    override: str,
    saved: str | None,
    expected_success: bool,
    expected_generation: bool,
) -> None:
    psk = tmp_path / "hotspot.psk"
    calls = tmp_path / "calls"
    if saved is not None:
        psk.write_text(saved + "\n")
        psk.chmod(0o644)
    prefix = SCRIPT.read_text().split("\nrequire_nmcli\n", 1)[0]
    source = (
        prefix
        + """
PSK_FILE="$TEST_PSK_FILE"
run_root() { printf '%s\\n' "$*" >> "$TEST_CALLS"; "$@"; }
getent() { return 1; }
generate_hotspot_psk() { printf '%s\\n' generate >> "$TEST_CALLS"; printf '%s\\n' "$TEST_PSK"; }
prepare_hotspot_psk
hotspot_psk
hotspot_psk
"""
    )
    env = dict(
        os.environ,
        INSTANTLINK_BRIDGE_HOTSPOT_PSK=override,
        TEST_PSK=PSK,
        TEST_PSK_FILE=str(psk),
        TEST_CALLS=str(calls),
    )
    result = subprocess.run(["bash", "-c", source], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is expected_success
    operations = calls.read_text().splitlines() if calls.exists() else []
    assert operations.count("generate") == int(expected_generation)
    if override:
        assert not operations
        assert psk.read_text() == saved + "\n" if saved is not None else not psk.exists()
    else:
        assert stat.S_IMODE(psk.stat().st_mode) == 0o640
        assert sum(operation.startswith("chmod ") for operation in operations) == 1
    if expected_success:
        expected = override or (PSK if expected_generation else saved)
        assert result.stdout.splitlines() == [expected, expected]


@pytest.mark.parametrize(
    "operation", ["stamp", "psk", "configure_new_psk", "configure_existing_psk"]
)
@pytest.mark.parametrize("root_launch", [True, False])
def test_cancelling_private_stdin_command_terminates_worker_and_releases_lock(
    tmp_path: Path, operation: str, root_launch: bool
) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import fcntl,hashlib,os,pathlib,sys,time\n"
        "fcntl.flock(9, fcntl.LOCK_EX)\n"
        "data = sys.stdin.buffer.read()\n"
        "pathlib.Path(os.environ['TEST_INPUT_HASH']).write_text(hashlib.sha256(data).hexdigest())\n"
        "pathlib.Path(os.environ['TEST_WORKER_PID']).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    command_name = (
        "python3"
        if operation == "stamp"
        else "chmod"
        if operation == "configure_existing_psk"
        else "tee"
    )
    command = tmp_path / command_name
    command.write_text('#!/bin/sh\nexec "$TEST_PYTHON" "$TEST_WORKER"\n')
    command.chmod(0o755)
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    # Simulate the root-only stamp admission on unprivileged CI. Exercise both
    # actual command launch branches; the installed script always uses root.
    prefix = SCRIPT.read_text().split("\nrequire_nmcli\n", 1)[0]
    prefix = prefix.replace("${EUID}", "${TEST_EUID}").replace(
        'if [[ "${TEST_EUID}" -eq 0 ]]; then\n    "$@"',
        'if [[ "${TEST_ROOT_LAUNCH}" == 1 ]]; then\n    "$@"',
    )
    source = prefix + '\nexec 9>"$TEST_LOCK_FILE"\n'
    if operation == "stamp":
        source += '\nhotspot_activation_stamp check test 192.168.8.1 test "$TEST_PSK"\n'
    elif operation == "psk":
        source += '\nPSK_FILE="$TEST_PSK_FILE"\nwrite_hotspot_psk "$TEST_PSK"\n'
    else:
        source += """
PSK_FILE="$TEST_PSK_FILE"
select_hotspot_uuid() { printf '%s\\n' test; }
hotspot_host() { printf '%s\\n' 192.168.8.1; }
hotspot_ssid() { printf '%s\\n' test; }
generate_hotspot_psk() { printf '%s\\n' "$TEST_PSK"; }
getent() { return 1; }
configure_hotspot
"""
    worker_pid = tmp_path / "worker.pid"
    lock = tmp_path / "mode.lock"
    input_hash = tmp_path / "input.sha"
    if operation == "configure_existing_psk":
        (tmp_path / "hotspot.psk").write_text(PSK + "\n")
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        TEST_PYTHON=sys.executable,
        TEST_WORKER=str(worker),
        TEST_WORKER_PID=str(worker_pid),
        TEST_INPUT_HASH=str(input_hash),
        TEST_LOCK_FILE=str(lock),
        TEST_PSK_FILE=str(tmp_path / "hotspot.psk"),
        TEST_PSK=PSK,
        TEST_EUID="0",
        TEST_ROOT_LAUNCH="1" if root_launch else "0",
    )
    process = subprocess.Popen(
        ["bash", "-c", source],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 3
        while not worker_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker_pid.exists(), "helper did not start its private-input command"
        expected_input = b"" if operation == "configure_existing_psk" else (PSK + "\n").encode()
        assert input_hash.read_text() == hashlib.sha256(expected_input).hexdigest()
        with lock.open("w") as held:
            with pytest.raises(BlockingIOError):
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        process.terminate()
        process.communicate(timeout=2)
        assert process.returncode == 143
        with lock.open("w") as released:
            fcntl.flock(released.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if process.poll() is None:
            process.kill()
        if worker_pid.exists():
            try:
                os.kill(int(worker_pid.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
        process.communicate(timeout=2)
