#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-status}"
HOTSPOT_CONNECTION="${INSTANTLINK_BRIDGE_HOTSPOT_CONNECTION:-InstantLink Bridge-Hotspot}"
HOME_CONNECTION="${INSTANTLINK_BRIDGE_HOME_CONNECTION:-InstantLink Bridge-Home}"
CONFIG_FILE="${INSTANTLINK_BRIDGE_CONFIG:-/etc/InstantLinkBridge/config.toml}"
HOTSPOT_SSID_FILE="${INSTANTLINK_BRIDGE_HOTSPOT_SSID_FILE:-/etc/InstantLinkBridge/hotspot.ssid}"
FALLBACK_HOTSPOT_SSID="InstantLink-XXXX"
PSK_FILE="${INSTANTLINK_BRIDGE_HOTSPOT_PSK_FILE:-/etc/InstantLinkBridge/hotspot.psk}"
NM_READY_TIMEOUT_S="${INSTANTLINK_BRIDGE_NM_READY_TIMEOUT_S:-30}"
HOTSPOT_CHANNEL="${INSTANTLINK_BRIDGE_HOTSPOT_CHANNEL:-6}"
WIFI_STATE_DIR="${INSTANTLINK_BRIDGE_WIFI_STATE_DIR:-/run/InstantLinkBridge-wifi}"
ROOT_CHILD_PID=""

terminate_helper() {
  trap - TERM INT
  if [[ -n "${ROOT_CHILD_PID}" ]]; then
    kill -TERM "${ROOT_CHILD_PID}" 2>/dev/null || true
  fi
  exit 143
}

trap terminate_helper TERM INT

lock_wifi_changes() {
  # Installed invocations run as root. Keep diagnostic non-root invocations on
  # the original sudo path, without trusting a user-owned activation stamp.
  [[ "${EUID}" -eq 0 ]] || return 0
  if [[ -L "${WIFI_STATE_DIR}" ]] ||
    { [[ -e "${WIFI_STATE_DIR}" ]] &&
      [[ ! -d "${WIFI_STATE_DIR}" || "$(stat -c %u "${WIFI_STATE_DIR}")" != 0 ]]; }; then
    echo "Wi-Fi runtime state directory is unsafe" >&2
    return 1
  fi
  install -d -m 0700 "${WIFI_STATE_DIR}"
  local lock="${WIFI_STATE_DIR}/mode.lock"
  if [[ -L "${lock}" ]] ||
    { [[ -e "${lock}" ]] &&
      [[ ! -f "${lock}" || "$(stat -c %u "${lock}")" != 0 ]]; }; then
    echo "Wi-Fi runtime lock is unsafe" >&2
    return 1
  fi
  umask 077
  exec 9>"${lock}"
  run_root flock -w 15 9
}

select_hotspot_uuid() {
  # nmcli escapes colons/backslashes in terse names; split only unescaped
  # separators. Prefer the actual active profile when old duplicate names exist.
  nmcli -t --escape yes -f NAME,UUID,TYPE,DEVICE connection show | python3 -c '
import sys
rows, all_rows = [], []
for line in sys.stdin.read().splitlines():
    fields, part, escaped = [], "", False
    for char in line:
        if escaped:
            part += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append(part)
            part = ""
        else:
            part += char
    fields.append(part)
    if escaped or len(fields) != 4:
        sys.exit(1)
    if fields[2] == "802-11-wireless":
        all_rows.append(fields)
        if fields[0] == sys.argv[1]:
            rows.append(fields)
active = [row for row in rows if row[3] == "wlan0"]
chosen = active if active else rows
if sys.argv[2] == "cleanup":
    for row in all_rows:
        if row[3] in ("", "--") and (row[0] == "InstantBridge-Hotspot" or
                (len(active) == 1 and row[0] == sys.argv[1] and row[1] != active[0][1])):
            print(row[1])
    sys.exit(0)
if len(chosen) > 1:
    print("Hotspot profile name is ambiguous", file=sys.stderr)
    sys.exit(1)
if chosen:
    print(chosen[0][1])
' "${HOTSPOT_CONNECTION}" "${1:-select}"
}

hotspot_activation_stamp() {
  local operation="$1" uuid="$2" host="$3" ssid="$4" psk="$5"
  [[ "${EUID}" -eq 0 ]] || return 1
  # GetAppliedConnection intentionally omits secrets. A private stamp binds
  # the desired PSK digest to a successful helper activation and that exact
  # NetworkManager owner/applied version; public settings alone cannot prove it.
  run_root python3 -c '
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

operation, uuid, host, ssid, channel, directory = sys.argv[1:]
psk = sys.stdin.read().removesuffix("\n")
env = dict(os.environ, LC_ALL="C")

def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=3, env=env).stdout.strip()

def variant(settings, group, key, default=None):
    return settings.get(group, {}).get(key, {}).get("data", default)

try:
    fields = ["connection.uuid", "connection.interface-name", "connection.autoconnect",
              "802-11-wireless.mode", "802-11-wireless.band", "802-11-wireless.channel",
              "802-11-wireless.ssid", "802-11-wireless-security.key-mgmt",
              "802-11-wireless-security.proto", "802-11-wireless-security.pairwise",
              "802-11-wireless-security.group", "802-11-wireless-security.psk",
              "802-11-wireless-security.wps-method", "ipv4.method", "ipv4.addresses",
              "ipv4.never-default", "ipv6.method"]
    saved = command(["nmcli", "--show-secrets", "--escape", "no", "-g",
                     ",".join(fields), "connection", "show", "uuid", uuid]).splitlines()
    expected = [uuid, "wlan0", "no", "ap", "bg", channel, ssid, "wpa-psk", "rsn",
                "ccmp", "ccmp", psk, "1", "shared", host + "/24", "yes", "disabled"]
    if len(saved) != len(expected):
        sys.exit(1)
    saved[12] = str(int(saved[12].split()[0], 0))
    if saved != expected:
        sys.exit(1)
    active = command(["nmcli", "--escape", "no", "-g",
                      "GENERAL.STATE,GENERAL.CON-UUID,GENERAL.DBUS-PATH,GENERAL.CON-PATH",
                      "device", "show", "wlan0"]).splitlines()
    if (len(active) != 4 or active[0].split()[0] != "100" or active[1] != uuid or
            not active[3].startswith("/org/freedesktop/NetworkManager/ActiveConnection/")):
        sys.exit(1)
    addresses = command(["nmcli", "--escape", "no", "-g", "IP4.ADDRESS",
                         "device", "show", "wlan0"]).splitlines()
    if host + "/24" not in addresses:
        sys.exit(1)
    owner = json.loads(command(["busctl", "--timeout=3", "--json=short", "call",
                               "org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", "GetNameOwner", "s",
                               "org.freedesktop.NetworkManager"]))["data"][0]
    applied, version = json.loads(command([
        "busctl", "--timeout=3", "--json=short", "call", owner, active[2],
        "org.freedesktop.NetworkManager.Device", "GetAppliedConnection", "u", "0"
    ]))["data"]
    checks = [("connection", "uuid", uuid), ("connection", "interface-name", "wlan0"),
              ("connection", "autoconnect", False), ("802-11-wireless", "mode", "ap"),
              ("802-11-wireless", "band", "bg"),
              ("802-11-wireless", "channel", int(channel)),
              ("802-11-wireless", "ssid", list(ssid.encode())),
              ("802-11-wireless-security", "key-mgmt", "wpa-psk"),
              ("802-11-wireless-security", "proto", ["rsn"]),
              ("802-11-wireless-security", "pairwise", ["ccmp"]),
              ("802-11-wireless-security", "group", ["ccmp"]),
              ("802-11-wireless-security", "wps-method", 1),
              ("ipv4", "method", "shared"), ("ipv4", "never-default", True),
              ("ipv6", "method", "disabled")]
    if any(variant(applied, group, key) != value for group, key, value in checks):
        sys.exit(1)
    applied_addresses = variant(applied, "ipv4", "address-data", [])
    if not any(row.get("address", {}).get("data") == host and
               row.get("prefix", {}).get("data") == 24 for row in applied_addresses):
        sys.exit(1)
    # Re-read owner and active identity after the applied snapshot so a daemon
    # replacement or activation during these reads cannot validate an old stamp.
    if command(["nmcli", "--escape", "no", "-g",
                "GENERAL.STATE,GENERAL.CON-UUID,GENERAL.DBUS-PATH,GENERAL.CON-PATH", "device", "show",
                "wlan0"]).splitlines() != active:
        sys.exit(1)
    owner_after = json.loads(command(["busctl", "--timeout=3", "--json=short", "call",
                                     "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                     "org.freedesktop.DBus", "GetNameOwner", "s",
                                     "org.freedesktop.NetworkManager"]))["data"][0]
    if owner_after != owner or not isinstance(version, int) or version < 1:
        sys.exit(1)
    applied_after, version_after = json.loads(command([
        "busctl", "--timeout=3", "--json=short", "call", owner, active[2],
        "org.freedesktop.NetworkManager.Device", "GetAppliedConnection", "u", "0"
    ]))["data"]
    if version_after != version or applied_after != applied:
        sys.exit(1)
    desired = hashlib.sha256(json.dumps(expected, ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()
    stamp = {"desired": desired, "owner": owner, "device": active[2],
             "active_connection": active[3], "uuid": uuid, "version": version}
    parent = pathlib.Path(directory)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        sys.exit(1)
    path = parent / "hotspot-applied.json"
    if operation == "check":
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            sys.exit(1)
        if json.loads(path.read_text()) != stamp:
            sys.exit(1)
    elif operation == "record":
        fd, temporary = tempfile.mkstemp(prefix=".hotspot-", dir=parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(stamp, output)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    else:
        sys.exit(1)
except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, subprocess.SubprocessError):
    # A failed optimization read must preserve the original activation path.
    # Do not emit nmcli output: the saved-profile read contains the private PSK.
    sys.exit(1)
' "${operation}" "${uuid}" "${host}" "${ssid}" "${HOTSPOT_CHANNEL}" "${WIFI_STATE_DIR}" <<<"${psk}"
}

require_nmcli() {
  command -v nmcli >/dev/null || {
    echo "nmcli is required; install NetworkManager first" >&2
    exit 1
  }
}

wait_for_networkmanager() {
  local waited=0
  while (( waited < NM_READY_TIMEOUT_S )); do
    if nmcli -t -f RUNNING general 2>/dev/null | grep -qx "running"; then
      return
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "NetworkManager is not running after ${NM_READY_TIMEOUT_S}s" >&2
  exit 1
}

run_root() {
  # Wait asynchronously so TERM reaches this trap while nmcli is still running.
  # Otherwise cancelling a mode switch could leave it activating the old mode.
  if [[ "${EUID}" -eq 0 ]]; then
    "$@" <&0 &
  else
    sudo "$@" <&0 &
  fi
  ROOT_CHILD_PID=$!
  local result=0
  wait "${ROOT_CHILD_PID}" || result=$?
  ROOT_CHILD_PID=""
  return "${result}"
}

ensure_wifi_interface() {
  # A failed SDIO firmware download can leave the driver loaded with no wlan0.
  # Enabling the radio alone cannot recover that state. Only reload on a Pi
  # whose interface is missing; a healthy interface must never be interrupted.
  run_root nmcli radio wifi on
  local net_path="${INSTANTLINK_BRIDGE_NET_SYSFS:-/sys/class/net}"
  local model_path="${INSTANTLINK_BRIDGE_MODEL_PATH:-/proc/device-tree/model}"
  local module_path="${INSTANTLINK_BRIDGE_MODULE_SYSFS:-/sys/module}"
  if [[ -d "${net_path}/wlan0" ]]; then
    return
  fi
  if [[ ! -r "${model_path}" ]] || ! grep -aq 'Raspberry Pi' "${model_path}"; then
    echo "Wi-Fi interface wlan0 is unavailable; automatic driver recovery requires a Raspberry Pi" >&2
    return 1
  fi
  echo "Wi-Fi interface missing; recovering brcmfmac driver" >&2
  if [[ -d "${module_path}/brcmfmac" ]]; then
    # The vendor extension can retain a reference after a once-healthy radio
    # loses its SDIO binding. Unload it before the base driver, not Bluetooth.
    if [[ -d "${module_path}/brcmfmac/holders/brcmfmac_wcc" ]]; then
      run_root modprobe -r brcmfmac_wcc
    fi
    run_root modprobe -r brcmfmac
  fi
  run_root modprobe brcmfmac
  local waited=0
  while (( waited < 10 )); do
    if [[ -d "${net_path}/wlan0" ]]; then
      return
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "Wi-Fi interface wlan0 is still unavailable after driver recovery" >&2
  return 1
}

hotspot_ssid() {
  if [[ -n "${INSTANTLINK_BRIDGE_HOTSPOT_SSID:-}" ]]; then
    printf '%s\n' "${INSTANTLINK_BRIDGE_HOTSPOT_SSID}"
    return
  fi
  if [[ -r "${HOTSPOT_SSID_FILE}" ]]; then
    local configured_file
    configured_file="$(sed -n '1p' "${HOTSPOT_SSID_FILE}")"
    if [[ -n "${configured_file}" ]]; then
      printf '%s\n' "${configured_file}"
      return
    fi
  fi
  local uuid="${1:-}"
  if [[ -z "${uuid}" ]]; then
    uuid="$(select_hotspot_uuid)"
  fi
  if [[ -n "${uuid}" ]]; then
    local configured
    configured="$(nmcli --escape no -g 802-11-wireless.ssid connection show uuid "${uuid}")"
    if [[ -n "${configured}" ]]; then
      printf '%s\n' "${configured}"
      return
    fi
  fi
  default_hotspot_ssid
}

default_hotspot_ssid() {
  local machine_id
  local machine_id_path
  for machine_id_path in /etc/machine-id /var/lib/dbus/machine-id; do
    if [[ -r "${machine_id_path}" ]]; then
      machine_id="$(sed -n '1p' "${machine_id_path}" | tr '[:lower:]' '[:upper:]')"
      if [[ "${machine_id}" =~ ^[0-9A-F]{8} ]]; then
        printf 'InstantLink-%s\n' "${machine_id:4:4}"
        return
      fi
    fi
  done
  printf '%s\n' "${FALLBACK_HOTSPOT_SSID}"
}

hotspot_host() {
  if [[ -n "${INSTANTLINK_BRIDGE_HOTSPOT_HOST:-}" ]]; then
    printf '%s\n' "${INSTANTLINK_BRIDGE_HOTSPOT_HOST}"
    return
  fi
  if [[ -r "${CONFIG_FILE}" ]]; then
    local configured
    configured="$(awk '
      /^\[ftp\]$/ { in_ftp = 1; next }
      /^\[/ { in_ftp = 0 }
      in_ftp && /^hotspot_host = / {
        value = $0
        sub(/^hotspot_host = "/, "", value)
        sub(/"$/, "", value)
        print value
        exit
      }
    ' "${CONFIG_FILE}")"
    if [[ -n "${configured}" ]]; then
      printf '%s\n' "${configured}"
      return
    fi
  fi
  printf '%s\n' '192.168.8.1'
}

prepare_hotspot_psk() {
  # Keep mutable root commands in the main shell so TERM owns their PID.
  # Capturing the effective PSK below must perform only reads.
  if [[ -n "${INSTANTLINK_BRIDGE_HOTSPOT_PSK:-}" ]]; then
    if ! valid_hotspot_psk "${INSTANTLINK_BRIDGE_HOTSPOT_PSK}"; then
      echo "INSTANTLINK_BRIDGE_HOTSPOT_PSK must be exactly 8 digits" >&2
      exit 2
    fi
    return
  fi
  local existing
  existing="$(read_hotspot_psk || true)"
  if [[ -n "${existing}" ]]; then
    ensure_hotspot_psk_permissions
    return
  fi
  run_root install -d -m 0750 "$(dirname "${PSK_FILE}")"
  local generated
  generated="$(generate_hotspot_psk)"
  write_hotspot_psk "${generated}"
}

hotspot_psk() {
  if [[ -n "${INSTANTLINK_BRIDGE_HOTSPOT_PSK:-}" ]]; then
    valid_hotspot_psk "${INSTANTLINK_BRIDGE_HOTSPOT_PSK}" || return 2
    printf '%s\n' "${INSTANTLINK_BRIDGE_HOTSPOT_PSK}"
  else
    read_hotspot_psk
  fi
}

valid_hotspot_psk() {
  [[ "$1" =~ ^[0-9]{8}$ ]]
}

delete_stale_hotspot_profiles() {
  local uuid
  while IFS= read -r uuid; do
    [[ -n "${uuid}" ]] || continue
    run_root nmcli connection delete uuid "${uuid}" >/dev/null 2>&1 || true
  done < <(select_hotspot_uuid cleanup)
}

read_hotspot_psk() {
  if [[ ! -r "${PSK_FILE}" ]]; then
    return 1
  fi
  local existing
  existing="$(sed -n '1p' "${PSK_FILE}")"
  if ! valid_hotspot_psk "${existing}"; then
    return 1
  fi
  printf '%s\n' "${existing}"
}

generate_hotspot_psk() {
  od -An -N4 -tu4 /dev/urandom | awk '{ printf "%08d\n", $1 % 100000000 }'
}

write_hotspot_psk() {
  run_root tee "${PSK_FILE}" <<<"$1" >/dev/null
  ensure_hotspot_psk_permissions
}

ensure_hotspot_psk_permissions() {
  if getent group ib >/dev/null 2>&1; then
    run_root chgrp ib "${PSK_FILE}"
  fi
  run_root chmod 0640 "${PSK_FILE}"
}

configure_hotspot() {
  local host
  local psk
  local ssid
  local uuid
  uuid="$(select_hotspot_uuid)"
  host="$(hotspot_host)"
  ssid="$(hotspot_ssid "${uuid}")"
  prepare_hotspot_psk
  psk="$(hotspot_psk)"
  ensure_wifi_interface
  if [[ -n "${uuid}" ]] &&
    hotspot_activation_stamp check "${uuid}" "${host}" "${ssid}" "${psk}"; then
    delete_stale_hotspot_profiles
    echo "Hotspot already active: SSID=${ssid} FTP=${host}"
    return
  fi
  if [[ -z "${uuid}" ]]; then
    run_root nmcli connection add type wifi ifname wlan0 con-name "${HOTSPOT_CONNECTION}" \
      ssid "${ssid}"
    uuid="$(select_hotspot_uuid)"
    if [[ -z "${uuid}" ]]; then
      echo "Created hotspot profile was not found" >&2
      return 1
    fi
  fi
  run_root nmcli connection modify uuid "${uuid}" \
    connection.interface-name wlan0 \
    connection.autoconnect no \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel "${HOTSPOT_CHANNEL}" \
    802-11-wireless.ssid "${ssid}" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.proto rsn \
    wifi-sec.pairwise ccmp \
    wifi-sec.group ccmp \
    wifi-sec.psk "${psk}" \
    wifi-sec.wps-method 1 \
    ipv4.method shared \
    ipv4.addresses "${host}/24" \
    ipv4.never-default yes \
    ipv6.method disabled
  run_root nmcli connection up uuid "${uuid}" ifname wlan0
  hotspot_activation_stamp record "${uuid}" "${host}" "${ssid}" "${psk}" || true
  delete_stale_hotspot_profiles
  echo "Hotspot active: SSID=${ssid} FTP=${host}"
}

configure_home() {
  local ssid="${2:-}"
  local password="${3:-}"
  if [[ -z "${ssid}" || -z "${password}" ]]; then
    echo "Usage: scripts/wifi-mode.sh home <ssid> <password>" >&2
    exit 2
  fi
  ensure_wifi_interface
  if nmcli -t -f NAME connection show | grep -qxF "${HOME_CONNECTION}"; then
    run_root nmcli connection modify "${HOME_CONNECTION}" \
      802-11-wireless.ssid "${ssid}" \
      wifi-sec.key-mgmt wpa-psk \
      wifi-sec.psk "${password}" \
      ipv4.method auto \
      ipv4.never-default no \
      ipv6.method disabled
  else
    run_root nmcli connection add type wifi ifname wlan0 con-name "${HOME_CONNECTION}" ssid "${ssid}" \
      wifi-sec.key-mgmt wpa-psk wifi-sec.psk "${password}" ipv4.method auto ipv6.method disabled
  fi
  run_root nmcli connection down "${HOTSPOT_CONNECTION}" >/dev/null 2>&1 || true
  run_root nmcli connection up "${HOME_CONNECTION}"
  echo "Home Wi-Fi active: SSID=${ssid}"
}

configure_home_saved() {
  local connection="${2:-}"
  if [[ -z "${connection}" ]]; then
    if nmcli -t -f NAME connection show | grep -qxF "${HOME_CONNECTION}"; then
      connection="${HOME_CONNECTION}"
    else
      connection="$(
        nmcli -t -f NAME,TYPE,AUTOCONNECT connection show |
          awk -F: -v hotspot="${HOTSPOT_CONNECTION}" \
            '$2 == "802-11-wireless" && $1 != hotspot && $3 == "yes" { print $1; exit }'
      )"
    fi
  fi
  if [[ -z "${connection}" ]]; then
    echo "No saved home Wi-Fi connection found" >&2
    exit 1
  fi
  ensure_wifi_interface
  run_root nmcli connection down "${HOTSPOT_CONNECTION}" >/dev/null 2>&1 || true
  run_root nmcli connection up "${connection}"
  echo "Home Wi-Fi active: connection=${connection}"
}

status() {
  nmcli -f NAME,TYPE,DEVICE,AUTOCONNECT connection show
  ip -4 -o addr show dev wlan0 2>/dev/null || true
  if nmcli -t -f NAME connection show | grep -qxF "${HOTSPOT_CONNECTION}"; then
    echo "Configured hotspot SSID: $(hotspot_ssid)"
    local psk
    psk="$(read_hotspot_psk || true)"
    echo "Configured hotspot PIN: ${psk:-not set}"
  fi
}

require_nmcli
wait_for_networkmanager
if [[ "${MODE}" != status ]]; then
  lock_wifi_changes
fi
case "${MODE}" in
  hotspot)
    configure_hotspot
    ;;
  home)
    configure_home "$@"
    ;;
  home-saved)
    configure_home_saved "$@"
    ;;
  off)
    run_root nmcli connection down "${HOTSPOT_CONNECTION}" >/dev/null 2>&1 || true
    run_root nmcli radio wifi off
    echo "Wi-Fi radio disabled"
    ;;
  status)
    status
    ;;
  *)
    echo "Usage: scripts/wifi-mode.sh {status|hotspot|home <ssid> <password>|home-saved [connection]|off}" >&2
    exit 2
    ;;
esac
