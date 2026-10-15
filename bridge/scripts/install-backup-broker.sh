#!/usr/bin/env bash
set -euo pipefail

# Install only the privileged backup boundary, without provisioning networking,
# changing camera credentials, or restarting the Bridge or Bluetooth.
ROOT="${1:-/}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: backup broker installation requires root" >&2
  exit 1
fi
ROOT="$(cd "${ROOT}" && pwd -P)"

require_plain_destination() {
  local relative="$1"
  local current="${ROOT%/}"
  local part
  local parts
  IFS=/ read -r -a parts <<< "${relative}"
  for part in "${parts[@]}"; do
    current="${current}/${part}"
    if [[ -L "${current}" ]]; then
      echo "ERROR: backup broker destination contains a symlink" >&2
      exit 1
    fi
  done
}

for relative in \
  usr/local/libexec/instantlink-bridge-backup/broker.py \
  usr/local/libexec/instantlink-bridge-backup/backup.py \
  etc/systemd/system/instantlink-bridge-backup.socket \
  etc/systemd/system/instantlink-bridge-backup@.service; do
  require_plain_destination "${relative}"
done

# Runtime Python and its venv are writable by ib. The root service uses a
# separate copy, system Python in isolated mode, and stdlib imports only.
install -d -m 0755 -o 0 -g 0 \
  "${ROOT%/}/usr/local/libexec" \
  "${ROOT%/}/usr/local/libexec/instantlink-bridge-backup"
install -m 0644 -o 0 -g 0 "${REPO_DIR}/scripts/backup-broker.py" \
  "${ROOT%/}/usr/local/libexec/instantlink-bridge-backup/broker.py"
install -m 0644 -o 0 -g 0 "${REPO_DIR}/src/instantlink_bridge/manager/backup.py" \
  "${ROOT%/}/usr/local/libexec/instantlink-bridge-backup/backup.py"
install -d -m 0755 -o 0 -g 0 "${ROOT%/}/etc/systemd/system"
for unit in instantlink-bridge-backup.socket instantlink-bridge-backup@.service; do
  install -m 0644 -o 0 -g 0 "${REPO_DIR}/systemd/${unit}" \
    "${ROOT%/}/etc/systemd/system/${unit}"
done

if [[ "${ROOT}" == / ]]; then
  systemctl daemon-reload
  systemctl enable --now instantlink-bridge-backup.socket
else
  systemctl --root="${ROOT}" enable instantlink-bridge-backup.socket
fi
