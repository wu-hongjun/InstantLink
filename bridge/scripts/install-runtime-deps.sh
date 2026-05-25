#!/usr/bin/env bash
set -euo pipefail

TARGET="${INSTANTLINK_BRIDGE_TARGET:-/opt/InstantLinkBridge}"
OWNER="${INSTANTLINK_BRIDGE_OWNER:-ib}"
GROUP="${INSTANTLINK_BRIDGE_GROUP:-ib}"
CONSTRAINTS_FILE="${INSTANTLINK_BRIDGE_CONSTRAINTS:-${TARGET}/requirements/constraints.txt}"
DEPLOY_METADATA_DIR="${INSTANTLINK_BRIDGE_DEPLOY_METADATA_DIR:-${TARGET}/.deployment}"
RUNTIME_PACKAGES_ARTIFACT="${INSTANTLINK_BRIDGE_RUNTIME_PACKAGES_ARTIFACT:-${DEPLOY_METADATA_DIR}/runtime-installed-packages.txt}"
RUNTIME_APT_PACKAGES_ARTIFACT="${INSTANTLINK_BRIDGE_RUNTIME_APT_PACKAGES_ARTIFACT:-${DEPLOY_METADATA_DIR}/runtime-apt-packages.txt}"
RUNTIME_DEPS_MANIFEST="${INSTANTLINK_BRIDGE_RUNTIME_DEPS_MANIFEST:-${DEPLOY_METADATA_DIR}/runtime-deps-manifest.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OFFLINE="${INSTANTLINK_BRIDGE_OFFLINE:-0}"
SEED_VENV="${INSTANTLINK_BRIDGE_SEED_VENV:-}"

APT_PACKAGES=(
  bluez
  cargo
  dnsmasq
  build-essential
  heif-thumbnailer
  iproute2
  iw
  libdbus-1-dev
  liblgpio-dev
  libheif-plugin-libde265
  network-manager
  pkg-config
  python3-venv
  rustc
  swig
  tcpdump
)

sha256_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    printf ''
    return 0
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${path}" | awk '{ print $1 }'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${path}" | awk '{ print $1 }'
    return 0
  fi

  echo "ERROR: sha256sum or shasum is required to record runtime metadata" >&2
  return 1
}

utc_now() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

ensure_constraints_file() {
  if [[ -f "${CONSTRAINTS_FILE}" ]]; then
    return 0
  fi
  echo "ERROR: missing Python constraints file at ${CONSTRAINTS_FILE}" >&2
  echo "Deploy the repository first or set INSTANTLINK_BRIDGE_CONSTRAINTS to the pinned constraints file." >&2
  exit 1
}

ensure_python_version() {
  "${PYTHON_BIN}" - <<'PY'
import sys

if not ((3, 11) <= sys.version_info[:2] < (3, 14)):
    raise SystemExit(
        "ERROR: InstantLink Bridge Pi runtime requires Python >=3.11,<3.14; "
        f"got {sys.version.split()[0]} from {sys.executable}"
    )
PY
}

is_truthy() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "${value}" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_virtualenv() {
  if [[ -x "${TARGET}/.venv/bin/python" ]]; then
    return 0
  fi

  if [[ -n "${SEED_VENV}" ]]; then
    if [[ ! -x "${SEED_VENV}/bin/python" ]]; then
      echo "ERROR: INSTANTLINK_BRIDGE_SEED_VENV lacks bin/python: ${SEED_VENV}" >&2
      exit 1
    fi
    install -d -m 0755 "${TARGET}"
    cp -a "${SEED_VENV}" "${TARGET}/.venv"
    chown -R "${OWNER}:${GROUP}" "${TARGET}/.venv"
    return 0
  fi

  sudo -u "${OWNER}" "${PYTHON_BIN}" -m venv "${TARGET}/.venv"
}

pip_install() {
  local python="$1"
  shift
  sudo -u "${OWNER}" "${python}" -m pip install -c "${CONSTRAINTS_FILE}" "$@"
}

render_runtime_deps_manifest() {
  local python="$1"
  local output_path="$2"
  local installed_packages_path="$3"
  local apt_packages_path="$4"
  local recorded_at="$5"
  local constraints_sha
  local installed_packages_sha
  local apt_packages_sha

  constraints_sha="$(sha256_file "${CONSTRAINTS_FILE}")"
  installed_packages_sha="$(sha256_file "${installed_packages_path}")"
  apt_packages_sha="$(sha256_file "${apt_packages_path}")"

  "${python}" - \
    "${output_path}" \
    "${recorded_at}" \
    "${TARGET}" \
    "${CONSTRAINTS_FILE}" \
    "${constraints_sha}" \
    "${installed_packages_path}" \
    "${installed_packages_sha}" \
    "${apt_packages_path}" \
    "${apt_packages_sha}" <<'PY'
import json
import pathlib
import platform
import subprocess
import sys

(
    output_path,
    recorded_at,
    target,
    constraints_file,
    constraints_sha,
    installed_packages_path,
    installed_packages_sha,
    apt_packages_path,
    apt_packages_sha,
) = sys.argv[1:]

pip_version = subprocess.check_output(
    [sys.executable, "-m", "pip", "--version"],
    text=True,
).strip()

manifest = {
    "schema_version": 1,
    "recorded_at_utc": recorded_at,
    "target": target,
    "python": {
        "executable": sys.executable,
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
    },
    "pip": pip_version,
    "constraints_file": constraints_file,
    "constraints_sha256": constraints_sha or None,
    "installed_packages_artifact": installed_packages_path,
    "installed_packages_sha256": installed_packages_sha or None,
    "apt_packages_artifact": apt_packages_path,
    "apt_packages_sha256": apt_packages_sha or None,
}

pathlib.Path(output_path).write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

record_apt_packages() {
  local packages_tmp
  packages_tmp="$(mktemp -t instantlink-bridge-runtime-apt-packages.XXXXXX)"

  dpkg-query -W -f='${binary:Package}=${Version}\n' "${APT_PACKAGES[@]}" 2>/dev/null |
    LC_ALL=C sort > "${packages_tmp}" || true
  sudo install -D -m 0644 -o "${OWNER}" "${packages_tmp}" "${RUNTIME_APT_PACKAGES_ARTIFACT}"
  rm -f "${packages_tmp}"
}

record_installed_packages() {
  local python="$1"
  local packages_tmp
  local manifest_tmp
  packages_tmp="$(mktemp -t instantlink-bridge-runtime-packages.XXXXXX)"
  manifest_tmp="$(mktemp -t instantlink-bridge-runtime-deps.XXXXXX.json)"

  sudo -u "${OWNER}" "${python}" -m pip list --format=freeze |
    LC_ALL=C sort > "${packages_tmp}"
  sudo install -D -m 0644 -o "${OWNER}" "${packages_tmp}" "${RUNTIME_PACKAGES_ARTIFACT}"

  render_runtime_deps_manifest \
    "${python}" \
    "${manifest_tmp}" \
    "${RUNTIME_PACKAGES_ARTIFACT}" \
    "${RUNTIME_APT_PACKAGES_ARTIFACT}" \
    "$(utc_now)"
  sudo install -D -m 0644 -o "${OWNER}" "${manifest_tmp}" "${RUNTIME_DEPS_MANIFEST}"

  rm -f "${packages_tmp}" "${manifest_tmp}"
}

build_instantlink_backend() {
  local installed_lib="${TARGET}/lib/libinstantlink_ffi.so"
  local installed_cli="${TARGET}/bin/instantlink"
  local instantlink_dir="${INSTANTLINK_BRIDGE_INSTANTLINK_SOURCE:-${TARGET}/instantlink-source}"
  local lib_source="${instantlink_dir}/target/release/libinstantlink_ffi.so"
  local cli_source="${instantlink_dir}/target/release/instantlink"

  if [[ -x "${installed_lib}" && -x "${installed_cli}" ]]; then
    echo "InstantLink backend artifacts already installed; skipping local cargo build."
    return 0
  fi

  if [[ ! -f "${instantlink_dir}/Cargo.toml" ]]; then
    echo "ERROR: missing InstantLink source at ${instantlink_dir} and no installed artifacts found." >&2
    echo "Run bridge/scripts/build-instantlink-artifacts.sh and deploy with --instantlink-artifacts," >&2
    echo "or set INSTANTLINK_BRIDGE_INSTANTLINK_SOURCE to a checked-out InstantLink source tree." >&2
    exit 1
  fi

  sudo -u "${OWNER}" env \
    CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-1}" \
    CARGO_PROFILE_RELEASE_LTO="${CARGO_PROFILE_RELEASE_LTO:-off}" \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS="${CARGO_PROFILE_RELEASE_CODEGEN_UNITS:-16}" \
    cargo build \
      --manifest-path "${instantlink_dir}/Cargo.toml" \
      --release \
      --locked \
      -p instantlink-ffi \
      -p instantlink-cli

  install -d -m 0755 "${TARGET}/lib" "${TARGET}/bin"
  install -m 0755 -o "${OWNER}" -g "${GROUP}" "${lib_source}" \
    "${TARGET}/lib/libinstantlink_ffi.so"
  install -m 0755 -o "${OWNER}" -g "${GROUP}" "${cli_source}" \
    "${TARGET}/bin/instantlink"
}

main() {
  local venv_python="${TARGET}/.venv/bin/python"

  ensure_constraints_file
  ensure_python_version

  if is_truthy "${OFFLINE}"; then
    echo "Offline dependency mode enabled; skipping apt-get update/install."
  else
    sudo apt-get update
    sudo apt-get install -y "${APT_PACKAGES[@]}"
  fi
  record_apt_packages

  ensure_virtualenv

  if is_truthy "${OFFLINE}"; then
    pip_install "${venv_python}" --no-index --no-deps --no-build-isolation -e "${TARGET}"
  else
    pip_install "${venv_python}" --upgrade pip setuptools wheel hatchling editables
    pip_install "${venv_python}" --no-build-isolation -e "${TARGET}"
  fi
  build_instantlink_backend
  record_installed_packages "${venv_python}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
