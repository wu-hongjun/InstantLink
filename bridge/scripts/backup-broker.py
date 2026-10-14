#!/usr/bin/python3
"""Root-only, socket-activated local backup boundary. Uses only trusted stdlib code."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import pwd
import re
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import time
from pathlib import Path

# Provisioning copies backup.py alongside this script into a root-owned directory.
# Isolated Python ignores runtime code, environment paths and user site packages.
sys.path.insert(0, str(Path(__file__).parent))
from backup import (
    DEFAULT_BACKUP_SOURCES,
    BackupError,
    BackupPathError,
    _open_backup_file,
    _restore_parent_descriptor,
    create_backup_archive,
    execute_backup_restore_plan,
    is_bluez_pairing_path,
    plan_backup_restore,
    prune_backup_retention,
    read_backup_manifest,
)

BACKUPS = Path("/var/lib/InstantLinkBridgeBackups")
LOGGER = logging.getLogger("instantlink.backup")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")


def _run(*args: str) -> None:
    subprocess.run(
        args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90
    )


def _active(unit: str) -> bool:
    return (
        subprocess.run(
            ("/usr/bin/systemctl", "is-active", "--quiet", unit),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode
        == 0
    )


def _private(path: Path) -> None:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_uid != 0 or stat.S_IMODE(value.st_mode) != 0o600:
        raise BackupPathError("backup artifact is not root-private")


def _allowed(path: str) -> bool:
    if is_bluez_pairing_path(path):
        return True
    return any(
        path == source.path.as_posix().lstrip("/")
        or (
            source.path.as_posix()
            in (
                "/etc/InstantLinkBridge",
                "/opt/InstantLinkBridge/.deployment",
                "/var/lib/InstantLinkBridge/management",
            )
            and path.startswith(source.path.as_posix().lstrip("/") + "/")
        )
        for source in DEFAULT_BACKUP_SOURCES
    )


def _adapter_addresses() -> set[str]:
    # Address comes from BlueZ's live adapter object, never a guessed stored directory.
    result = subprocess.run(
        ("/usr/bin/bluetoothctl", "list"),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return set(re.findall(r"^Controller ([0-9A-F:]{17}) ", result.stdout, re.MULTILINE))


def _restore(backup_id: str, *, root: Path = Path("/")) -> dict[str, object]:
    archive = BACKUPS / (backup_id + ".tar.gz")
    manifest_path = BACKUPS / (backup_id + ".manifest.json")
    _private(archive)
    _private(manifest_path)
    manifest = read_backup_manifest(manifest_path)
    if manifest.backup_id != backup_id or any(not _allowed(entry.path) for entry in manifest.files):
        raise BackupPathError("backup contains a path outside the product restore policy")
    bonds = [entry for entry in manifest.files if is_bluez_pairing_path(entry.path)]
    if any(entry.mode != 0o600 for entry in bonds):
        raise BackupPathError("pairing info is not private")
    if bonds and "var/lib/InstantLinkBridge/printer.json" not in {
        entry.path for entry in manifest.files
    }:
        raise BackupPathError("pairing backup is missing the selected Printer identity")
    adapters = _adapter_addresses() if bonds else set()
    if any(entry.path.split("/")[3] not in adapters for entry in bonds):
        raise BackupPathError("pairing backup belongs to a different Bluetooth adapter")
    plan = plan_backup_restore(archive, manifest, root=root, allow_live_root=True)
    identities = [entry for entry in bonds if entry.path.endswith("/identity")]
    for identity in identities:
        target = root / identity.path
        changed = True
        if target.exists():
            with tarfile.open(archive, "r:gz") as container:
                archived = container.extractfile(identity.path)
                if archived is None:
                    raise BackupPathError("adapter identity is missing")
                replacement = archived.read(65537)
                if len(replacement) > 65536:
                    raise BackupPathError("adapter identity metadata is too large")
            with _open_backup_file(target, root) as current:
                changed = current.read(65537) != replacement
        selected = {entry.path.split("/")[4] for entry in bonds if entry.path.endswith("/info")}
        if (
            changed
            and target.parent.exists()
            and any(
                device.is_dir() and device.name not in selected and (device / "info").exists()
                for device in target.parent.iterdir()
            )
        ):
            raise BackupPathError("adapter identity conflicts with another saved Bluetooth device")
    bridge_active = _active("instantlink-bridge.service")
    bluetooth_active = bool(bonds) and _active("bluetooth.service")
    try:
        if bridge_active:
            _run("/usr/bin/systemctl", "stop", "instantlink-bridge.service")
        if bluetooth_active:
            _run("/usr/bin/systemctl", "stop", "bluetooth.service")
        result = execute_backup_restore_plan(plan)
        if any(entry.path.startswith("etc/systemd/system/") for entry in manifest.files):
            _run("/usr/bin/systemctl", "daemon-reload")
        runtime = pwd.getpwnam("ib")
        for path in result.restored_paths:
            relative = path.relative_to(root).as_posix()
            if is_bluez_pairing_path(relative):
                directory = path.parent
                while directory != root / "var/lib":
                    descriptor = _restore_parent_descriptor(directory, root, create=False)
                    try:
                        os.fchown(descriptor, 0, 0)
                        os.fchmod(descriptor, 0o700)
                    finally:
                        os.close(descriptor)
                    directory = directory.parent
            elif relative.startswith("var/lib/InstantLinkBridge/"):
                with _open_backup_file(path, root) as handle:
                    os.fchown(handle.fileno(), runtime.pw_uid, runtime.pw_gid)
                directory = path.parent
                while directory != root / "var/lib":
                    descriptor = _restore_parent_descriptor(directory, root, create=False)
                    try:
                        os.fchown(descriptor, runtime.pw_uid, runtime.pw_gid)
                        os.fchmod(descriptor, 0o700 if "management" in directory.parts else 0o2770)
                    finally:
                        os.close(descriptor)
                    directory = directory.parent
            elif relative.startswith("etc/InstantLinkBridge/"):
                with _open_backup_file(path, root) as handle:
                    os.fchown(handle.fileno(), 0, runtime.pw_gid)
                    if relative == "etc/InstantLinkBridge/config.toml":
                        os.fchmod(handle.fileno(), 0o660)
                descriptor = _restore_parent_descriptor(path.parent, root, create=False)
                try:
                    os.fchown(descriptor, 0, runtime.pw_gid)
                    os.fchmod(descriptor, 0o2770)
                finally:
                    os.close(descriptor)
        return {
            "restore": {
                "backup_id": backup_id,
                "restored_paths": [str(path) for path in result.restored_paths],
                "restored_count": len(result.restored_paths),
            }
        }
    finally:
        try:
            if bluetooth_active:
                _run("/usr/bin/systemctl", "start", "bluetooth.service")
        finally:
            if bridge_active:
                _run("/usr/bin/systemctl", "start", "instantlink-bridge.service")


def handle(request: object) -> dict[str, object]:
    if not isinstance(request, dict):
        raise BackupError("invalid backup request")
    action = request.get("action")
    if action == "create" and set(request) <= {"action", "version"}:
        version = request.get("version")
        if version is not None and (not isinstance(version, str) or len(version) > 80):
            raise BackupError("invalid backup version")
        created = create_backup_archive(BACKUPS, root=Path("/"), version=version)
        if any(not _allowed(entry.path) for entry in created.manifest.files):
            created.archive_path.unlink()
            created.manifest_path.unlink()
            raise BackupPathError("backup source outside product policy")
        prune_backup_retention(BACKUPS)
        return {
            "backup": {
                "verified": True,
                "backup_id": created.manifest.backup_id,
                "manifest_path": str(created.manifest_path),
                "archive_path": str(created.archive_path),
                "archive_sha256": created.archive_sha256,
                "file_count": len(created.manifest.files),
            }
        }
    if action == "restore" and set(request) == {"action", "backup_id"}:
        backup_id = request.get("backup_id")
        if isinstance(backup_id, str) and ID_RE.fullmatch(backup_id):
            return _restore(backup_id)
    raise BackupError("invalid backup action")


def main() -> None:
    if os.geteuid() != 0:
        raise BackupError("backup broker must run as root")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    started = time.monotonic()
    action = "invalid"
    connection = socket.socket(fileno=0)
    _, peer_uid, _ = struct.unpack(
        "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    )
    if peer_uid not in (0, pwd.getpwnam("ib").pw_uid):
        return
    connection.settimeout(5)
    data = bytearray()
    try:
        while b"\n" not in data and len(data) <= 2048:
            packet = connection.recv(2049 - len(data))
            if not packet:
                break
            data.extend(packet)
        if len(data) > 2048 or not data.endswith(b"\n"):
            raise BackupError("invalid backup request")
        BACKUPS.mkdir(mode=0o700, exist_ok=True)
        directory = BACKUPS.lstat()
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0:
            raise BackupPathError("backup storage must be root-owned")
        BACKUPS.chmod(0o700)
        with (BACKUPS / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = json.loads(data)
            if isinstance(request, dict) and request.get("action") in ("create", "restore"):
                action = request["action"]
            response = {"ok": True, "payload": handle(request)}
        LOGGER.info(
            "backup.operation_complete action=%s duration_ms=%d",
            action,
            (time.monotonic() - started) * 1000,
        )
    except FileNotFoundError:
        LOGGER.info(
            "backup.operation_failed action=%s error_type=NotFound duration_ms=%d",
            action,
            (time.monotonic() - started) * 1000,
        )
        response = {"ok": False, "error_code": "backup_not_found"}
    except Exception as error:
        LOGGER.warning(
            "backup.operation_failed action=%s error_type=%s duration_ms=%d",
            action,
            type(error).__name__,
            (time.monotonic() - started) * 1000,
        )
        # Do not send exception text, paths, config, keys or contents over this boundary.
        response = {
            "ok": False,
            "error": "Backup operation failed. Inspect local storage and adapter availability.",
        }
    connection.sendall(json.dumps(response).encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
