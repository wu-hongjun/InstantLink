#!/usr/bin/env bash
set -euo pipefail

MODE=report

SAFE_DISABLE_UNITS=(
  NetworkManager-wait-online.service
  apt-daily.timer
  apt-daily-upgrade.timer
  man-db.timer
  e2scrub_reap.service
)

SAFE_STOP_UNITS=(
  apt-daily.service
  apt-daily-upgrade.service
  man-db.service
)

PROTECTED_UNITS=(
  NetworkManager.service
  bluetooth.service
  dbus.service
  dnsmasq.service
  instantlink-bridge.service
  systemd-networkd.service
)

REPORT_ONLY_UNITS=(
  instantlink-bridge-boot-splash.service
  tailscaled.service
  hciuart.service
  ModemManager.service
  cups.service
  avahi-daemon.service
  triggerhappy.service
  dphys-swapfile.service
  logrotate.timer
)

usage() {
  cat <<'USAGE'
Usage: scripts/boot-diet.sh [--report|--apply]

Reports or applies the conservative InstantLink Bridge boot diet on a target Pi.

Modes:
  --report  Print boot timings, protected service state, and diet candidates.
            This is the default and makes no changes.
  --apply   Disable only non-network, non-BLE background units from the safe
            diet list, then print the resulting service state.

The apply mode intentionally preserves NetworkManager, systemd-networkd,
dnsmasq, bluetooth/BlueZ, and instantlink-bridge.service so hotspot mode, peer Wi-Fi,
USB camera networking, and BLE reconnects remain intact.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --report)
      MODE=report
      shift
      ;;
    --apply)
      MODE=apply
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_systemd() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemctl is required; run this on the target Pi." >&2
    exit 1
  fi
}

sudo_cmd() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

unit_exists() {
  local unit="$1"

  if systemctl list-unit-files --no-legend --no-pager "${unit}" 2>/dev/null |
    awk '{ print $1 }' | grep -Fxq "${unit}"; then
    return 0
  fi

  systemctl list-units --all --no-legend --no-pager "${unit}" 2>/dev/null |
    awk '{ print $1 }' | grep -Fxq "${unit}"
}

unit_enabled_state() {
  local unit="$1"
  local state

  state="$(systemctl is-enabled "${unit}" 2>/dev/null || true)"
  if [[ -z "${state}" ]]; then
    state="not-found"
  fi
  printf '%s' "${state}"
}

unit_active_state() {
  local unit="$1"
  local state

  state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
  if [[ -z "${state}" ]]; then
    state="unknown"
  fi
  printf '%s' "${state}"
}

print_units() {
  local title="$1"
  shift

  printf '\n%s\n' "${title}"
  printf '%-42s %-14s %-14s\n' "unit" "enabled" "active"
  printf '%-42s %-14s %-14s\n' "----" "-------" "------"
  local unit
  for unit in "$@"; do
    printf '%-42s %-14s %-14s\n' \
      "${unit}" \
      "$(unit_enabled_state "${unit}")" \
      "$(unit_active_state "${unit}")"
  done
}

print_boot_measurements() {
  printf 'Boot summary\n'
  if command -v systemd-analyze >/dev/null 2>&1; then
    SYSTEMD_PAGER=cat systemd-analyze || true

    printf '\nTop boot blame entries\n'
    SYSTEMD_PAGER=cat systemd-analyze --no-pager blame 2>/dev/null | sed -n '1,20p' || true

    printf '\nInstantLink Bridge critical chain\n'
    SYSTEMD_PAGER=cat systemd-analyze --no-pager critical-chain instantlink-bridge.service 2>/dev/null || true
  else
    echo "systemd-analyze not found"
  fi
}

print_app_milestones() {
  printf '\nInstantLink Bridge boot milestones\n'
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --boot -o short-monotonic -u instantlink-bridge.service 2>/dev/null |
      grep -E 'bridge\.(boot\.start|usb\.ready|bt\.scanning|bt\.connected|ui\.ready|ready)' ||
      echo "No bridge.* boot milestones found in this boot journal."
  else
    echo "journalctl not found"
  fi
}

print_boot_config() {
  local config_txt="${INSTANTLINK_BRIDGE_BOOT_CONFIG:-/boot/firmware/config.txt}"
  local token

  printf '\nBoot firmware config checks (%s)\n' "${config_txt}"
  if [[ ! -f "${config_txt}" ]]; then
    echo "missing"
    return
  fi

  for token in \
    "camera_auto_detect=0" \
    "display_auto_detect=0" \
    "auto_initramfs=0" \
    "max_framebuffers=1" \
    "disable_splash=1" \
    "boot_delay=0" \
    "dtparam=audio=off" \
    "dtoverlay=fbtft,spi0-0,st7789v,width=240,height=240,dc_pin=25,reset_pin=27,led_pin=24,rotate=270,speed=40000000,fps=30"; do
    if grep -qxF "${token}" "${config_txt}"; then
      printf 'present: %s\n' "${token}"
    else
      printf 'missing: %s\n' "${token}"
    fi
  done
}

assert_safe_apply_set() {
  local unit
  local protected

  for unit in "${SAFE_DISABLE_UNITS[@]}" "${SAFE_STOP_UNITS[@]}"; do
    for protected in "${PROTECTED_UNITS[@]}"; do
      if [[ "${unit}" == "${protected}" ]]; then
        echo "ERROR: safe diet includes protected unit ${unit}" >&2
        exit 1
      fi
    done
  done
}

disable_unit_if_present() {
  local unit="$1"

  if ! unit_exists "${unit}"; then
    printf 'skip missing: %s\n' "${unit}"
    return
  fi

  printf 'disable --now: %s\n' "${unit}"
  sudo_cmd systemctl disable --now "${unit}"
}

stop_unit_if_present() {
  local unit="$1"

  if ! unit_exists "${unit}"; then
    printf 'skip missing: %s\n' "${unit}"
    return
  fi

  printf 'stop: %s\n' "${unit}"
  sudo_cmd systemctl stop "${unit}"
}

report() {
  require_systemd
  print_boot_measurements
  print_units "Protected service state" "${PROTECTED_UNITS[@]}"
  print_units "Safe diet candidates" "${SAFE_DISABLE_UNITS[@]}" "${SAFE_STOP_UNITS[@]}"
  print_units "Report-only candidates" "${REPORT_ONLY_UNITS[@]}"
  print_boot_config
  print_app_milestones
}

apply_diet() {
  require_systemd
  assert_safe_apply_set

  local unit
  for unit in "${SAFE_DISABLE_UNITS[@]}"; do
    disable_unit_if_present "${unit}"
  done
  for unit in "${SAFE_STOP_UNITS[@]}"; do
    stop_unit_if_present "${unit}"
  done

  print_units "Safe diet candidates after apply" "${SAFE_DISABLE_UNITS[@]}" "${SAFE_STOP_UNITS[@]}"
}

if [[ "${MODE}" == "apply" ]]; then
  apply_diet
else
  report
fi
