"""Backup manifest helpers for Bridge management updates.

This module only plans and verifies local backup contents. It does not switch
release slots, stop services, or create exported support bundles.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tarfile
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any

BACKUP_SCHEMA_VERSION = 1
BACKUP_KIND = "instantlink_bridge_local_update_backup"
DEFAULT_RETENTION_COUNT = 3
DEFAULT_EXCLUDED_PATHS: tuple[Path, ...] = (
    Path("/var/lib/InstantLinkBridge/incoming"),
    Path("/var/lib/InstantLinkBridge/uploads"),
    Path("/var/log"),
    Path("/root/.ssh"),
    Path("/home/ib/.ssh"),
    Path("/etc/ssh"),
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_READ_CHUNK_SIZE = 1024 * 1024


class BackupError(ValueError):
    """Base error for backup manifest failures."""


class BackupPathError(BackupError):
    """Raised when a backup path is outside the configured root or unsafe."""


class BackupManifestError(BackupError):
    """Raised when a backup manifest is malformed."""


class BackupVerificationError(BackupError):
    """Raised when backup verification fails and strict mode is requested."""


@dataclass(frozen=True, slots=True)
class BackupSource:
    """One configured source path for a local update backup."""

    path: Path
    required: bool = True


DEFAULT_BACKUP_SOURCES: tuple[BackupSource, ...] = (
    BackupSource(Path("/etc/InstantLinkBridge"), required=True),
    BackupSource(Path("/opt/InstantLinkBridge/.deployment"), required=False),
    BackupSource(
        Path("/etc/NetworkManager/system-connections/InstantLink Bridge-Hotspot.nmconnection"),
        required=False,
    ),
    BackupSource(
        Path("/etc/NetworkManager/conf.d/99-instantlink-bridge-unmanaged-usb0.conf"),
        required=False,
    ),
    BackupSource(Path("/etc/systemd/network/10-usb0.network"), required=False),
    BackupSource(
        Path("/etc/systemd/journald.conf.d/99-instantlink-bridge-persistent.conf"),
        required=False,
    ),
    BackupSource(Path("/etc/systemd/system/instantlink-bridge.service"), required=False),
    BackupSource(
        Path("/etc/systemd/system/instantlink-bridge-boot-splash.service"),
        required=False,
    ),
    BackupSource(
        Path("/etc/systemd/system/instantlink-bridge-manager.service"),
        required=False,
    ),
    BackupSource(
        Path("/etc/systemd/system/instantlink-bridge-usb0-rearm.service"),
        required=False,
    ),
    BackupSource(
        Path("/etc/systemd/system/instantlink-bridge-usb0-lost.service"),
        required=False,
    ),
    BackupSource(Path("/etc/udev/rules.d/99-instantlink-bridge-usb0.rules"), required=False),
    BackupSource(Path("/var/lib/InstantLinkBridge/printer.json"), required=False),
    BackupSource(Path("/var/lib/InstantLinkBridge/management"), required=False),
)
# TODO: Add selected-printer BlueZ bond metadata when the adapter-local path is safe to discover.


@dataclass(frozen=True, slots=True)
class BackupFileEntry:
    """One hashed file recorded in a backup manifest."""

    path: str
    source_path: str
    size_bytes: int
    sha256: str
    mode: int | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "path": self.path,
            "source_path": self.source_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.mode is not None:
            value["mode"] = self.mode
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BackupFileEntry:
        path = _required_str(value, "path")
        _safe_relative_posix_path(path)
        source_path = _required_str(value, "source_path")
        size_bytes = value.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise BackupManifestError("backup file size_bytes must be a non-negative integer")
        sha256 = _required_str(value, "sha256")
        if _SHA256_RE.fullmatch(sha256) is None:
            raise BackupManifestError(f"invalid SHA-256 digest for backup file: {path}")
        mode = value.get("mode")
        if mode is not None:
            mode = _safe_file_mode_from_value(mode, path=path)
        return cls(
            path=path,
            source_path=source_path,
            size_bytes=size_bytes,
            sha256=sha256,
            mode=mode,
        )


@dataclass(frozen=True, slots=True)
class MissingBackupSource:
    """A configured backup source that was absent when the manifest was created."""

    source_path: str
    required: bool
    reason: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "required": self.required,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MissingBackupSource:
        source_path = _required_str(value, "source_path")
        required = value.get("required")
        if not isinstance(required, bool):
            raise BackupManifestError("missing backup source required must be a boolean")
        reason = _required_str(value, "reason")
        return cls(source_path=source_path, required=required, reason=reason)


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """Serializable manifest for a local update backup."""

    schema_version: int
    backup_kind: str
    backup_id: str
    created_at: str
    root: str
    version: str | None
    files: tuple[BackupFileEntry, ...]
    missing_sources: tuple[MissingBackupSource, ...] = ()
    excluded_paths: tuple[str, ...] = ()
    archive_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "backup_kind": self.backup_kind,
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "root": self.root,
            "version": self.version,
            "files": [entry.to_dict() for entry in self.files],
            "missing_sources": [entry.to_dict() for entry in self.missing_sources],
            "excluded_paths": list(self.excluded_paths),
        }
        if self.archive_sha256 is not None:
            value["archive_sha256"] = self.archive_sha256
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BackupManifest:
        if value.get("schema_version") != BACKUP_SCHEMA_VERSION:
            raise BackupManifestError("unsupported backup manifest schema version")
        if value.get("backup_kind") != BACKUP_KIND:
            raise BackupManifestError("unsupported backup manifest kind")

        files_value = value.get("files")
        if not isinstance(files_value, list):
            raise BackupManifestError("backup manifest files must be a list")
        files = tuple(_parse_file_entry(item) for item in files_value)

        missing_value = value.get("missing_sources", [])
        if not isinstance(missing_value, list):
            raise BackupManifestError("backup manifest missing_sources must be a list")
        missing_sources = tuple(_parse_missing_source(item) for item in missing_value)

        excluded_value = value.get("excluded_paths", [])
        if not isinstance(excluded_value, list) or not all(
            isinstance(item, str) for item in excluded_value
        ):
            raise BackupManifestError("backup manifest excluded_paths must be a list of strings")

        version = value.get("version")
        if version is not None and not isinstance(version, str):
            raise BackupManifestError("backup manifest version must be a string or null")

        archive_sha256 = value.get("archive_sha256")
        if archive_sha256 is not None:
            if not isinstance(archive_sha256, str) or _SHA256_RE.fullmatch(archive_sha256) is None:
                raise BackupManifestError("backup manifest archive_sha256 must be a SHA-256 digest")

        return cls(
            schema_version=BACKUP_SCHEMA_VERSION,
            backup_kind=BACKUP_KIND,
            backup_id=_required_str(value, "backup_id"),
            created_at=_required_str(value, "created_at"),
            root=_required_str(value, "root"),
            version=version,
            files=files,
            missing_sources=missing_sources,
            excluded_paths=tuple(excluded_value),
            archive_sha256=archive_sha256,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class BackupHashMismatch:
    """A file whose current hash differs from the backup manifest."""

    path: str
    expected_sha256: str
    actual_sha256: str


@dataclass(frozen=True, slots=True)
class BackupVerificationResult:
    """Result of verifying a manifest against local files."""

    ok: bool
    checked_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    mismatches: tuple[BackupHashMismatch, ...]
    invalid_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    """Manifest/archive pair used when planning backup retention."""

    name: str
    manifest_path: Path
    archive_path: Path | None
    sort_key: str

    @property
    def paths(self) -> tuple[Path, ...]:
        if self.archive_path is None:
            return (self.manifest_path,)
        return (self.manifest_path, self.archive_path)


@dataclass(frozen=True, slots=True)
class BackupRetentionPlan:
    """Which backup artifacts should be retained or pruned."""

    keep: tuple[BackupArtifact, ...]
    prune: tuple[BackupArtifact, ...]
    prune_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class CreatedBackupArchive:
    """A newly written backup archive and its manifest pair."""

    manifest: BackupManifest
    manifest_path: Path
    archive_path: Path

    @property
    def archive_sha256(self) -> str:
        if self.manifest.archive_sha256 is None:
            raise BackupManifestError("created backup manifest is missing archive_sha256")
        return self.manifest.archive_sha256


@dataclass(frozen=True, slots=True)
class BackupArchiveVerificationResult:
    """Result of verifying an archive against a backup manifest."""

    ok: bool
    archive_sha256: str
    checked_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    extra_paths: tuple[str, ...]
    mismatches: tuple[BackupHashMismatch, ...]
    invalid_paths: tuple[str, ...] = ()
    archive_digest_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class BackupRestoreEntry:
    """One file that can be safely restored from a backup archive."""

    path: str
    target_path: Path
    size_bytes: int
    sha256: str
    mode: int


@dataclass(frozen=True, slots=True)
class BackupRestorePlan:
    """A verified restore plan for a backup archive."""

    manifest: BackupManifest
    archive_path: Path
    root: Path
    entries: tuple[BackupRestoreEntry, ...]
    exclude_paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class BackupRestoreResult:
    """Result of executing a restore plan."""

    restored_paths: tuple[Path, ...]


BackupSourceLike = BackupSource | str | Path
BackupManifestLike = BackupManifest | Mapping[str, Any]
BackupArtifactLike = BackupArtifact | str | Path


def create_backup_manifest(
    sources: Iterable[BackupSourceLike],
    *,
    root: str | Path = Path("/"),
    exclude_paths: Iterable[str | Path] | None = None,
    backup_id: str | None = None,
    version: str | None = None,
    created_at: str | None = None,
) -> BackupManifest:
    """Create a backup manifest from configured local source paths."""

    root_path = _resolved_root(root)
    exclusions = _resolved_exclusions(_exclude_paths_for_root(exclude_paths, root_path), root_path)
    created_at_value = created_at or _utc_timestamp()
    backup_id_value = backup_id or default_backup_id(created_at_value, version=version)

    files: list[BackupFileEntry] = []
    missing_sources: list[MissingBackupSource] = []
    excluded_paths: set[str] = set()

    for source in sources:
        backup_source = _coerce_backup_source(source)
        source_path = _source_path_under_root(backup_source.path, root_path)
        if _is_excluded_path(source_path, exclusions):
            excluded_paths.add(_backup_relative_path(source_path, root_path))
            continue
        if not source_path.exists():
            missing = MissingBackupSource(
                source_path=str(source_path),
                required=backup_source.required,
            )
            if backup_source.required:
                raise BackupManifestError(f"required backup source is missing: {source_path}")
            missing_sources.append(missing)
            continue
        if source_path.is_dir():
            _add_directory_entries(source_path, root_path, exclusions, files, excluded_paths)
        elif source_path.is_file():
            file_path = _existing_path_under_root(source_path, root_path)
            files.append(_backup_entry_for_file(file_path, root_path))
        else:
            raise BackupManifestError(
                f"backup source is not a regular file or directory: {source_path}"
            )

    files = _dedupe_backup_entries(files)
    files.sort(key=lambda entry: entry.path)
    return BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        backup_kind=BACKUP_KIND,
        backup_id=backup_id_value,
        created_at=created_at_value,
        root=str(root_path),
        version=version,
        files=tuple(files),
        missing_sources=tuple(missing_sources),
        excluded_paths=tuple(sorted(excluded_paths)),
    )


def default_backup_sources(*, root: str | Path = Path("/")) -> tuple[BackupSource, ...]:
    """Return the canonical product backup source set for a root filesystem."""

    root_path = _resolved_root(root)
    return tuple(
        BackupSource(path=_default_path_for_root(source.path, root_path), required=source.required)
        for source in DEFAULT_BACKUP_SOURCES
    )


def default_excluded_paths(*, root: str | Path = Path("/")) -> tuple[Path, ...]:
    """Return default backup exclusions mapped into a root filesystem."""

    root_path = _resolved_root(root)
    return tuple(_default_path_for_root(path, root_path) for path in DEFAULT_EXCLUDED_PATHS)


def create_backup_archive(
    backups_dir: str | Path,
    sources: Iterable[BackupSourceLike] | None = None,
    *,
    root: str | Path = Path("/"),
    exclude_paths: Iterable[str | Path] | None = None,
    backup_id: str | None = None,
    version: str | None = None,
    created_at: str | None = None,
) -> CreatedBackupArchive:
    """Create a tar.gz archive and paired manifest JSON from allowlisted sources."""

    root_path = _resolved_root(root)
    backup_sources = (
        tuple(sources) if sources is not None else default_backup_sources(root=root_path)
    )
    manifest = create_backup_manifest(
        backup_sources,
        root=root_path,
        exclude_paths=exclude_paths,
        backup_id=backup_id,
        version=version,
        created_at=created_at,
    )

    directory = Path(backups_dir)
    directory.mkdir(parents=True, exist_ok=True)
    archive_path = directory / f"{manifest.backup_id}.tar.gz"
    manifest_path = directory / f"{manifest.backup_id}.manifest.json"
    if archive_path.exists() or manifest_path.exists():
        raise BackupError(f"backup artifact already exists: {manifest.backup_id}")

    _write_backup_tar_archive(archive_path, manifest, root_path)
    archive_sha256 = sha256_file(archive_path)
    manifest_with_digest = _manifest_with_archive_digest(manifest, archive_sha256)
    verify_backup_archive(archive_path, manifest_with_digest, raise_on_error=True)
    write_backup_manifest(manifest_path, manifest_with_digest)
    return CreatedBackupArchive(
        manifest=manifest_with_digest,
        manifest_path=manifest_path,
        archive_path=archive_path,
    )


def verify_backup_archive(
    archive_path: str | Path,
    manifest: BackupManifestLike,
    *,
    root: str | Path | None = None,
    exclude_paths: Iterable[str | Path] | None = None,
    raise_on_error: bool = False,
) -> BackupArchiveVerificationResult:
    """Verify archive contents, paths, modes, and hashes against a manifest."""

    archive = Path(archive_path)
    backup_manifest = _coerce_manifest(manifest)
    archive_sha256 = sha256_file(archive)
    archive_digest_mismatch = (
        backup_manifest.archive_sha256 is not None
        and archive_sha256 != backup_manifest.archive_sha256
    )
    root_path = _resolved_root(root) if root is not None else None
    exclusions = (
        _resolved_exclusions(_exclude_paths_for_root(exclude_paths, root_path), root_path)
        if root_path is not None
        else ()
    )
    expected_entries = {entry.path: entry for entry in backup_manifest.files}
    checked_paths: list[str] = []
    extra_paths: list[str] = []
    mismatches: list[BackupHashMismatch] = []
    invalid_paths: list[str] = []
    seen_paths: set[str] = set()

    if len(expected_entries) != len(backup_manifest.files):
        invalid_paths.extend(_duplicate_manifest_paths(backup_manifest.files))

    for entry in backup_manifest.files:
        try:
            _safe_relative_posix_path(entry.path)
        except BackupPathError:
            invalid_paths.append(entry.path)
            continue
        if root_path is not None and _is_excluded_restore_path(entry.path, root_path, exclusions):
            invalid_paths.append(entry.path)

    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar.getmembers():
                member_path = _safe_tar_member_path(member)
                if member_path is None:
                    invalid_paths.append(member.name or "<empty>")
                    continue
                if member_path in seen_paths:
                    invalid_paths.append(member_path)
                    continue
                seen_paths.add(member_path)

                if root_path is not None and _is_excluded_restore_path(
                    member_path,
                    root_path,
                    exclusions,
                ):
                    invalid_paths.append(member_path)
                    continue

                expected_entry = expected_entries.get(member_path)
                if expected_entry is None:
                    extra_paths.append(member_path)
                    continue

                mode = _safe_archive_member_mode(member)
                if mode is None or (
                    expected_entry.mode is not None and mode != expected_entry.mode
                ):
                    invalid_paths.append(member_path)
                    continue

                extracted = tar.extractfile(member)
                if extracted is None:
                    invalid_paths.append(member_path)
                    continue
                size_bytes, actual_sha256 = _hash_tar_file(extracted)
                if (
                    size_bytes != expected_entry.size_bytes
                    or actual_sha256 != expected_entry.sha256
                ):
                    mismatches.append(
                        BackupHashMismatch(
                            path=expected_entry.path,
                            expected_sha256=expected_entry.sha256,
                            actual_sha256=actual_sha256,
                        )
                    )
                    continue
                checked_paths.append(expected_entry.path)
    except (OSError, tarfile.TarError) as exc:
        if raise_on_error:
            raise BackupVerificationError(f"backup archive could not be read: {archive}") from exc
        invalid_paths.append(str(archive))

    missing_paths = tuple(
        entry.path for entry in backup_manifest.files if entry.path not in seen_paths
    )
    result = BackupArchiveVerificationResult(
        ok=not (
            archive_digest_mismatch
            or missing_paths
            or extra_paths
            or mismatches
            or invalid_paths
        ),
        archive_sha256=archive_sha256,
        checked_paths=tuple(checked_paths),
        missing_paths=missing_paths,
        extra_paths=tuple(extra_paths),
        mismatches=tuple(mismatches),
        invalid_paths=tuple(invalid_paths),
        archive_digest_mismatch=archive_digest_mismatch,
    )
    if raise_on_error and not result.ok:
        raise BackupVerificationError(_archive_verification_error_message(result))
    return result


def plan_backup_restore(
    archive_path: str | Path,
    manifest: BackupManifestLike,
    *,
    root: str | Path,
    exclude_paths: Iterable[str | Path] | None = None,
    allow_live_root: bool = False,
) -> BackupRestorePlan:
    """Verify an archive and plan a safe root-relative restore."""

    root_path = _resolved_existing_restore_root(root, allow_live_root=allow_live_root)
    exclusions = _resolved_exclusions(_exclude_paths_for_root(exclude_paths, root_path), root_path)
    backup_manifest = _coerce_manifest(manifest)
    verify_backup_archive(
        archive_path,
        backup_manifest,
        root=root_path,
        exclude_paths=exclusions,
        raise_on_error=True,
    )

    entries: list[BackupRestoreEntry] = []
    for entry in backup_manifest.files:
        relative_path = _safe_relative_posix_path(entry.path)
        target_path = _restore_target_path(root_path, relative_path)
        entries.append(
            BackupRestoreEntry(
                path=entry.path,
                target_path=target_path,
                size_bytes=entry.size_bytes,
                sha256=entry.sha256,
                mode=entry.mode if entry.mode is not None else 0o600,
            )
        )
    return BackupRestorePlan(
        manifest=backup_manifest,
        archive_path=Path(archive_path),
        root=root_path,
        entries=tuple(entries),
        exclude_paths=exclusions,
    )


def restore_backup_archive(
    archive_path: str | Path,
    manifest: BackupManifestLike,
    *,
    root: str | Path,
    exclude_paths: Iterable[str | Path] | None = None,
    allow_live_root: bool = False,
) -> BackupRestoreResult:
    """Verify and restore a backup archive into a non-live root by default."""

    plan = plan_backup_restore(
        archive_path,
        manifest,
        root=root,
        exclude_paths=exclude_paths,
        allow_live_root=allow_live_root,
    )
    return execute_backup_restore_plan(plan)


def execute_backup_restore_plan(plan: BackupRestorePlan) -> BackupRestoreResult:
    """Execute a previously verified restore plan."""

    verify_backup_archive(
        plan.archive_path,
        plan.manifest,
        root=plan.root,
        exclude_paths=plan.exclude_paths,
        raise_on_error=True,
    )
    planned_by_path = {entry.path: entry for entry in plan.entries}
    restored_paths: list[Path] = []
    with tarfile.open(plan.archive_path, mode="r:gz") as tar:
        members = {member.name: member for member in tar.getmembers()}
        for entry in plan.entries:
            member = members.get(entry.path)
            if member is None:
                raise BackupVerificationError(f"backup archive is missing: {entry.path}")
            if entry.path not in planned_by_path:
                raise BackupVerificationError(f"backup archive path was not planned: {entry.path}")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise BackupVerificationError(f"backup archive member cannot be read: {entry.path}")
            _restore_tar_file(extracted, entry, plan.root)
            restored_paths.append(entry.target_path)
    return BackupRestoreResult(restored_paths=tuple(restored_paths))


def verify_backup_manifest(
    manifest: BackupManifestLike,
    *,
    root: str | Path | None = None,
    raise_on_error: bool = False,
) -> BackupVerificationResult:
    """Verify manifest file paths and SHA-256 hashes against local files."""

    backup_manifest = _coerce_manifest(manifest)
    root_path = _resolved_root(root if root is not None else backup_manifest.root)
    checked_paths: list[str] = []
    missing_paths: list[str] = []
    mismatches: list[BackupHashMismatch] = []
    invalid_paths: list[str] = []

    for entry in backup_manifest.files:
        relative_path = _safe_relative_posix_path(entry.path)
        candidate = (root_path / Path(relative_path.as_posix())).resolve(strict=False)
        if not _is_relative_to(candidate, root_path):
            raise BackupPathError(f"backup manifest path escapes root: {entry.path}")
        if not candidate.exists():
            missing_paths.append(entry.path)
            continue
        resolved = candidate.resolve(strict=True)
        if not _is_relative_to(resolved, root_path) or not resolved.is_file():
            invalid_paths.append(entry.path)
            continue
        checked_paths.append(entry.path)
        actual_sha256 = sha256_file(resolved)
        if actual_sha256 != entry.sha256:
            mismatches.append(
                BackupHashMismatch(
                    path=entry.path,
                    expected_sha256=entry.sha256,
                    actual_sha256=actual_sha256,
                )
            )

    result = BackupVerificationResult(
        ok=not missing_paths and not mismatches and not invalid_paths,
        checked_paths=tuple(checked_paths),
        missing_paths=tuple(missing_paths),
        mismatches=tuple(mismatches),
        invalid_paths=tuple(invalid_paths),
    )
    if raise_on_error and not result.ok:
        raise BackupVerificationError(_verification_error_message(result))
    return result


def read_backup_manifest(path: str | Path) -> BackupManifest:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BackupManifestError("backup manifest file must contain a JSON object")
    return BackupManifest.from_dict(value)


def write_backup_manifest(path: str | Path, manifest: BackupManifestLike) -> None:
    backup_manifest = _coerce_manifest(manifest)
    Path(path).write_text(backup_manifest.to_json(), encoding="utf-8")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_backup_id(created_at: str | None = None, *, version: str | None = None) -> str:
    timestamp = created_at or _utc_timestamp()
    compact_timestamp = (
        timestamp.replace("-", "")
        .replace(":", "")
        .replace("T", "-")
        .replace("+0000", "Z")
        .replace("+00:00", "Z")
    )
    compact_timestamp = compact_timestamp.removesuffix("Z").split(".")[0]
    version_component = _safe_backup_id_component(version or "unknown")
    return f"update-{compact_timestamp}-{version_component}"


def is_excluded_backup_path(
    path: str | Path,
    *,
    root: str | Path = Path("/"),
    exclude_paths: Iterable[str | Path] | None = None,
) -> bool:
    root_path = _resolved_root(root)
    source_path = _source_path_under_root(path, root_path)
    exclusions = _resolved_exclusions(_exclude_paths_for_root(exclude_paths, root_path), root_path)
    return _is_excluded_path(source_path, exclusions)


def discover_backup_artifacts(
    backups_dir: str | Path,
    *,
    manifest_pattern: str = "update-*.manifest.json",
) -> tuple[BackupArtifact, ...]:
    """Return backup manifest/archive pairs found in a backups directory."""

    directory = Path(backups_dir)
    artifacts: list[BackupArtifact] = []
    for manifest_path in sorted(directory.glob(manifest_pattern)):
        if not manifest_path.is_file():
            continue
        name = manifest_path.name.removesuffix(".manifest.json")
        archive_path = directory / f"{name}.tar.gz"
        artifacts.append(
            BackupArtifact(
                name=name,
                manifest_path=manifest_path,
                archive_path=archive_path if archive_path.exists() else None,
                sort_key=_artifact_sort_key(manifest_path),
            )
        )
    return tuple(artifacts)


def plan_backup_retention(
    artifacts: Iterable[BackupArtifactLike],
    *,
    keep: int = DEFAULT_RETENTION_COUNT,
) -> BackupRetentionPlan:
    """Plan retention, keeping the newest backup artifacts by manifest metadata."""

    if keep < 1:
        raise BackupError("backup retention keep count must be at least 1")
    backup_artifacts = tuple(_coerce_backup_artifact(artifact) for artifact in artifacts)
    ordered = tuple(
        sorted(
            backup_artifacts,
            key=lambda artifact: (artifact.sort_key, artifact.manifest_path.name),
            reverse=True,
        )
    )
    kept = ordered[:keep]
    pruned = ordered[keep:]
    prune_paths = tuple(path for artifact in pruned for path in artifact.paths)
    return BackupRetentionPlan(keep=kept, prune=pruned, prune_paths=prune_paths)


def select_backups_to_prune(
    backups_dir: str | Path,
    *,
    keep: int = DEFAULT_RETENTION_COUNT,
) -> tuple[Path, ...]:
    """Return backup manifest/archive paths that should be pruned."""

    plan = plan_backup_retention(discover_backup_artifacts(backups_dir), keep=keep)
    return plan.prune_paths


def prune_backup_retention(
    backups_dir: str | Path,
    *,
    keep: int = DEFAULT_RETENTION_COUNT,
) -> BackupRetentionPlan:
    """Delete backup archive/manifest pairs beyond the retention count."""

    plan = plan_backup_retention(discover_backup_artifacts(backups_dir), keep=keep)
    for path in plan.prune_paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
    return plan


def prune_backup_artifacts(
    backups_dir: str | Path,
    *,
    keep: int = DEFAULT_RETENTION_COUNT,
) -> BackupRetentionPlan:
    """Alias for pruning old backup archive/manifest pairs."""

    return prune_backup_retention(backups_dir, keep=keep)


def _add_directory_entries(
    source_path: Path,
    root_path: Path,
    exclusions: tuple[Path, ...],
    files: list[BackupFileEntry],
    excluded_paths: set[str],
) -> None:
    for dirpath, dirnames, filenames in os.walk(source_path, followlinks=False):
        current_dir = Path(dirpath)
        kept_dirnames: list[str] = []
        for dirname in sorted(dirnames):
            directory = _existing_path_under_root(current_dir / dirname, root_path)
            if _is_excluded_path(directory, exclusions) or (current_dir / dirname).is_symlink():
                excluded_paths.add(_backup_relative_path(directory, root_path))
            else:
                kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in sorted(filenames):
            candidate = current_dir / filename
            if candidate.is_symlink():
                excluded_paths.add(_backup_relative_path(candidate, root_path))
                continue
            file_path = _existing_path_under_root(candidate, root_path)
            if _is_excluded_path(file_path, exclusions):
                excluded_paths.add(_backup_relative_path(file_path, root_path))
                continue
            if file_path.is_file():
                files.append(_backup_entry_for_file(file_path, root_path))


def _backup_entry_for_file(file_path: Path, root_path: Path) -> BackupFileEntry:
    file_stat = file_path.stat()
    return BackupFileEntry(
        path=_backup_relative_path(file_path, root_path),
        source_path=str(file_path),
        size_bytes=file_stat.st_size,
        sha256=sha256_file(file_path),
        mode=_safe_file_mode(file_stat.st_mode),
    )


def _write_backup_tar_archive(
    archive_path: Path,
    manifest: BackupManifest,
    root_path: Path,
) -> None:
    with tarfile.open(archive_path, mode="w:gz") as archive:
        for entry in manifest.files:
            relative_path = _safe_relative_posix_path(entry.path)
            file_path = _existing_path_under_root(
                root_path / Path(relative_path.as_posix()),
                root_path,
            )
            file_stat = file_path.stat(follow_symlinks=False)
            if not stat.S_ISREG(file_stat.st_mode):
                raise BackupManifestError(f"backup source is not a regular file: {file_path}")
            mode = entry.mode if entry.mode is not None else _safe_file_mode(file_stat.st_mode)
            tar_info = tarfile.TarInfo(entry.path)
            tar_info.size = file_stat.st_size
            tar_info.mode = mode
            tar_info.mtime = int(file_stat.st_mtime)
            tar_info.uid = 0
            tar_info.gid = 0
            tar_info.uname = ""
            tar_info.gname = ""
            with file_path.open("rb") as handle:
                archive.addfile(tar_info, handle)


def _manifest_with_archive_digest(manifest: BackupManifest, archive_sha256: str) -> BackupManifest:
    return BackupManifest(
        schema_version=manifest.schema_version,
        backup_kind=manifest.backup_kind,
        backup_id=manifest.backup_id,
        created_at=manifest.created_at,
        root=manifest.root,
        version=manifest.version,
        files=manifest.files,
        missing_sources=manifest.missing_sources,
        excluded_paths=manifest.excluded_paths,
        archive_sha256=archive_sha256,
    )


def _safe_tar_member_path(member: tarfile.TarInfo) -> str | None:
    try:
        member_path = _safe_relative_posix_path(member.name)
    except BackupPathError:
        return None
    if member.name != member_path.as_posix():
        return None
    if member.issym() or member.islnk() or member.isdev() or not member.isfile():
        return None
    return member_path.as_posix()


def _safe_archive_member_mode(member: tarfile.TarInfo) -> int | None:
    try:
        return _safe_file_mode_from_value(member.mode, path=member.name)
    except BackupManifestError:
        return None


def _hash_tar_file(handle: IO[bytes]) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    for chunk in iter(lambda: handle.read(_READ_CHUNK_SIZE), b""):
        size_bytes += len(chunk)
        digest.update(chunk)
    return size_bytes, digest.hexdigest()


def _duplicate_manifest_paths(entries: Iterable[BackupFileEntry]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for entry in entries:
        if entry.path in seen:
            duplicates.append(entry.path)
        else:
            seen.add(entry.path)
    return duplicates


def _dedupe_backup_entries(entries: Iterable[BackupFileEntry]) -> list[BackupFileEntry]:
    entries_by_path: dict[str, BackupFileEntry] = {}
    for entry in entries:
        entries_by_path.setdefault(entry.path, entry)
    return list(entries_by_path.values())


def _is_excluded_restore_path(path: str, root_path: Path, exclusions: tuple[Path, ...]) -> bool:
    relative_path = _safe_relative_posix_path(path)
    candidate = (root_path / Path(relative_path.as_posix())).resolve(strict=False)
    if not _is_relative_to(candidate, root_path):
        raise BackupPathError(f"backup restore path escapes root: {path}")
    return _is_excluded_path(candidate, exclusions)


def _resolved_existing_restore_root(root: str | Path, *, allow_live_root: bool) -> Path:
    root_path = _resolved_root(root)
    if root_path == Path("/") and not allow_live_root:
        raise BackupPathError("backup restore to live root is disabled by default")
    if not root_path.exists() or not root_path.is_dir():
        raise BackupPathError(f"backup restore root must be an existing directory: {root_path}")
    if root_path.is_symlink():
        raise BackupPathError(f"backup restore root must not be a symlink: {root_path}")
    return root_path


def _restore_target_path(root_path: Path, relative_path: PurePosixPath) -> Path:
    target_path = root_path / Path(relative_path.as_posix())
    resolved = target_path.resolve(strict=False)
    if not _is_relative_to(resolved, root_path):
        raise BackupPathError(f"backup restore path escapes root: {relative_path.as_posix()}")

    current = root_path
    for part in relative_path.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise BackupPathError(f"backup restore parent is a symlink: {current}")
        if current.exists() and not current.is_dir():
            raise BackupPathError(f"backup restore parent is not a directory: {current}")

    if target_path.is_symlink():
        raise BackupPathError(f"backup restore target is a symlink: {target_path}")
    if target_path.exists() and not target_path.is_file():
        raise BackupPathError(f"backup restore target is not a regular file: {target_path}")
    return target_path


def _restore_tar_file(handle: IO[bytes], entry: BackupRestoreEntry, root_path: Path) -> None:
    target_path = _restore_target_path(root_path, _safe_relative_posix_path(entry.path))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size_bytes = 0
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=target_path.parent,
            prefix=f".{target_path.name}.tmp-",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            for chunk in iter(lambda: handle.read(_READ_CHUNK_SIZE), b""):
                size_bytes += len(chunk)
                digest.update(chunk)
                tmp_file.write(chunk)
        actual_sha256 = digest.hexdigest()
        if size_bytes != entry.size_bytes or actual_sha256 != entry.sha256:
            raise BackupVerificationError(
                f"backup archive member changed during restore: {entry.path}"
            )
        tmp_path.chmod(entry.mode)
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
        raise


def _backup_relative_path(path: Path, root_path: Path) -> str:
    try:
        relative = path.relative_to(root_path)
    except ValueError as exc:
        raise BackupPathError(f"backup path escapes root: {path}") from exc
    return PurePosixPath(*relative.parts).as_posix()


def _source_path_under_root(path: str | Path, root_path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    candidate = candidate.resolve(strict=False)
    if not _is_relative_to(candidate, root_path):
        raise BackupPathError(f"backup source path escapes root: {path}")
    return candidate


def _existing_path_under_root(path: str | Path, root_path: Path) -> Path:
    candidate = Path(path).resolve(strict=True)
    if not _is_relative_to(candidate, root_path):
        raise BackupPathError(f"backup source path escapes root: {path}")
    return candidate


def _resolved_root(root: str | Path) -> Path:
    return Path(root).resolve(strict=False)


def _resolved_exclusions(exclude_paths: Iterable[str | Path], root_path: Path) -> tuple[Path, ...]:
    exclusions: list[Path] = []
    for path in exclude_paths:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root_path / candidate
        exclusions.append(candidate.resolve(strict=False))
    return tuple(exclusions)


def _exclude_paths_for_root(
    exclude_paths: Iterable[str | Path] | None,
    root_path: Path,
) -> tuple[Path, ...]:
    if exclude_paths is None:
        return default_excluded_paths(root=root_path)
    rooted_paths: list[Path] = []
    for path in exclude_paths:
        candidate = Path(path)
        if (
            root_path != Path("/")
            and candidate.is_absolute()
            and not _is_relative_to(candidate.resolve(strict=False), root_path)
        ):
            rooted_paths.append(_default_path_for_root(candidate, root_path))
        else:
            rooted_paths.append(candidate)
    return tuple(rooted_paths)


def _default_path_for_root(path: Path, root_path: Path) -> Path:
    if root_path == Path("/"):
        return path
    if path.is_absolute():
        return root_path.joinpath(*path.parts[1:])
    return root_path / path


def _is_excluded_path(path: Path, exclusions: tuple[Path, ...]) -> bool:
    return any(path == exclusion or _is_relative_to(path, exclusion) for exclusion in exclusions)


def _safe_relative_posix_path(value: str) -> PurePosixPath:
    if "\x00" in value or "\\" in value or "//" in value or value.endswith("/"):
        raise BackupPathError(f"backup manifest path is unsafe: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise BackupPathError(f"backup manifest path must be relative: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise BackupPathError(f"backup manifest path is unsafe: {value}")
    if path.as_posix() != value:
        raise BackupPathError(f"backup manifest path is unsafe: {value}")
    return path


def _safe_file_mode(mode: int) -> int:
    return stat.S_IMODE(mode) & 0o777


def _safe_file_mode_from_value(value: object, *, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 0o777:
        raise BackupManifestError(f"backup file mode must be 0..0o777: {path}")
    return value


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _coerce_backup_source(source: BackupSourceLike) -> BackupSource:
    if isinstance(source, BackupSource):
        return source
    return BackupSource(path=Path(source), required=True)


def _coerce_manifest(manifest: BackupManifestLike) -> BackupManifest:
    if isinstance(manifest, BackupManifest):
        return manifest
    return BackupManifest.from_dict(manifest)


def _coerce_backup_artifact(artifact: BackupArtifactLike) -> BackupArtifact:
    if isinstance(artifact, BackupArtifact):
        return artifact
    manifest_path = Path(artifact)
    name = manifest_path.name.removesuffix(".manifest.json")
    archive_path = manifest_path.with_name(f"{name}.tar.gz")
    return BackupArtifact(
        name=name,
        manifest_path=manifest_path,
        archive_path=archive_path if archive_path.exists() else None,
        sort_key=_artifact_sort_key(manifest_path),
    )


def _artifact_sort_key(manifest_path: Path) -> str:
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return manifest_path.name
    if not isinstance(value, dict):
        return manifest_path.name
    created_at = value.get("created_at")
    if isinstance(created_at, str):
        return created_at
    backup_id = value.get("backup_id")
    if isinstance(backup_id, str):
        return backup_id
    return manifest_path.name


def _parse_file_entry(value: object) -> BackupFileEntry:
    if not isinstance(value, Mapping):
        raise BackupManifestError("backup manifest file entries must be JSON objects")
    return BackupFileEntry.from_dict(value)


def _parse_missing_source(value: object) -> MissingBackupSource:
    if not isinstance(value, Mapping):
        raise BackupManifestError("backup manifest missing source entries must be JSON objects")
    return MissingBackupSource.from_dict(value)


def _required_str(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise BackupManifestError(f"backup manifest {key} must be a non-empty string")
    return item


def _verification_error_message(result: BackupVerificationResult) -> str:
    parts: list[str] = []
    if result.missing_paths:
        parts.append(f"missing={','.join(result.missing_paths)}")
    if result.mismatches:
        parts.append(f"mismatched={','.join(item.path for item in result.mismatches)}")
    if result.invalid_paths:
        parts.append(f"invalid={','.join(result.invalid_paths)}")
    return f"backup verification failed ({'; '.join(parts)})"


def _archive_verification_error_message(result: BackupArchiveVerificationResult) -> str:
    parts: list[str] = []
    if result.archive_digest_mismatch:
        parts.append("archive_sha256=mismatch")
    if result.missing_paths:
        parts.append(f"missing={','.join(result.missing_paths)}")
    if result.extra_paths:
        parts.append(f"extra={','.join(result.extra_paths)}")
    if result.mismatches:
        parts.append(f"mismatched={','.join(item.path for item in result.mismatches)}")
    if result.invalid_paths:
        parts.append(f"invalid={','.join(result.invalid_paths)}")
    return f"backup archive verification failed ({'; '.join(parts)})"


def _safe_backup_id_component(value: str) -> str:
    component = _BACKUP_ID_UNSAFE_RE.sub("_", value.strip()).strip("._-")
    return component or "unknown"


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
