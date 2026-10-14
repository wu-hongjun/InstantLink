from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRIDGE_ROOT = Path(__file__).resolve().parents[1]
PROFILE = BRIDGE_ROOT / "config" / "instantlink-bridge-unused-media.conf"
PROVISION = BRIDGE_ROOT / "scripts" / "provision-sd.sh"
BOOT_DIET = BRIDGE_ROOT / "scripts" / "boot-diet.sh"
UNUSED_MODULES = {
    "bcm2835_v4l2",
    "bcm2835_codec",
    "bcm2835_isp",
    "vc_sm_cma",
    "snd_bcm2835",
}


def sandbox_environment(tmp_path: Path) -> dict[str, str]:
    tools = tmp_path / "tools"
    tools.mkdir()
    # Use actual install/chmod/awk/sed against the offline root. The target's ib
    # identity and systemd are not identities or services on the test host.
    for command in ("chown", "chgrp", "systemctl", "systemd-analyze", "journalctl"):
        executable = tools / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    # Provisioning targets Linux GNU install. Homebrew exposes the same utility
    # with a g prefix on macOS; do not substitute BSD install's different -D.
    ginstall = shutil.which("ginstall")
    if ginstall is not None:
        (tools / "install").symlink_to(ginstall)
    bash_environment = tmp_path / "bash-environment"
    bash_environment.write_text(
        # The stub systemctl reports no units. Bash 3 on macOS lacks mapfile;
        # assigning no results is the correct operation for that empty output.
        "if ! type mapfile >/dev/null 2>&1; then mapfile() { return 0; }; fi\n",
        encoding="utf-8",
    )
    return {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "BASH_ENV": str(bash_environment),
    }


def test_profile_blocks_only_unused_leaf_aliases() -> None:
    directives = [
        line.split()
        for line in PROFILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert len(directives) == len(UNUSED_MODULES)
    assert all(len(parts) == 2 and parts[0] == "blacklist" for parts in directives)
    assert {parts[1] for parts in directives} == UNUSED_MODULES
    # No install override or shared-driver blacklist: explicit diagnostic loads
    # remain possible, and SPI/LCD/Bluetooth retain their normal loader paths.


def test_offline_provision_installs_profile_idempotently_without_replacing_user_config(
    tmp_path: Path,
) -> None:
    if sys.platform == "darwin" and shutil.which("ginstall") is None:
        pytest.skip("Linux provisioning requires GNU install; install coreutils on macOS")
    target = tmp_path / "root"
    (target / "etc/InstantLinkBridge").mkdir(parents=True)
    (target / "etc/modprobe.d").mkdir()
    (target / "etc/passwd").write_text("ib:x:1000:1000::/:/bin/false\n", encoding="utf-8")
    (target / "etc/group").write_text("ib:x:1000:\n", encoding="utf-8")
    user_config = target / "etc/InstantLinkBridge/config.toml"
    user_config.write_text(
        '[ftp]\nusername = "camera-user"\npassword = "private-fixture-password"\n'
        "[display]\nrotation = 270\n",
        encoding="utf-8",
    )
    unrelated_profile = target / "etc/modprobe.d/user.conf"
    unrelated_profile.write_text("options user_driver enabled=1\n", encoding="utf-8")
    snapshots = {path: path.read_bytes() for path in (user_config, unrelated_profile)}
    environment = sandbox_environment(tmp_path)

    for _ in range(2):
        result = subprocess.run(
            ["bash", str(PROVISION), str(target)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        installed = target / "etc/modprobe.d/instantlink-bridge-unused-media.conf"
        assert installed.read_bytes() == PROFILE.read_bytes()
        assert installed.stat().st_mode & 0o777 == 0o644
        for path, expected in snapshots.items():
            assert path.read_bytes() == expected


@pytest.mark.parametrize("present", [True, False])
def test_boot_report_reads_profile_without_mutating_it(tmp_path: Path, present: bool) -> None:
    config = tmp_path / "media.conf"
    if present:
        config.write_bytes(PROFILE.read_bytes())
    environment = sandbox_environment(tmp_path)
    environment.update(
        {
            "INSTANTLINK_BRIDGE_MEDIA_MODULE_CONFIG": str(config),
            "INSTANTLINK_BRIDGE_BOOT_CONFIG": str(tmp_path / "missing-config.txt"),
        }
    )

    result = subprocess.run(
        ["bash", str(BOOT_DIET), "--report"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Unused VCHI media alias autoload checks" in result.stdout
    if present:
        assert config.read_bytes() == PROFILE.read_bytes()
        for module in UNUSED_MODULES:
            assert f"present: blacklist {module}" in result.stdout
    else:
        assert (
            "missing; install the tracked Bridge media module profile and reboot" in result.stdout
        )
        assert not config.exists()
