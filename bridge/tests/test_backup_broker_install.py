"""Exercise the privileged helper installer without root or systemd access."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRIDGE_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = BRIDGE_ROOT / "scripts/install-backup-broker.sh"


def _installer_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, str], Path]:
    repo = tmp_path / "bridge"
    for relative in (
        "scripts/install-backup-broker.sh",
        "scripts/backup-broker.py",
        "src/instantlink_bridge/manager/backup.py",
        "systemd/instantlink-bridge-backup.socket",
        "systemd/instantlink-bridge-backup@.service",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BRIDGE_ROOT / relative, target)
    root = tmp_path / "root"
    root.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "tools.jsonl"
    tools_script = (
        f"#!{sys.executable}\n"
        + """
import json
import os
import pathlib
import shutil
import sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["BROKER_TEST_LOG"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\\n")
if name == "id":
    print("0")
elif name == "install":
    mode = int(args[args.index("-m") + 1], 8)
    remaining = args.copy()
    for option in ("-m", "-o", "-g"):
        index = remaining.index(option)
        del remaining[index:index + 2]
    if "-d" in remaining:
        remaining.remove("-d")
        for item in remaining:
            target = pathlib.Path(item)
            target.mkdir(parents=True, exist_ok=True)
            target.chmod(mode)
    else:
        shutil.copyfile(remaining[0], remaining[1])
        pathlib.Path(remaining[1]).chmod(mode)
"""
    )
    for name in ("id", "install", "systemctl"):
        executable = tools / name
        executable.write_text(tools_script, encoding="utf-8")
        executable.chmod(0o755)
    env = os.environ | {"PATH": f"{tools}:{os.environ['PATH']}", "BROKER_TEST_LOG": str(log)}
    return repo, root, env, log


def _run_installer(repo: Path, root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "scripts/install-backup-broker.sh"), str(root)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installer_refreshes_isolated_root_code_and_enables_offline_socket(tmp_path: Path) -> None:
    repo, root, env, log = _installer_fixture(tmp_path)
    result = _run_installer(repo, root, env)
    assert result.returncode == 0, result.stderr
    trusted = root / "usr/local/libexec/instantlink-bridge-backup"
    assert trusted.stat().st_mode & 0o777 == 0o755
    for source, target in (
        (repo / "scripts/backup-broker.py", trusted / "broker.py"),
        (repo / "src/instantlink_bridge/manager/backup.py", trusted / "backup.py"),
    ):
        assert target.read_bytes() == source.read_bytes()
        assert target.stat().st_mode & 0o777 == 0o644
    for unit in ("instantlink-bridge-backup.socket", "instantlink-bridge-backup@.service"):
        assert (root / "etc/systemd/system" / unit).read_bytes() == (
            repo / "systemd" / unit
        ).read_bytes()
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    for call in calls:
        if call[0] == "install":
            assert call[call.index("-o") + 1] == "0"
            assert call[call.index("-g") + 1] == "0"
    assert calls[-1] == [
        "systemctl",
        f"--root={root}",
        "enable",
        "instantlink-bridge-backup.socket",
    ]
    # Reinstallation must refresh the trusted module rather than leave stale logic.
    module = repo / "src/instantlink_bridge/manager/backup.py"
    module.write_text(module.read_text(encoding="utf-8") + "\n# Updated backup boundary\n")
    assert _run_installer(repo, root, env).returncode == 0
    assert (trusted / "backup.py").read_bytes() == module.read_bytes()


@pytest.mark.parametrize("relative", ["usr/local/libexec", "etc/systemd/system"])
def test_installer_rejects_symlink_destination_before_writes(tmp_path: Path, relative: str) -> None:
    repo, root, env, log = _installer_fixture(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    symlink = root / relative
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(external, target_is_directory=True)
    result = _run_installer(repo, root, env)
    assert result.returncode != 0
    assert "destination contains a symlink" in result.stderr
    assert list(external.iterdir()) == []
    assert [json.loads(line)[0] for line in log.read_text().splitlines()] == ["id"]


def test_root_service_uses_isolated_system_python_and_manager_remains_sandboxed() -> None:
    broker_unit = (BRIDGE_ROOT / "systemd/instantlink-bridge-backup@.service").read_text()
    assert (
        "ExecStart=/usr/bin/python3 -I /usr/local/libexec/instantlink-bridge-backup/broker.py"
        in (broker_unit)
    )
    assert "StandardInput=socket" in broker_unit
    assert "/opt/InstantLinkBridge" not in broker_unit
    manager_unit = (BRIDGE_ROOT / "systemd/instantlink-bridge-manager.service").read_text()
    assert "User=ib" in manager_unit
    assert "NoNewPrivileges=yes" in manager_unit
    assert "ProtectSystem=strict" in manager_unit


def test_all_install_paths_refresh_trusted_backup_boundary() -> None:
    for name in ("deploy-to-pi.sh", "provision-sd.sh", "install-firmware-bundle.sh"):
        assert "scripts/install-backup-broker.sh" in (BRIDGE_ROOT / "scripts" / name).read_text()
    firmware_installer = (BRIDGE_ROOT / "scripts/install-firmware-bundle.sh").read_text()
    main = firmware_installer[firmware_installer.index("main() {") :]
    assert main.index('chown -R "${OWNER}:${GROUP}" "${TARGET}"') < (
        main.index("install_backup_broker")
    )


@pytest.mark.parametrize("historical", [False, True])
def test_firmware_installer_supports_bundles_before_backup_broker(
    tmp_path: Path, historical: bool
) -> None:
    target = tmp_path / "runtime"
    target.mkdir()
    marker = tmp_path / "installed"
    if not historical:
        helper = target / "scripts/install-backup-broker.sh"
        helper.parent.mkdir()
        helper.write_text('test "$1" = /\nprintf installed > "$BROKER_TEST_MARKER"\n')
    # Load the installer's real functions without running the unrelated native,
    # ownership and service operations against the host.
    installer = (BRIDGE_ROOT / "scripts/install-firmware-bundle.sh").read_text()
    functions = installer.rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["bash", "-c", functions + "\ninstall_backup_broker\n"],
        env=os.environ
        | {
            "INSTANTLINK_BRIDGE_TARGET": str(target),
            "BROKER_TEST_MARKER": str(marker),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert marker.exists() is not historical
