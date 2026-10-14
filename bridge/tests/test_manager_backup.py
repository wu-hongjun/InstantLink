from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
from pathlib import Path

import pytest

from instantlink_bridge.manager.backup import (
    BACKUP_KIND,
    BACKUP_SCHEMA_VERSION,
    BackupFileEntry,
    BackupManifest,
    BackupManifestError,
    BackupPathError,
    BackupSource,
    BackupVerificationError,
    create_backup_archive,
    create_backup_manifest,
    default_backup_sources,
    default_excluded_paths,
    discover_backup_artifacts,
    execute_backup_restore_plan,
    plan_backup_restore,
    plan_backup_retention,
    prune_backup_retention,
    read_backup_manifest,
    sha256_file,
    verify_backup_archive,
    verify_backup_manifest,
)


def _manifest_for_archive(tmp_path: Path, archive_path: Path) -> BackupManifest:
    return BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        backup_kind=BACKUP_KIND,
        backup_id="update-malicious",
        created_at="2026-05-26T15:30:00Z",
        root=str(tmp_path),
        version=None,
        files=(),
        missing_sources=(),
        excluded_paths=(),
        archive_sha256=sha256_file(archive_path),
    )


def test_backup_manifest_hash_verification_detects_tampering(tmp_path: Path) -> None:
    config_path = tmp_path / "etc" / "InstantLinkBridge" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("quality = 100\n", encoding="utf-8")

    manifest = create_backup_manifest(
        [config_path],
        root=tmp_path,
        version="v0.2.0",
        created_at="2026-05-26T15:30:00Z",
    )

    assert manifest.backup_id == "update-20260526-153000-v0.2.0"
    assert [entry.path for entry in manifest.files] == ["etc/InstantLinkBridge/config.toml"]
    assert manifest.files[0].sha256 == hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert sha256_file(config_path) == manifest.files[0].sha256

    valid_result = verify_backup_manifest(manifest, root=tmp_path)

    assert valid_result.ok
    assert valid_result.checked_paths == ("etc/InstantLinkBridge/config.toml",)

    config_path.write_text("quality = 95\n", encoding="utf-8")

    tampered_result = verify_backup_manifest(manifest, root=tmp_path)

    assert not tampered_result.ok
    assert tampered_result.mismatches[0].path == "etc/InstantLinkBridge/config.toml"
    with pytest.raises(BackupVerificationError):
        verify_backup_manifest(manifest, root=tmp_path, raise_on_error=True)


def test_backup_manifest_records_optional_missing_and_refuses_required_missing(
    tmp_path: Path,
) -> None:
    optional_manifest = create_backup_manifest(
        [BackupSource(tmp_path / "missing-optional.toml", required=False)],
        root=tmp_path,
        created_at="2026-05-26T15:30:00Z",
    )

    assert optional_manifest.files == ()
    assert optional_manifest.missing_sources[0].source_path.endswith("missing-optional.toml")
    assert not optional_manifest.missing_sources[0].required
    assert verify_backup_manifest(optional_manifest, root=tmp_path).ok

    with pytest.raises(BackupManifestError, match="required backup source is missing"):
        create_backup_manifest([tmp_path / "missing-required.toml"], root=tmp_path)


def test_backup_manifest_verification_reports_missing_files(tmp_path: Path) -> None:
    config_path = tmp_path / "etc" / "InstantLinkBridge" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("quality = 100\n", encoding="utf-8")
    manifest = create_backup_manifest([config_path], root=tmp_path)

    config_path.unlink()

    result = verify_backup_manifest(manifest, root=tmp_path)

    assert not result.ok
    assert result.missing_paths == ("etc/InstantLinkBridge/config.toml",)


def test_backup_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-config.toml"
    outside.write_text("secret = true\n", encoding="utf-8")
    try:
        with pytest.raises(BackupPathError):
            create_backup_manifest([outside], root=tmp_path)
    finally:
        outside.unlink()

    unsafe_manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "backup_kind": BACKUP_KIND,
        "backup_id": "update-test",
        "created_at": "2026-05-26T15:30:00Z",
        "root": str(tmp_path),
        "version": None,
        "files": [
            {
                "path": "../etc/shadow",
                "source_path": str(tmp_path / "etc" / "shadow"),
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ],
        "missing_sources": [],
        "excluded_paths": [],
    }

    with pytest.raises(BackupPathError):
        BackupManifest.from_dict(unsafe_manifest)


def test_backup_manifest_enforces_exclusions(tmp_path: Path) -> None:
    config_path = tmp_path / "etc" / "InstantLinkBridge" / "config.toml"
    upload_path = tmp_path / "var" / "lib" / "InstantLinkBridge" / "incoming" / "photo.jpg"
    config_path.parent.mkdir(parents=True)
    upload_path.parent.mkdir(parents=True)
    config_path.write_text("quality = 100\n", encoding="utf-8")
    upload_path.write_bytes(b"uploaded image")

    manifest = create_backup_manifest(
        [tmp_path / "etc", tmp_path / "var"],
        root=tmp_path,
        exclude_paths=[Path("var/lib/InstantLinkBridge/incoming")],
    )

    assert [entry.path for entry in manifest.files] == ["etc/InstantLinkBridge/config.toml"]
    assert manifest.excluded_paths == ("var/lib/InstantLinkBridge/incoming",)


def test_default_backup_sources_map_into_temp_root(tmp_path: Path) -> None:
    source_paths = {source.path for source in default_backup_sources(root=tmp_path)}

    assert tmp_path / "etc" / "InstantLinkBridge" in source_paths
    assert tmp_path / "opt" / "InstantLinkBridge" / ".deployment" in source_paths
    assert (
        tmp_path
        / "etc"
        / "NetworkManager"
        / "system-connections"
        / "InstantLink Bridge-Hotspot.nmconnection"
    ) in source_paths
    assert tmp_path / "etc" / "systemd" / "system" / "instantlink-bridge.service" in source_paths
    assert (
        tmp_path / "etc" / "udev" / "rules.d" / "99-instantlink-bridge-usb0.rules"
    ) in source_paths
    assert tmp_path / "var" / "lib" / "InstantLinkBridge" / "management" in source_paths
    assert all(path.is_relative_to(tmp_path) for path in source_paths)

    assert tmp_path / "var" / "log" in default_excluded_paths(root=tmp_path)
    assert tmp_path / "home" / "ib" / ".ssh" in default_excluded_paths(root=tmp_path)


def test_backup_archive_creation_verify_and_restore_to_temp_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source-root"
    backups_dir = tmp_path / "backups"
    restore_root = tmp_path / "restore-root"
    source_root.mkdir()
    restore_root.mkdir()

    config_path = source_root / "etc" / "InstantLinkBridge" / "config.toml"
    management_client_path = (
        source_root / "var" / "lib" / "InstantLinkBridge" / "management" / "mac.json"
    )
    upload_path = source_root / "var" / "lib" / "InstantLinkBridge" / "incoming" / "photo.jpg"
    log_path = source_root / "var" / "log" / "instantlink.log"
    ssh_key_path = source_root / "home" / "ib" / ".ssh" / "id_ed25519"
    for path in (config_path, management_client_path, upload_path, log_path, ssh_key_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("quality = 100\n", encoding="utf-8")
    management_client_path.write_text('{"client_id": "mac"}\n', encoding="utf-8")
    upload_path.write_bytes(b"uploaded image")
    log_path.write_text("journal\n", encoding="utf-8")
    ssh_key_path.write_text("ssh-secret\n", encoding="utf-8")
    os.chmod(config_path, 0o660)
    os.chmod(management_client_path, 0o600)

    symlink_path = config_path.with_name("config.link")
    symlink_path.symlink_to(config_path)

    created = create_backup_archive(
        backups_dir,
        [source_root / "etc", source_root / "var", source_root / "home"],
        root=source_root,
        backup_id="update-test",
        created_at="2026-05-26T15:30:00Z",
    )

    manifest = read_backup_manifest(created.manifest_path)
    assert manifest.archive_sha256 == sha256_file(created.archive_path)
    assert [entry.path for entry in manifest.files] == [
        "etc/InstantLinkBridge/config.toml",
        "var/lib/InstantLinkBridge/management/mac.json",
    ]
    assert "etc/InstantLinkBridge/config.link" in manifest.excluded_paths
    assert "var/lib/InstantLinkBridge/incoming" in manifest.excluded_paths
    assert "var/log" in manifest.excluded_paths
    assert "home/ib/.ssh" in manifest.excluded_paths

    archive_result = verify_backup_archive(created.archive_path, manifest, raise_on_error=True)

    assert archive_result.ok
    assert archive_result.checked_paths == (
        "etc/InstantLinkBridge/config.toml",
        "var/lib/InstantLinkBridge/management/mac.json",
    )

    plan = plan_backup_restore(created.archive_path, manifest, root=restore_root)
    restore_result = execute_backup_restore_plan(plan)

    restored_config_path = restore_root / "etc" / "InstantLinkBridge" / "config.toml"
    restored_client_path = (
        restore_root / "var" / "lib" / "InstantLinkBridge" / "management" / "mac.json"
    )
    assert restore_result.restored_paths == (restored_config_path, restored_client_path)
    assert restored_config_path.read_text(encoding="utf-8") == "quality = 100\n"
    assert restored_client_path.read_text(encoding="utf-8") == '{"client_id": "mac"}\n'
    assert stat.S_IMODE(restored_config_path.stat().st_mode) == 0o660
    assert stat.S_IMODE(restored_client_path.stat().st_mode) == 0o600
    assert not (restore_root / "var" / "lib" / "InstantLinkBridge" / "incoming").exists()
    assert not (restore_root / "var" / "log").exists()
    assert not (restore_root / "home" / "ib" / ".ssh").exists()


def test_backup_archive_rejects_digest_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    config_path = root / "etc" / "InstantLinkBridge" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("quality = 100\n", encoding="utf-8")
    created = create_backup_archive(
        tmp_path / "backups",
        [config_path],
        root=root,
        backup_id="update-test",
    )

    created.archive_path.write_bytes(created.archive_path.read_bytes() + b"tamper")
    result = verify_backup_archive(created.archive_path, created.manifest)

    assert not result.ok
    assert result.archive_digest_mismatch
    with pytest.raises(BackupVerificationError, match="archive_sha256=mismatch"):
        verify_backup_archive(created.archive_path, created.manifest, raise_on_error=True)


def test_backup_archive_restore_rejects_excluded_paths_by_default(tmp_path: Path) -> None:
    root = tmp_path / "root"
    upload_path = root / "var" / "lib" / "InstantLinkBridge" / "incoming" / "photo.jpg"
    upload_path.parent.mkdir(parents=True)
    upload_path.write_bytes(b"uploaded image")
    created = create_backup_archive(
        tmp_path / "backups",
        [upload_path],
        root=root,
        exclude_paths=(),
        backup_id="update-test",
    )
    restore_root = tmp_path / "restore"
    restore_root.mkdir()

    with pytest.raises(BackupVerificationError, match="invalid="):
        plan_backup_restore(created.archive_path, created.manifest, root=restore_root)


def test_backup_archive_rejects_path_traversal_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "malicious.tar.gz"
    payload = b"shadow"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        info = tarfile.TarInfo("../etc/shadow")
        info.size = len(payload)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(payload))

    manifest = _manifest_for_archive(tmp_path, archive_path)

    with pytest.raises(BackupVerificationError, match="invalid="):
        verify_backup_archive(archive_path, manifest, raise_on_error=True)


def test_backup_archive_rejects_symlink_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        info = tarfile.TarInfo("etc/InstantLinkBridge/config.toml")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/shadow"
        info.mode = 0o644
        archive.addfile(info)

    entry = BackupFileEntry(
        path="etc/InstantLinkBridge/config.toml",
        source_path=str(tmp_path / "etc" / "InstantLinkBridge" / "config.toml"),
        size_bytes=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        mode=0o644,
    )
    manifest = BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        backup_kind=BACKUP_KIND,
        backup_id="update-symlink",
        created_at="2026-05-26T15:30:00Z",
        root=str(tmp_path),
        version=None,
        files=(entry,),
        archive_sha256=sha256_file(archive_path),
    )

    with pytest.raises(BackupVerificationError, match="invalid="):
        verify_backup_archive(archive_path, manifest, raise_on_error=True)


def test_backup_archive_refuses_required_missing_source(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(BackupManifestError, match="required backup source is missing"):
        create_backup_archive(
            tmp_path / "backups",
            [BackupSource(root / "missing-required.toml", required=True)],
            root=root,
        )


def test_backup_retention_selects_oldest_artifacts(tmp_path: Path) -> None:
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    created_at_values = [
        "2026-05-20T10:15:00Z",
        "2026-05-21T10:15:00Z",
        "2026-05-22T10:15:00Z",
        "2026-05-23T10:15:00Z",
    ]
    for created_at in created_at_values:
        backup_id = f"update-{created_at[:10].replace('-', '')}"
        manifest_path = backups_dir / f"{backup_id}.manifest.json"
        archive_path = backups_dir / f"{backup_id}.tar.gz"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": BACKUP_SCHEMA_VERSION,
                    "backup_kind": BACKUP_KIND,
                    "backup_id": backup_id,
                    "created_at": created_at,
                    "root": str(tmp_path),
                    "version": None,
                    "files": [],
                    "missing_sources": [],
                    "excluded_paths": [],
                }
            ),
            encoding="utf-8",
        )
        archive_path.write_bytes(b"backup")

    artifacts = discover_backup_artifacts(backups_dir)
    plan = plan_backup_retention(artifacts, keep=3)

    assert [artifact.sort_key for artifact in plan.keep] == [
        "2026-05-23T10:15:00Z",
        "2026-05-22T10:15:00Z",
        "2026-05-21T10:15:00Z",
    ]
    assert [artifact.sort_key for artifact in plan.prune] == ["2026-05-20T10:15:00Z"]
    assert {path.name for path in plan.prune_paths} == {
        "update-20260520.manifest.json",
        "update-20260520.tar.gz",
    }

    pruned_plan = prune_backup_retention(backups_dir, keep=3)

    assert [artifact.sort_key for artifact in pruned_plan.prune] == ["2026-05-20T10:15:00Z"]
    assert not (backups_dir / "update-20260520.manifest.json").exists()
    assert not (backups_dir / "update-20260520.tar.gz").exists()
    assert (backups_dir / "update-20260523.manifest.json").exists()
    assert (backups_dir / "update-20260523.tar.gz").exists()


ADAPTER = "B8:27:EB:8E:59:C2"
PRINTER = "FA:AB:BC:C7:95:64"
OTHER = "FA:AB:BC:C7:95:65"


def _pairing_root(tmp_path: Path, *, address: str = PRINTER, configured: str = "") -> Path:
    root = tmp_path / "source"
    config = root / "etc/InstantLinkBridge/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'[printer]\ndevice_name = "{configured}"\n', encoding="utf-8")
    selected = root / "var/lib/InstantLinkBridge/printer.json"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        json.dumps({"address": address, "name": "INSTAX-52006924"}), encoding="utf-8"
    )
    return root


def _bond(
    root: Path, address: str = PRINTER, adapter: str = ADAPTER, name: str = "INSTAX-52006924"
) -> Path:
    path = root / "var/lib/bluetooth" / adapter / address / "info"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"[General]\nName={name}\n[LongTermKey]\nKey=synthetic-test-key\n", encoding="utf-8"
    )
    path.chmod(0o644)
    return path


def test_default_backup_includes_only_selected_bond_and_adapter_identity(tmp_path: Path) -> None:
    root = _pairing_root(tmp_path)
    selected = _bond(root)
    unrelated = _bond(root, OTHER, name="Other device")
    identity = selected.parent.parent / "identity"
    identity.write_text(
        "[General]\nIdentityResolvingKey=synthetic-test-identity\n", encoding="utf-8"
    )
    cache = selected.parent.parent / "cache" / OTHER
    cache.parent.mkdir()
    cache.write_text("never include scan cache", encoding="utf-8")
    created = create_backup_archive(tmp_path / "backups", root=root)
    paths = {entry.path for entry in created.manifest.files}
    assert selected.relative_to(root).as_posix() in paths
    assert identity.relative_to(root).as_posix() in paths
    assert unrelated.relative_to(root).as_posix() not in paths
    assert cache.relative_to(root).as_posix() not in paths
    assert all(
        entry.mode == 0o600
        for entry in created.manifest.files
        if entry.path.startswith("var/lib/bluetooth/")
    )
    assert stat.S_IMODE(created.archive_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(created.manifest_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(created.archive_path.parent.stat().st_mode) == 0o700
    destination = tmp_path / "restored"
    destination.mkdir()
    execute_backup_restore_plan(
        plan_backup_restore(created.archive_path, created.manifest, root=destination)
    )
    restored = destination / selected.relative_to(root)
    assert restored.read_bytes() == selected.read_bytes()
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600
    assert stat.S_IMODE(restored.parent.stat().st_mode) == 0o700


def test_unpaired_selection_is_a_normal_backup(tmp_path: Path) -> None:
    root = _pairing_root(tmp_path)
    created = create_backup_archive(tmp_path / "backups", root=root)
    assert not any(entry.path.startswith("var/lib/bluetooth/") for entry in created.manifest.files)


def test_selected_mac_is_authoritative_when_other_alias_matches(tmp_path: Path) -> None:
    root = _pairing_root(tmp_path)
    _bond(root, OTHER)
    assert not any("bluetooth" in str(source.path) for source in default_backup_sources(root=root))


def test_configured_selection_overrides_saved_identity_and_normalizes_suffix(
    tmp_path: Path,
) -> None:
    root = _pairing_root(tmp_path, configured="INSTAX-00009999")
    _bond(root)
    selected = _bond(root, OTHER, name="INSTAX-00009999 (ANDROID)")
    assert selected in {source.path for source in default_backup_sources(root=root)}
    assert root / "var/lib/bluetooth" / ADAPTER / PRINTER / "info" not in {
        source.path for source in default_backup_sources(root=root)
    }


@pytest.mark.parametrize("kind", ["adapter", "device", "info", "identity", "selection"])
def test_pairing_discovery_rejects_symlink_components(tmp_path: Path, kind: str) -> None:
    root = _pairing_root(tmp_path)
    info = _bond(root)
    identity = info.parent.parent / "identity"
    identity.write_text("synthetic identity", encoding="utf-8")
    target = {
        "adapter": info.parent.parent,
        "device": info.parent,
        "info": info,
        "identity": identity,
        "selection": root / "var/lib/InstantLinkBridge/printer.json",
    }[kind]
    moved = tmp_path / "moved"
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(BackupPathError, match="symlink"):
        default_backup_sources(root=root)


def test_pairing_discovery_rejects_multiple_adapters(tmp_path: Path) -> None:
    root = _pairing_root(tmp_path)
    _bond(root)
    _bond(root, adapter="B8:27:EB:8E:59:C3")
    with pytest.raises(BackupPathError, match="ambiguous Bluetooth adapters"):
        default_backup_sources(root=root)


def test_backup_failure_removes_partial_private_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from instantlink_bridge.manager import backup

    root = _pairing_root(tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise BackupVerificationError("synthetic verification failure")

    monkeypatch.setattr(backup, "verify_backup_archive", fail)
    with pytest.raises(BackupVerificationError):
        create_backup_archive(tmp_path / "backups", root=root)
    assert list((tmp_path / "backups").iterdir()) == []


def test_restore_uses_directory_descriptor_when_parent_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    original = source / "etc/InstantLinkBridge/config.toml"
    original.parent.mkdir(parents=True)
    original.write_text("private synthetic config", encoding="utf-8")
    created = create_backup_archive(tmp_path / "backups", [original], root=source)
    destination = tmp_path / "destination"
    parent = destination / "etc/InstantLinkBridge"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = destination / "etc/old-safe-directory"
    real_replace = os.replace

    def raced_replace(src: str, dst: str, *, src_dir_fd: int, dst_dir_fd: int) -> None:
        parent.rename(moved)
        parent.symlink_to(outside, target_is_directory=True)
        real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", raced_replace)
    execute_backup_restore_plan(
        plan_backup_restore(created.archive_path, created.manifest, root=destination)
    )
    assert list(outside.iterdir()) == []
    assert (moved / "config.toml").read_text(encoding="utf-8") == "private synthetic config"


def test_archive_collision_during_exclusive_write_preserves_other_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from instantlink_bridge.manager import backup

    root = _pairing_root(tmp_path)
    writer = backup._write_backup_tar_archive
    competing = b"successful competing archive"

    def collide(path: Path, manifest: BackupManifest, filesystem_root: Path) -> tuple[int, int]:
        path.write_bytes(competing)
        return writer(path, manifest, filesystem_root)

    monkeypatch.setattr(backup, "_write_backup_tar_archive", collide)
    with pytest.raises(FileExistsError):
        create_backup_archive(tmp_path / "backups", root=root, backup_id="collision")
    assert (tmp_path / "backups/collision.tar.gz").read_bytes() == competing


def test_manifest_collision_preserves_other_creator_and_removes_own_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from instantlink_bridge.manager import backup

    root = _pairing_root(tmp_path)
    writer = backup.write_backup_manifest
    competing = b"successful competing manifest"

    def collide(path: Path, manifest: BackupManifest) -> None:
        path.write_bytes(competing)
        writer(path, manifest)

    monkeypatch.setattr(backup, "write_backup_manifest", collide)
    with pytest.raises(FileExistsError):
        create_backup_archive(tmp_path / "backups", root=root, backup_id="collision")
    assert (tmp_path / "backups/collision.manifest.json").read_bytes() == competing
    assert not (tmp_path / "backups/collision.tar.gz").exists()
