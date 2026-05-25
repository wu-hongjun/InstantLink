#!/usr/bin/env bash
set -euo pipefail

BRIDGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "${BRIDGE_ROOT}/.." && pwd)"
CARGO_BIN="${CARGO_BIN:-cargo}"
TARGET_TRIPLE="${INSTANTLINK_BRIDGE_RUST_TARGET:-aarch64-unknown-linux-gnu}"
MANIFEST="${ROOT}/Cargo.toml"
ARTIFACT_MANIFEST_NAME="${INSTANTLINK_BRIDGE_ARTIFACTS_MANIFEST_NAME:-instantlink-artifacts-manifest.json}"

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${path}" | awk '{ print $1 }'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${path}" | awk '{ print $1 }'
    return 0
  fi

  echo "ERROR: sha256sum or shasum is required to render artifact metadata" >&2
  return 1
}

utc_now() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

git_branch_name() {
  local repo="$1"
  local branch
  if branch="$(git -C "${repo}" symbolic-ref --quiet --short HEAD 2>/dev/null)"; then
    printf '%s' "${branch}"
    return 0
  fi
  printf 'DETACHED:%s' "$(git -C "${repo}" rev-parse --short HEAD)"
}

git_worktree_dirty() {
  local repo="$1"
  [[ -n "$(git -C "${repo}" status --porcelain --untracked-files=all)" ]]
}

render_artifacts_manifest() {
  local output_path="$1"
  local artifacts_dir="$2"
  local lib_source="$3"
  local cli_source="$4"
  local target_triple="$5"
  local lib_sha
  local cli_sha
  local commit_sha
  local branch
  local dirty

  lib_sha="$(sha256_file "${lib_source}")"
  cli_sha="$(sha256_file "${cli_source}")"
  commit_sha="$(git -C "${ROOT}" rev-parse --verify HEAD)"
  branch="$(git_branch_name "${ROOT}")"
  if git_worktree_dirty "${ROOT}"; then
    dirty=true
  else
    dirty=false
  fi

  "${PYTHON_BIN:-python3}" - \
    "${output_path}" \
    "$(utc_now)" \
    "${artifacts_dir}" \
    "${target_triple}" \
    "${lib_source}" \
    "${lib_sha}" \
    "${cli_source}" \
    "${cli_sha}" \
    "${commit_sha}" \
    "${branch}" \
    "${dirty}" <<'PY'
import json
import pathlib
import sys

(
    output_path,
    built_at,
    artifacts_dir,
    target_triple,
    lib_source,
    lib_sha,
    cli_source,
    cli_sha,
    commit_sha,
    branch,
    dirty,
) = sys.argv[1:]

manifest = {
    "schema_version": 1,
    "built_at_utc": built_at,
    "target_triple": target_triple,
    "cargo": {
        "command": "cargo zigbuild",
        "locked": True,
        "profile": "release",
        "packages": ["instantlink-ffi", "instantlink-cli"],
    },
    "instantlink_workspace": {
        "commit_sha": commit_sha,
        "branch": branch,
        "dirty": dirty == "true",
    },
    "artifacts_dir": artifacts_dir,
    "artifacts": {
        "libinstantlink_ffi.so": {
            "source_path": lib_source,
            "sha256": lib_sha,
        },
        "instantlink": {
            "source_path": cli_source,
            "sha256": cli_sha,
        },
    },
}

pathlib.Path(output_path).write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

if [[ ! -f "${MANIFEST}" ]]; then
  echo "ERROR: missing InstantLink submodule at ${MANIFEST}" >&2
  exit 1
fi

if ! "${CARGO_BIN}" zigbuild --help >/dev/null 2>&1; then
  echo "ERROR: cargo-zigbuild is required for cross-building InstantLink artifacts" >&2
  echo "Install it with: cargo install cargo-zigbuild" >&2
  exit 1
fi

env \
  CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-1}" \
  CARGO_PROFILE_RELEASE_LTO="${CARGO_PROFILE_RELEASE_LTO:-off}" \
  CARGO_PROFILE_RELEASE_CODEGEN_UNITS="${CARGO_PROFILE_RELEASE_CODEGEN_UNITS:-16}" \
  "${CARGO_BIN}" zigbuild \
    --manifest-path "${MANIFEST}" \
    --release \
    --locked \
    --target "${TARGET_TRIPLE}" \
    -p instantlink-ffi \
    -p instantlink-cli

artifact_dir="${ROOT}/target/${TARGET_TRIPLE}/release"
lib_source="${artifact_dir}/libinstantlink_ffi.so"
cli_source="${artifact_dir}/instantlink"
artifact_manifest="${artifact_dir}/${ARTIFACT_MANIFEST_NAME}"

if [[ ! -f "${lib_source}" ]]; then
  echo "ERROR: missing InstantLink FFI artifact after build: ${lib_source}" >&2
  exit 1
fi
if [[ ! -f "${cli_source}" ]]; then
  echo "ERROR: missing InstantLink CLI artifact after build: ${cli_source}" >&2
  exit 1
fi

render_artifacts_manifest \
  "${artifact_manifest}" \
  "${artifact_dir}" \
  "${lib_source}" \
  "${cli_source}" \
  "${TARGET_TRIPLE}"

printf 'InstantLink artifacts ready in %s\n' "${artifact_dir}"
printf 'Artifact manifest written to %s\n' "${artifact_manifest}"
