"""Privileged release-slot installation helpers for verified firmware bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

from instantlink_bridge.manager.release_slots import (
    ReleaseSlotLayout,
    ReleaseSlotPathError,
    ReleaseSwitchPlan,
    RollbackPlan,
    RollbackState,
    apply_symlink_updates,
    ensure_release_slot_layout,
    plan_current_previous_switch,
    plan_rollback,
    read_rollback_state,
    release_path,
    validate_release_id,
    write_rollback_state,
)
from instantlink_bridge.manager.signing import FirmwareManifestError, validate_firmware_manifest

DEFAULT_INSTALL_ROOT = Path("/opt/InstantLinkBridge")
DEFAULT_SERVICE_NAME = "instantlink-bridge.service"
INSTALL_LOCK_FILE_NAME = ".install.lock"
UPDATE_STATE_FILE_NAME = "update-state.json"

_REQUIRED_NATIVE_ARTIFACTS = (
    PurePosixPath("native/bin/instantlink"),
    PurePosixPath("native/lib/libinstantlink_ffi.so"),
    PurePosixPath("native/instantlink-artifacts-manifest.json"),
)


class FirmwareInstallError(RuntimeError):
    """Base error for firmware release-slot installation failures."""


class FirmwareBundleError(FirmwareInstallError):
    """Raised when an extracted firmware bundle is malformed or unsafe."""


class OperationLockError(FirmwareInstallError):
    """Raised when another install or rollback operation holds the lock file."""


class PrivilegedCommandError(FirmwareInstallError):
    """Raised when a planned privileged command fails."""


@dataclass(frozen=True, slots=True)
class PrivilegedCommand:
    """A narrow privileged command plan for the caller to execute or review."""

    argv: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"argv": list(self.argv)}


class PrivilegedCommandRunner(Protocol):
    """Executes one planned privileged command."""

    def run(self, command: PrivilegedCommand) -> None:
        """Run a privileged command or raise on failure."""


class SubprocessPrivilegedCommandRunner:
    """Run planned privileged commands with subprocess.check semantics."""

    def run(self, command: PrivilegedCommand) -> None:
        try:
            subprocess.run(command.argv, check=True)
        except subprocess.CalledProcessError as exc:
            raise PrivilegedCommandError(
                f"privileged command failed with exit status {exc.returncode}: {command.argv}"
            ) from exc


@dataclass(frozen=True, slots=True)
class FirmwareBundle:
    """Validated shape metadata for an extracted firmware bundle."""

    bundle_dir: Path
    manifest_path: Path
    manifest: Mapping[str, object]
    release_id: str
    bridge_dir: Path
    native_dir: Path
    checksum_path: Path


@dataclass(frozen=True, slots=True)
class ReleaseSlotInstallPlan:
    """Dry-run plan for installing one firmware bundle into release slots."""

    root: Path
    bundle_dir: Path
    release_id: str
    release_path: Path
    state_path: Path
    lock_path: Path
    switch_plan: ReleaseSwitchPlan
    privileged_commands: tuple[PrivilegedCommand, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "bundle_dir": str(self.bundle_dir),
            "release_id": self.release_id,
            "release_path": str(self.release_path),
            "state_path": str(self.state_path),
            "lock_path": str(self.lock_path),
            "switch_plan": self.switch_plan.to_dict(),
            "privileged_commands": [command.to_dict() for command in self.privileged_commands],
        }


@dataclass(frozen=True, slots=True)
class ReleaseSlotInstallResult:
    """Result of applying a release-slot installation plan."""

    plan: ReleaseSlotInstallPlan
    executed_privileged_commands: tuple[PrivilegedCommand, ...]


@dataclass(frozen=True, slots=True)
class ReleaseSlotRollbackResult:
    """Result of applying a locked rollback switch."""

    root: Path
    state_path: Path
    lock_path: Path
    rollback_plan: RollbackPlan
    privileged_commands: tuple[PrivilegedCommand, ...]
    executed_privileged_commands: tuple[PrivilegedCommand, ...]


class OperationLock:
    """Exclusive lock file used to serialize install and rollback operations."""

    def __init__(self, root: str | Path, *, operation: str) -> None:
        layout = ReleaseSlotLayout.from_root(root)
        self.path = layout.root / INSTALL_LOCK_FILE_NAME
        self.operation = operation
        self._fd: int | None = None

    def __enter__(self) -> OperationLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self._fd = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise OperationLockError(f"install operation already in progress: {self.path}") from exc

        payload = f"pid={os.getpid()}\noperation={self.operation}\n"
        os.write(self._fd, payload.encode("utf-8"))
        os.fsync(self._fd)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def operation_lock(root: str | Path, *, operation: str) -> OperationLock:
    """Return a lock context for install/rollback operations."""

    return OperationLock(root, operation=operation)


def plan_privileged_commands(
    *,
    restart_service: bool = True,
    service_name: str = DEFAULT_SERVICE_NAME,
) -> tuple[PrivilegedCommand, ...]:
    """Return the systemd commands needed after switching a release slot."""

    commands = [PrivilegedCommand(("systemctl", "daemon-reload"))]
    if restart_service:
        commands.append(PrivilegedCommand(("systemctl", "restart", service_name)))
    return tuple(commands)


def inspect_firmware_bundle(
    bundle_dir: str | Path,
    *,
    release_id: str | None = None,
) -> FirmwareBundle:
    """Validate an extracted firmware bundle's manifest and filesystem shape."""

    raw_bundle_path = Path(bundle_dir)
    if raw_bundle_path.is_symlink():
        raise FirmwareBundleError(f"firmware bundle is not a plain directory: {bundle_dir}")
    bundle_path = raw_bundle_path.resolve(strict=True)
    if not bundle_path.is_dir():
        raise FirmwareBundleError(f"firmware bundle is not a plain directory: {bundle_dir}")

    manifest_path = bundle_path / "manifest.json"
    checksum_path = bundle_path / "SHA256SUMS"
    bridge_dir = bundle_path / "bridge"
    native_dir = bundle_path / "native"

    _require_plain_file(manifest_path, root=bundle_path, label="manifest.json")
    _require_plain_file(checksum_path, root=bundle_path, label="SHA256SUMS")
    _require_plain_directory(bridge_dir, root=bundle_path, label="bridge")
    _require_plain_directory(native_dir, root=bundle_path, label="native")

    manifest = _load_manifest(manifest_path)
    selected_release_id = validate_release_id(release_id or _release_id_from_manifest(manifest))

    for relative_path in _REQUIRED_NATIVE_ARTIFACTS:
        _require_plain_file(
            _bundle_child(bundle_path, relative_path),
            root=bundle_path,
            label=relative_path.as_posix(),
        )
    _verify_manifest_native_artifacts(bundle_path, manifest)
    _reject_symlinks_or_escapes(bridge_dir, root=bundle_path)
    _reject_symlinks_or_escapes(native_dir, root=bundle_path)

    install_script = bundle_path / "install-firmware-bundle.sh"
    if install_script.exists() or install_script.is_symlink():
        _require_plain_file(install_script, root=bundle_path, label="install-firmware-bundle.sh")

    return FirmwareBundle(
        bundle_dir=bundle_path,
        manifest_path=manifest_path,
        manifest=manifest,
        release_id=selected_release_id,
        bridge_dir=bridge_dir,
        native_dir=native_dir,
        checksum_path=checksum_path,
    )


def plan_release_slot_install(
    bundle_dir: str | Path,
    *,
    root: str | Path = DEFAULT_INSTALL_ROOT,
    release_id: str | None = None,
    restart_service: bool = True,
    service_name: str = DEFAULT_SERVICE_NAME,
    now: str | None = None,
) -> ReleaseSlotInstallPlan:
    """Validate a bundle and plan the release copy, slot switch, and commands."""

    bundle = inspect_firmware_bundle(bundle_dir, release_id=release_id)
    layout = ReleaseSlotLayout.from_root(root)
    _reject_existing_release_path(layout, bundle.release_id)
    return _build_install_plan(
        bundle,
        layout=layout,
        restart_service=restart_service,
        service_name=service_name,
        now=now,
        require_release=False,
    )


def install_release_slot_bundle(
    bundle_dir: str | Path,
    *,
    root: str | Path = DEFAULT_INSTALL_ROOT,
    release_id: str | None = None,
    privileged_runner: PrivilegedCommandRunner | None = None,
    restart_service: bool = True,
    service_name: str = DEFAULT_SERVICE_NAME,
    now: str | None = None,
) -> ReleaseSlotInstallResult:
    """Install an extracted verified firmware bundle into release slots."""

    layout = ensure_release_slot_layout(root)
    with operation_lock(layout.root, operation="install"):
        bundle = inspect_firmware_bundle(bundle_dir, release_id=release_id)
        _reject_existing_release_path(layout, bundle.release_id)
        _copy_bundle_to_release(bundle, layout)
        plan = _build_install_plan(
            bundle,
            layout=layout,
            restart_service=restart_service,
            service_name=service_name,
            now=now,
            require_release=True,
        )
        _write_update_state(plan.state_path, plan.switch_plan.state)
        apply_symlink_updates(plan.switch_plan.actions)
        _write_update_state(plan.state_path, plan.switch_plan.state)
        executed = _run_privileged_commands(plan.privileged_commands, privileged_runner)
        return ReleaseSlotInstallResult(plan=plan, executed_privileged_commands=executed)


def rollback_release_slot(
    *,
    root: str | Path = DEFAULT_INSTALL_ROOT,
    reason: str,
    privileged_runner: PrivilegedCommandRunner | None = None,
    restart_service: bool = True,
    service_name: str = DEFAULT_SERVICE_NAME,
    now: str | None = None,
) -> ReleaseSlotRollbackResult:
    """Apply a rollback under the same operation lock used by installs."""

    layout = ensure_release_slot_layout(root)
    state_path = layout.root / UPDATE_STATE_FILE_NAME
    lock_path = layout.root / INSTALL_LOCK_FILE_NAME
    with operation_lock(layout.root, operation="rollback"):
        state = read_rollback_state(state_path)
        rollback_plan = plan_rollback(layout.root, state=state, reason=reason, now=now)
        commands = plan_privileged_commands(
            restart_service=restart_service,
            service_name=service_name,
        )
        _write_update_state(state_path, rollback_plan.state)
        apply_symlink_updates(rollback_plan.actions)
        _write_update_state(state_path, rollback_plan.state)
        executed = _run_privileged_commands(commands, privileged_runner)
        return ReleaseSlotRollbackResult(
            root=layout.root,
            state_path=state_path,
            lock_path=lock_path,
            rollback_plan=rollback_plan,
            privileged_commands=commands,
            executed_privileged_commands=executed,
        )


def _build_install_plan(
    bundle: FirmwareBundle,
    *,
    layout: ReleaseSlotLayout,
    restart_service: bool,
    service_name: str,
    now: str | None,
    require_release: bool,
) -> ReleaseSlotInstallPlan:
    switch_plan = plan_current_previous_switch(
        layout.root,
        bundle.release_id,
        now=now,
        require_release=require_release,
    )
    return ReleaseSlotInstallPlan(
        root=layout.root,
        bundle_dir=bundle.bundle_dir,
        release_id=bundle.release_id,
        release_path=release_path(layout.root, bundle.release_id),
        state_path=layout.root / UPDATE_STATE_FILE_NAME,
        lock_path=layout.root / INSTALL_LOCK_FILE_NAME,
        switch_plan=switch_plan,
        privileged_commands=plan_privileged_commands(
            restart_service=restart_service,
            service_name=service_name,
        ),
    )


def _copy_bundle_to_release(bundle: FirmwareBundle, layout: ReleaseSlotLayout) -> None:
    target = release_path(layout.root, bundle.release_id)
    _reject_existing_release_path(layout, bundle.release_id)
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{bundle.release_id}.",
            suffix=".tmp",
            dir=layout.releases_dir,
        )
    )
    try:
        _copy_tree_without_symlinks(bundle.bridge_dir, temp_dir / "bridge")
        _copy_tree_without_symlinks(bundle.native_dir, temp_dir / "native")
        _copy_file_without_symlink(bundle.manifest_path, temp_dir / "manifest.json")
        _copy_file_without_symlink(bundle.checksum_path, temp_dir / "SHA256SUMS")

        install_script = bundle.bundle_dir / "install-firmware-bundle.sh"
        if install_script.exists():
            _copy_file_without_symlink(install_script, temp_dir / "install-firmware-bundle.sh")

        if target.exists() or target.is_symlink():
            raise ReleaseSlotPathError(f"release path already exists: {target}")
        os.replace(temp_dir, target)
        _fsync_directory(layout.releases_dir)
    except Exception:
        if temp_dir.exists() and not temp_dir.is_symlink():
            shutil.rmtree(temp_dir)
        raise


def _reject_existing_release_path(layout: ReleaseSlotLayout, release_id: str) -> None:
    target = release_path(layout.root, release_id)
    if target.exists() or target.is_symlink():
        raise ReleaseSlotPathError(f"release path already exists or is unsafe: {target}")


def _run_privileged_commands(
    commands: tuple[PrivilegedCommand, ...],
    runner: PrivilegedCommandRunner | None,
) -> tuple[PrivilegedCommand, ...]:
    if runner is None:
        return ()
    for command in commands:
        runner.run(command)
    return commands


def _write_update_state(path: str | Path, state: RollbackState) -> None:
    write_rollback_state(path, state)


def _load_manifest(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FirmwareBundleError(f"firmware manifest is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FirmwareBundleError("firmware manifest must be a JSON object")
    manifest = cast("dict[str, object]", value)
    try:
        validate_firmware_manifest(manifest)
    except FirmwareManifestError as exc:
        raise FirmwareBundleError(str(exc)) from exc
    return manifest


def _release_id_from_manifest(manifest: Mapping[str, object]) -> str:
    explicit_release_id = manifest.get("release_id")
    if isinstance(explicit_release_id, str):
        return explicit_release_id

    bridge_version = manifest.get("bridge_version")
    if not isinstance(bridge_version, str):
        raise FirmwareBundleError("firmware manifest bridge_version is required")
    release_version = bridge_version.replace("+", "_")

    built_at = manifest.get("built_at_utc")
    if isinstance(built_at, str) and len(built_at) == len("2026-05-26T15:30:00Z"):
        compact_time = built_at.replace(":", "")
        if compact_time.endswith("Z") and "T" in compact_time:
            return f"{compact_time}-v{release_version}"
    return f"v{release_version}"


def _verify_manifest_native_artifacts(
    bundle_dir: Path,
    manifest: Mapping[str, object],
) -> None:
    native_artifacts = manifest.get("native_artifacts")
    if not isinstance(native_artifacts, Mapping):
        raise FirmwareBundleError("firmware manifest native_artifacts are required")

    checked_paths: set[PurePosixPath] = set()
    for artifact_name, artifact in native_artifacts.items():
        if not isinstance(artifact_name, str) or not isinstance(artifact, Mapping):
            raise FirmwareBundleError("firmware manifest native artifact entries must be objects")
        path_value = artifact.get("path")
        digest_value = artifact.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest_value, str):
            raise FirmwareBundleError(
                f"firmware manifest native artifact is missing path or sha256: {artifact_name}"
            )
        relative_path = _safe_relative_path(path_value)
        if relative_path.parts[0] != "native":
            raise FirmwareBundleError(f"native artifact path must stay under native/: {path_value}")
        artifact_path = _bundle_child(bundle_dir, relative_path)
        _require_plain_file(artifact_path, root=bundle_dir, label=path_value)
        if _sha256_file(artifact_path) != digest_value:
            raise FirmwareBundleError(f"native artifact digest mismatch: {path_value}")
        checked_paths.add(relative_path)

    missing = set(_REQUIRED_NATIVE_ARTIFACTS) - checked_paths
    if missing:
        names = ", ".join(sorted(path.as_posix() for path in missing))
        raise FirmwareBundleError(f"firmware manifest is missing native artifacts: {names}")


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\x00" in value or "\\" in value:
        raise FirmwareBundleError(f"bundle path is unsafe: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise FirmwareBundleError(f"bundle path must be relative: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise FirmwareBundleError(f"bundle path must not traverse directories: {value}")
    return path


def _bundle_child(bundle_dir: Path, relative_path: PurePosixPath) -> Path:
    return bundle_dir.joinpath(*relative_path.parts)


def _require_plain_file(path: Path, *, root: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FirmwareBundleError(f"firmware bundle is missing plain file: {label}")
    _require_resolved_under_root(path, root=root, label=label)


def _require_plain_directory(path: Path, *, root: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise FirmwareBundleError(f"firmware bundle is missing plain directory: {label}")
    _require_resolved_under_root(path, root=root, label=label)


def _require_resolved_under_root(path: Path, *, root: Path, label: str) -> None:
    resolved = path.resolve(strict=True)
    if not _is_relative_to(resolved, root):
        raise FirmwareBundleError(f"firmware bundle path escapes bundle root: {label}")


def _reject_symlinks_or_escapes(path: Path, *, root: Path) -> None:
    root_resolved = root.resolve(strict=True)
    source_resolved = path.resolve(strict=True)
    if not _is_relative_to(source_resolved, root_resolved):
        raise FirmwareBundleError(f"firmware bundle path escapes bundle root: {path}")

    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        current_dir = Path(dirpath)
        if current_dir.is_symlink():
            raise FirmwareBundleError(f"firmware bundle contains symlink directory: {current_dir}")
        _require_resolved_under_root(current_dir, root=root_resolved, label=str(current_dir))

        for dirname in dirnames:
            child_dir = current_dir / dirname
            if child_dir.is_symlink():
                raise FirmwareBundleError(
                    f"firmware bundle contains symlink directory: {child_dir}"
                )
            _require_resolved_under_root(child_dir, root=root_resolved, label=str(child_dir))

        for filename in filenames:
            child_file = current_dir / filename
            if child_file.is_symlink():
                raise FirmwareBundleError(f"firmware bundle contains symlink file: {child_file}")
            if not child_file.is_file():
                raise FirmwareBundleError(f"firmware bundle contains non-file entry: {child_file}")
            _require_resolved_under_root(child_file, root=root_resolved, label=str(child_file))


def _copy_tree_without_symlinks(source: Path, destination: Path) -> None:
    _reject_symlinks_or_escapes(source, root=source)
    destination.mkdir(parents=True)
    source_resolved = source.resolve(strict=True)
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        current_dir = Path(dirpath)
        relative_dir = current_dir.resolve(strict=True).relative_to(source_resolved)
        target_dir = destination / relative_dir
        target_dir.mkdir(exist_ok=True)
        for dirname in dirnames:
            child_dir = current_dir / dirname
            if child_dir.is_symlink():
                raise FirmwareBundleError(
                    f"firmware bundle contains symlink directory: {child_dir}"
                )
        for filename in filenames:
            child_file = current_dir / filename
            if child_file.is_symlink() or not child_file.is_file():
                raise FirmwareBundleError(f"firmware bundle contains unsafe file: {child_file}")
            shutil.copy2(child_file, target_dir / filename)


def _copy_file_without_symlink(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise FirmwareBundleError(f"firmware bundle contains unsafe file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
