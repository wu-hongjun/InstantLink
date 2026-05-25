#!/usr/bin/env bash
set -euo pipefail

BRIDGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "${BRIDGE_ROOT}/.." && pwd)"
CARGO_BIN="${CARGO_BIN:-cargo}"
TARGET_TRIPLE="${INSTANTLINK_BRIDGE_RUST_TARGET:-aarch64-unknown-linux-gnu}"
MANIFEST="${ROOT}/Cargo.toml"

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
printf 'InstantLink artifacts ready in %s\n' "${artifact_dir}"
