from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from instantlink_bridge.manager import installer
from instantlink_bridge.manager.installer import (
    INSTALL_LOCK_FILE_NAME,
    UPDATE_STATE_FILE_NAME,
    FirmwareBundleError,
    OperationLockError,
    install_release_slot_bundle,
    plan_release_slot_install,
)
from instantlink_bridge.manager.release_slots import (
    CURRENT_LINK_NAME,
    PREVIOUS_LINK_NAME,
    ReleaseReference,
    ReleaseSlotPathError,
    RollbackState,
    SymlinkUpdate,
    apply_symlink_updates,
    ensure_release_slot_layout,
    read_release_link,
    read_rollback_state,
    release_symlink_target,
)


def test_release_slot_install_copies_payload_switches_links_and_persists_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "InstantLinkBridge"
    bundle = write_firmware_bundle(tmp_path)
    layout = ensure_release_slot_layout(root)
    old_release = "2026-05-24T153000Z-v0.1.5"
    (layout.releases_dir / old_release).mkdir()
    layout.current_link.symlink_to(release_symlink_target(old_release))
    (layout.shared_dir / "printer-cache.json").write_text("{}", encoding="utf-8")
    writes: list[tuple[str, str | None]] = []
    original_write_update_state = installer._write_update_state

    def record_write(path: str | Path, state: RollbackState) -> None:
        current = read_release_link(root, CURRENT_LINK_NAME)
        assert current is None or isinstance(current, ReleaseReference)
        writes.append((Path(path).name, current.release_id if current is not None else None))
        original_write_update_state(path, state)

    monkeypatch.setattr(installer, "_write_update_state", record_write)

    result = install_release_slot_bundle(
        bundle,
        root=root,
        now="2026-05-26T15:30:00Z",
    )

    release_id = "2026-05-26T153000Z-v0.2.0"
    release_dir = layout.releases_dir / release_id
    assert (release_dir / "bridge" / "pyproject.toml").read_text(encoding="utf-8") == (
        "[project]\nname = \"instantlink-bridge\"\n"
    )
    assert (release_dir / "native" / "bin" / "instantlink").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\n"
    )
    assert (layout.shared_dir / "printer-cache.json").read_text(encoding="utf-8") == "{}"
    assert os.readlink(layout.current_link) == release_symlink_target(release_id)
    assert os.readlink(layout.previous_link) == release_symlink_target(old_release)
    assert result.executed_privileged_commands == ()
    assert [command.argv for command in result.plan.privileged_commands] == [
        ("systemctl", "daemon-reload"),
        ("systemctl", "restart", "instantlink-bridge.service"),
    ]

    state = read_rollback_state(root / UPDATE_STATE_FILE_NAME)
    assert state.active_release == release_id
    assert state.previous_release == old_release
    assert state.status.value == "pending_verification"
    assert writes == [
        (UPDATE_STATE_FILE_NAME, old_release),
        (UPDATE_STATE_FILE_NAME, release_id),
    ]


def test_release_slot_install_rejects_missing_manifest(tmp_path: Path) -> None:
    bundle = write_firmware_bundle(tmp_path)
    (bundle / "manifest.json").unlink()

    with pytest.raises(FirmwareBundleError, match=r"manifest\.json"):
        plan_release_slot_install(bundle, root=tmp_path / "InstantLinkBridge")


def test_release_slot_install_rejects_symlink_release_path(tmp_path: Path) -> None:
    root = tmp_path / "InstantLinkBridge"
    bundle = write_firmware_bundle(tmp_path)
    layout = ensure_release_slot_layout(root)
    release_id = "2026-05-26T153000Z-v0.2.0"
    outside = tmp_path / "outside-release"
    outside.mkdir()
    (layout.releases_dir / release_id).symlink_to(outside)

    with pytest.raises(ReleaseSlotPathError, match="release path"):
        install_release_slot_bundle(bundle, root=root)


def test_release_slot_install_rejects_lock_conflict(tmp_path: Path) -> None:
    root = tmp_path / "InstantLinkBridge"
    bundle = write_firmware_bundle(tmp_path)
    root.mkdir()
    (root / INSTALL_LOCK_FILE_NAME).write_text("pid=1\noperation=install\n", encoding="utf-8")

    with pytest.raises(OperationLockError, match="already in progress"):
        install_release_slot_bundle(bundle, root=root)


def test_release_slot_install_updates_current_and_previous(tmp_path: Path) -> None:
    root = tmp_path / "InstantLinkBridge"
    bundle = write_firmware_bundle(tmp_path)
    layout = ensure_release_slot_layout(root)
    previous_release = "2026-05-20T101500Z-v0.1.0"
    current_release = "2026-05-24T153000Z-v0.1.5"
    for release_id in (previous_release, current_release):
        (layout.releases_dir / release_id).mkdir()
    apply_symlink_updates(
        (
            SymlinkUpdate(
                PREVIOUS_LINK_NAME,
                layout.previous_link,
                release_symlink_target(previous_release),
                None,
            ),
            SymlinkUpdate(
                CURRENT_LINK_NAME,
                layout.current_link,
                release_symlink_target(current_release),
                None,
            ),
        )
    )

    install_release_slot_bundle(bundle, root=root)

    new_current = read_release_link(root, CURRENT_LINK_NAME)
    new_previous = read_release_link(root, PREVIOUS_LINK_NAME)
    assert isinstance(new_current, ReleaseReference)
    assert isinstance(new_previous, ReleaseReference)
    assert new_current.release_id == "2026-05-26T153000Z-v0.2.0"
    assert new_previous.release_id == current_release


def write_firmware_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bridge_dir = bundle / "bridge"
    native_bin = bundle / "native" / "bin"
    native_lib = bundle / "native" / "lib"
    bridge_dir.mkdir(parents=True)
    native_bin.mkdir(parents=True)
    native_lib.mkdir(parents=True)

    (bridge_dir / "pyproject.toml").write_text(
        "[project]\nname = \"instantlink-bridge\"\n",
        encoding="utf-8",
    )
    instantlink = native_bin / "instantlink"
    instantlink.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    instantlink.chmod(0o755)
    ffi = native_lib / "libinstantlink_ffi.so"
    ffi.write_bytes(b"ffi")
    artifacts_manifest = bundle / "native" / "instantlink-artifacts-manifest.json"
    artifacts_manifest.write_text('{"schema_version": 1}\n', encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "package_kind": "instantlink_bridge_firmware",
        "bridge_version": "0.2.0",
        "source_ref": "v0.2.0",
        "built_at_utc": "2026-05-26T15:30:00Z",
        "required_bridge_api_version": 1,
        "minimum_rollback_version": None,
        "migration_notes": [],
        "instantlink_workspace": {
            "commit_sha": "1" * 40,
            "branch": "main",
            "dirty": False,
        },
        "target": {
            "platform": "linux",
            "architecture": "aarch64",
            "rust_triple": "aarch64-unknown-linux-gnu",
        },
        "archive": {
            "name": "InstantLinkBridgeFirmware-v0.2.0-linux-aarch64.tar.gz",
            "compression": "gzip",
        },
        "python": {
            "package": "instantlink-bridge",
            "constraints": "bridge/requirements/constraints.txt",
        },
        "native_artifacts": {
            "instantlink": {
                "path": "native/bin/instantlink",
                "sha256": sha256_file(instantlink),
            },
            "libinstantlink_ffi.so": {
                "path": "native/lib/libinstantlink_ffi.so",
                "sha256": sha256_file(ffi),
            },
            "build_manifest": {
                "path": "native/instantlink-artifacts-manifest.json",
                "sha256": sha256_file(artifacts_manifest),
            },
        },
        "install": {
            "script": "install-firmware-bundle.sh",
            "default_target": "/opt/InstantLinkBridge",
        },
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (bundle / "SHA256SUMS").write_text("verified elsewhere\n", encoding="utf-8")
    install_script = bundle / "install-firmware-bundle.sh"
    install_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    install_script.chmod(0o755)
    return bundle


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
