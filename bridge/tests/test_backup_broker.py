"""Exercise trusted broker policy without root, Bluetooth, systemd or film."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from instantlink_bridge.manager import backup, update_flow

ADAPTER = "B8:27:EB:8E:59:C2"
PRINTER = "FA:AB:BC:C7:95:64"


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setitem(sys.modules, "backup", backup)
    path = Path(__file__).parents[1] / "scripts/backup-broker.py"
    spec = importlib.util.spec_from_file_location("tested_backup_broker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(
    tmp_path: Path, *, bond: bool = True, identity: bool = True
) -> tuple[Path, Path, backup.CreatedBackupArchive]:
    root = tmp_path / "source"
    config = root / "etc/InstantLinkBridge/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[printer]\n", encoding="utf-8")
    selected = root / "var/lib/InstantLinkBridge/printer.json"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        json.dumps({"address": PRINTER, "name": "INSTAX-52006924"}), encoding="utf-8"
    )
    if bond:
        info = root / "var/lib/bluetooth" / ADAPTER / PRINTER / "info"
        info.parent.mkdir(parents=True)
        info.write_text(
            "[General]\nName=INSTAX-52006924\n[LongTermKey]\nKey=synthetic-key\n", encoding="utf-8"
        )
        if identity:
            (info.parent.parent / "identity").write_text(
                "[General]\nIdentityResolvingKey=synthetic-identity\n", encoding="utf-8"
            )
    storage = tmp_path / "backups"
    created = backup.create_backup_archive(storage, root=root)
    destination = tmp_path / "destination"
    destination.mkdir()
    return storage, destination, created


def _restore_env(
    broker: ModuleType, monkeypatch: pytest.MonkeyPatch, storage: Path
) -> list[tuple[str, ...]]:
    monkeypatch.setattr(broker, "BACKUPS", storage)
    monkeypatch.setattr(broker, "_private", lambda path: None)
    monkeypatch.setattr(broker, "_adapter_addresses", lambda: {ADAPTER})
    monkeypatch.setattr(broker, "_active", lambda unit: True)
    monkeypatch.setattr(
        broker.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(broker, "_run", lambda *args: calls.append(args))
    return calls


def test_same_adapter_bond_restore_reloads_services_and_private_modes(
    broker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, root, created = _archive(tmp_path)
    calls = _restore_env(broker, monkeypatch, storage)
    # Ownership is a privileged hardware responsibility; descriptor and mode behavior is local.
    monkeypatch.setattr(broker.os, "fchown", lambda *args: None)
    result = broker._restore(created.manifest.backup_id, root=root)
    assert result["restore"]["restored_count"] == 4
    assert calls == [
        ("/usr/bin/systemctl", "stop", "instantlink-bridge.service"),
        ("/usr/bin/systemctl", "stop", "bluetooth.service"),
        ("/usr/bin/systemctl", "start", "bluetooth.service"),
        ("/usr/bin/systemctl", "start", "instantlink-bridge.service"),
    ]
    for entry in created.manifest.files:
        assert backup.sha256_file(root / entry.path) == entry.sha256
        if entry.path.startswith("var/lib/bluetooth/"):
            assert stat.S_IMODE((root / entry.path).stat().st_mode) == 0o600
            assert stat.S_IMODE((root / entry.path).parent.stat().st_mode) == 0o700


def test_wrong_adapter_rejects_before_any_mutation(
    broker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, root, created = _archive(tmp_path)
    calls = _restore_env(broker, monkeypatch, storage)
    monkeypatch.setattr(broker, "_adapter_addresses", lambda: {"B8:27:EB:8E:59:C3"})
    with pytest.raises(backup.BackupPathError, match="different Bluetooth adapter"):
        broker._restore(created.manifest.backup_id, root=root)
    assert calls == []
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("existing_identity", [True, False])
def test_changed_identity_rejects_unrelated_device_before_mutation(
    broker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_identity: bool
) -> None:
    storage, root, created = _archive(tmp_path)
    calls = _restore_env(broker, monkeypatch, storage)
    adapter = root / "var/lib/bluetooth" / ADAPTER
    adapter.mkdir(parents=True)
    if existing_identity:
        (adapter / "identity").write_text("different-existing-identity", encoding="utf-8")
    unrelated = adapter / "FA:AB:BC:C7:95:65" / "info"
    unrelated.parent.mkdir()
    unrelated.write_text("unrelated-existing-bond", encoding="utf-8")
    with pytest.raises(backup.BackupPathError, match="conflicts"):
        broker._restore(created.manifest.backup_id, root=root)
    assert calls == []
    assert unrelated.read_text(encoding="utf-8") == "unrelated-existing-bond"


def test_failed_bluetooth_restart_still_attempts_bridge_restart(
    broker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, root, created = _archive(tmp_path)
    calls = _restore_env(broker, monkeypatch, storage)
    monkeypatch.setattr(broker.os, "fchown", lambda *args: None)

    def run(*args: str) -> None:
        calls.append(args)
        if args[1:] == ("start", "bluetooth.service"):
            raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(broker, "_run", run)
    with pytest.raises(RuntimeError, match="synthetic"):
        broker._restore(created.manifest.backup_id, root=root)
    assert calls[-1] == ("/usr/bin/systemctl", "start", "instantlink-bridge.service")


def test_legacy_backup_without_bonds_does_not_restart_bluez(
    broker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, root, created = _archive(tmp_path, bond=False)
    calls = _restore_env(broker, monkeypatch, storage)
    monkeypatch.setattr(broker.os, "fchown", lambda *args: None)
    broker._restore(created.manifest.backup_id, root=root)
    assert not any("bluetooth.service" in call for call in calls)


@pytest.mark.parametrize(
    "message",
    [
        None,
        [],
        {"action": "shell"},
        {"action": "create", "root": "/tmp"},
        {"action": "restore", "backup_id": "../escape"},
        {"action": "restore", "backup_id": "/etc/passwd"},
    ],
)
def test_broker_rejects_other_actions_roots_and_unsafe_ids(
    broker: ModuleType, message: object
) -> None:
    with pytest.raises(backup.BackupError):
        broker.handle(message)


def test_production_management_create_restore_use_private_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def request(action: str, **kwargs: str) -> dict[str, object]:
        calls.append((action, kwargs))
        return {"backup" if action == "create" else "restore": {"backup_id": "test-safe"}}

    monkeypatch.setattr(update_flow, "request_private_backup", request)
    environment = update_flow.ManagerEnvironment.production()
    assert environment.private_backup_broker
    assert update_flow.run_backup_create(environment) == {"backup": {"backup_id": "test-safe"}}
    assert update_flow.run_backup_restore(environment, backup_id="test-safe") == {
        "restore": {"backup_id": "test-safe"}
    }
    assert calls == [("create", {}), ("restore", {"backup_id": "test-safe"})]


def test_production_restore_preserves_not_found_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from instantlink_bridge.manager.backup_client import PrivateBackupError

    def missing(*args: object, **kwargs: object) -> None:
        raise PrivateBackupError("backup_not_found")

    monkeypatch.setattr(update_flow, "request_private_backup", missing)
    with pytest.raises(update_flow.UpdateFlowError) as error:
        update_flow.run_backup_restore(
            update_flow.ManagerEnvironment.production(), backup_id="absent"
        )
    assert error.value.error_code == "backup_not_found"
    assert error.value.http_status == 404


def test_client_sends_only_fixed_operation_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from instantlink_bridge.manager import backup_client

    sent: list[bytes] = []

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, seconds: float) -> None:
            assert seconds > 600

        def connect(self, path: str) -> None:
            assert path == "/run/instantlink-bridge-backup.sock"

        def sendall(self, data: bytes) -> None:
            sent.append(data)

        def recv(self, size: int) -> bytes:
            return b'{"ok":true,"payload":{"backup":{"backup_id":"safe","verified":true}}}\n'

    monkeypatch.setattr(backup_client.socket, "socket", lambda *args: Connection())
    assert backup_client.request_private_backup("create", version="0.1.17")["backup"] == {
        "backup_id": "safe",
        "verified": True,
    }
    assert json.loads(sent[0]) == {"action": "create", "version": "0.1.17"}


def test_private_config_files_restore_runtime_owner_and_secret_modes(
    broker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, root, _first = _archive(tmp_path, bond=False)
    source = tmp_path / "source"
    presets = source / "etc/InstantLinkBridge/presets.toml"
    presets.write_text("private synthetic preset", encoding="utf-8")
    presets.chmod(0o600)
    credential = source / "etc/InstantLinkBridge/private/nested/credential.json"
    credential.parent.mkdir(parents=True)
    credential.write_text("private nested synthetic credential", encoding="utf-8")
    credential.chmod(0o600)
    created = backup.create_backup_archive(storage, root=source, backup_id="private-config")
    _restore_env(broker, monkeypatch, storage)
    monkeypatch.setattr(
        broker.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1234, pw_gid=5678)
    )
    records: list[tuple[bytes, int, int]] = []

    def record_owner(descriptor: int, uid: int, gid: int) -> None:
        value = os.fstat(descriptor)
        if stat.S_ISREG(value.st_mode):
            records.append((os.pread(descriptor, 4096, 0), uid, gid))

    monkeypatch.setattr(broker.os, "fchown", record_owner)
    broker._restore(created.manifest.backup_id, root=root)
    assert (b"private synthetic preset", 1234, 5678) in records
    assert not any(
        content == b"private synthetic preset" and uid == 0 for content, uid, _ in records
    )
    restored = root / "etc/InstantLinkBridge/presets.toml"
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600
    restored_credential = root / credential.relative_to(source)
    assert (b"private nested synthetic credential", 1234, 5678) in records
    assert stat.S_IMODE(restored_credential.stat().st_mode) == 0o600
    assert stat.S_IMODE(restored_credential.parent.stat().st_mode) == 0o2770
    assert stat.S_IMODE(restored_credential.parent.parent.stat().st_mode) == 0o2770
    assert stat.S_IMODE((root / "etc/InstantLinkBridge/config.toml").stat().st_mode) == 0o660
