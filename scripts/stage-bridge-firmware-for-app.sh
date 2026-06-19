#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="${INSTANTLINK_BRIDGE_FIRMWARE_SOURCE_DIR:-${ROOT}/target/bridge-firmware/dist}"
DEST_DIR="${INSTANTLINK_BRIDGE_FIRMWARE_APP_BUNDLE_DIR:-${ROOT}/target/bridge-firmware/app-bundle/BridgeFirmware}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VERSION=""

usage() {
  cat <<'USAGE'
Usage: scripts/stage-bridge-firmware-for-app.sh [--version <version-or-tag>] [--from-dir <dir>]

Stages an already-built InstantLink Bridge firmware bundle so scripts/build-app.sh can copy it into
InstantLink.app/Contents/Resources/BridgeFirmware.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:?--version requires a value}"
      shift 2
      ;;
    --from-dir)
      SOURCE_DIR="${2:?--from-dir requires a value}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "ERROR: firmware source directory does not exist: ${SOURCE_DIR}" >&2
  exit 1
fi

normalized="${VERSION#refs/tags/}"
normalized="${normalized#bridge-v}"
normalized="${normalized#v}"

if [[ -n "${VERSION}" ]]; then
  if [[ ! "${normalized}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.-]+)?$ ]]; then
    echo "ERROR: invalid firmware version '${VERSION}'. Expected MAJOR.MINOR.PATCH." >&2
    exit 2
  fi
  archive="${SOURCE_DIR}/InstantLinkBridgeFirmware-v${normalized}-linux-aarch64.tar.gz"
else
  latest="${SOURCE_DIR}/latest.json"
  if [[ ! -f "${latest}" ]]; then
    echo "ERROR: missing firmware release index: ${latest}" >&2
    exit 1
  fi
  archive_name="$("${PYTHON_BIN}" - "${latest}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"ERROR: invalid firmware release index {path}: {exc}")

archive_name = payload.get("archive_name")
if not isinstance(archive_name, str) or "/" in archive_name or archive_name in {"", ".", ".."}:
    raise SystemExit(f"ERROR: firmware release index {path} has invalid archive_name")
print(archive_name)
PY
)"
  archive="${SOURCE_DIR}/${archive_name}"
fi

if [[ -z "${archive}" || ! -f "${archive}" ]]; then
  echo "ERROR: no matching firmware archive found in ${SOURCE_DIR}" >&2
  exit 1
fi

basename="$(basename "${archive}")"
manifest="${SOURCE_DIR}/${basename%.tar.gz}.manifest.json"
manifest_sig="${SOURCE_DIR}/${basename%.tar.gz}.manifest.sig"
checksum="${archive}.sha256"
latest="${SOURCE_DIR}/latest.json"
latest_sig="${SOURCE_DIR}/latest.json.sig"

for required in "${manifest}" "${manifest_sig}" "${checksum}" "${latest}" "${latest_sig}"; do
  if [[ ! -f "${required}" ]]; then
    echo "ERROR: missing firmware sidecar: ${required}" >&2
    exit 1
  fi
done

rm -rf "${DEST_DIR}"
mkdir -p "${DEST_DIR}"
cp "${archive}" "${checksum}" "${manifest}" "${manifest_sig}" "${latest}" "${latest_sig}" "${DEST_DIR}/"

printf 'Staged Bridge firmware for app resources at %s\n' "${DEST_DIR}"
