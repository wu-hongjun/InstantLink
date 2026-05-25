#!/usr/bin/env bash
set -euo pipefail

GADGET_NAME="${INSTANTLINK_BRIDGE_GADGET_NAME:-instantlink-bridge}"
GADGET_DIR="/sys/kernel/config/usb_gadget/${GADGET_NAME}"
USB_IFACE="${INSTANTLINK_BRIDGE_USB_IFACE:-usb0}"
USB_ADDR="${INSTANTLINK_BRIDGE_USB_ADDR:-192.168.7.1/24}"
HOST_ADDR="${INSTANTLINK_BRIDGE_USB_HOST_ADDR:-02:1a:57:00:00:01}"
DEV_ADDR="${INSTANTLINK_BRIDGE_USB_DEV_ADDR:-02:1a:57:00:00:02}"
SERIAL="${INSTANTLINK_BRIDGE_USB_SERIAL:-InstantLink Bridge}"
MANUFACTURER="${INSTANTLINK_BRIDGE_USB_MANUFACTURER:-InstantLink Bridge}"
PRODUCT_PREFIX="${INSTANTLINK_BRIDGE_USB_PRODUCT_PREFIX:-InstantLink Bridge Ethernet}"
CONFIGFS="/sys/kernel/config"

usage() {
  cat <<'USAGE'
Usage: scripts/usb-gadget-mode.sh <command> [mode]

Commands:
  status              Print current USB gadget state.
  start <mode>        Replace g_ether/configfs gadget with a test mode.
  watch [seconds]     Watch UDC, carrier, operstate, leases, and recent logs.
  reset-g-ether       Restore the legacy g_ether module path.
  cleanup             Remove the configfs gadget and unload g_ether if possible.

Modes for start:
  ecm                 CDC-ECM function, generic Linux VID/PID.
  ncm                 CDC-NCM function, generic Linux VID/PID.
  rndis               RNDIS function, generic Linux VID/PID.
  ecm-rndis           Composite CDC-ECM + RNDIS.
  ecm-realtek         CDC-ECM with RTL8153 VID/PID spoof.
  ncm-realtek         CDC-NCM with RTL8153 VID/PID spoof.
  ncm-asix            CDC-NCM with ASIX AX88179B-style VID/PID spoof.

This is an experiment harness. It is intentionally non-persistent; reboot or
run reset-g-ether to return to the provisioned InstantLink Bridge default.
USAGE
}

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: run as root" >&2
    exit 1
  fi
}

first_udc() {
  local udc
  udc="${INSTANTLINK_BRIDGE_UDC:-}"
  if [[ -n "${udc}" ]]; then
    printf '%s' "${udc}"
    return
  fi
  find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | head -1
}

ensure_configfs() {
  if ! mountpoint -q "${CONFIGFS}"; then
    mount -t configfs none "${CONFIGFS}"
  fi
}

remove_link_if_exists() {
  local path="$1"
  if [[ -L "${path}" ]]; then
    rm -f "${path}"
  fi
}

cleanup_configfs() {
  if [[ ! -d "${GADGET_DIR}" ]]; then
    return
  fi

  if [[ -f "${GADGET_DIR}/UDC" ]]; then
    echo "" > "${GADGET_DIR}/UDC" 2>/dev/null || true
  fi

  find "${GADGET_DIR}/configs" -type l -exec rm -f {} + 2>/dev/null || true

  while IFS= read -r -d '' path; do
    rmdir "${path}" 2>/dev/null || true
  done < <(find "${GADGET_DIR}/functions" -depth -mindepth 1 -type d -print0 2>/dev/null || true)

  while IFS= read -r -d '' path; do
    rmdir "${path}" 2>/dev/null || true
  done < <(find "${GADGET_DIR}/configs" -depth -mindepth 1 -type d -print0 2>/dev/null || true)

  while IFS= read -r -d '' path; do
    rmdir "${path}" 2>/dev/null || true
  done < <(find "${GADGET_DIR}/strings" -depth -mindepth 1 -type d -print0 2>/dev/null || true)

  rmdir "${GADGET_DIR}" 2>/dev/null || true
}

stop_legacy_g_ether() {
  ip link set "${USB_IFACE}" down 2>/dev/null || true
  modprobe -r g_ether 2>/dev/null || true
}

write_gadget_ids() {
  local mode="$1"
  local vid="0x1d6b"
  local pid="0x0104"

  case "${mode}" in
    ecm-realtek|ncm-realtek)
      vid="0x0bda"
      pid="0x8153"
      ;;
    ncm-asix)
      vid="0x0b95"
      pid="0x1790"
      ;;
  esac

  echo "${vid}" > "${GADGET_DIR}/idVendor"
  echo "${pid}" > "${GADGET_DIR}/idProduct"
  echo "0x0200" > "${GADGET_DIR}/bcdUSB"
  echo "0x0100" > "${GADGET_DIR}/bcdDevice"
}

write_device_class() {
  local mode="$1"
  case "${mode}" in
    rndis|ecm-rndis)
      echo "0xef" > "${GADGET_DIR}/bDeviceClass"
      echo "0x02" > "${GADGET_DIR}/bDeviceSubClass"
      echo "0x01" > "${GADGET_DIR}/bDeviceProtocol"
      ;;
    *)
      echo "0x02" > "${GADGET_DIR}/bDeviceClass"
      echo "0x00" > "${GADGET_DIR}/bDeviceSubClass"
      echo "0x00" > "${GADGET_DIR}/bDeviceProtocol"
      ;;
  esac
}

set_ether_attrs() {
  local function_dir="$1"
  [[ -f "${function_dir}/host_addr" ]] && echo "${HOST_ADDR}" > "${function_dir}/host_addr"
  [[ -f "${function_dir}/dev_addr" ]] && echo "${DEV_ADDR}" > "${function_dir}/dev_addr"
  [[ -f "${function_dir}/ifname" ]] && echo "${USB_IFACE}" > "${function_dir}/ifname" 2>/dev/null || true
}

add_function() {
  local function_name="$1"
  local instance="$2"
  local function_dir="${GADGET_DIR}/functions/${function_name}.${instance}"

  mkdir -p "${function_dir}"
  set_ether_attrs "${function_dir}"
  ln -s "${function_dir}" "${GADGET_DIR}/configs/c.1/${function_name}.${instance}"
}

start_mode() {
  local mode="$1"
  local udc
  udc="$(first_udc)"
  if [[ -z "${udc}" ]]; then
    echo "ERROR: no USB device controller found under /sys/class/udc" >&2
    exit 1
  fi

  ensure_configfs
  cleanup_configfs
  stop_legacy_g_ether

  mkdir -p "${GADGET_DIR}"
  write_gadget_ids "${mode}"
  write_device_class "${mode}"

  mkdir -p "${GADGET_DIR}/strings/0x409"
  echo "${SERIAL}" > "${GADGET_DIR}/strings/0x409/serialnumber"
  echo "${MANUFACTURER}" > "${GADGET_DIR}/strings/0x409/manufacturer"
  echo "${PRODUCT_PREFIX} ${mode}" > "${GADGET_DIR}/strings/0x409/product"

  mkdir -p "${GADGET_DIR}/configs/c.1/strings/0x409"
  echo "InstantLink Bridge ${mode}" > "${GADGET_DIR}/configs/c.1/strings/0x409/configuration"
  echo "0xc0" > "${GADGET_DIR}/configs/c.1/bmAttributes"
  echo "2" > "${GADGET_DIR}/configs/c.1/MaxPower"

  case "${mode}" in
    ecm|ecm-realtek)
      add_function ecm usb0
      ;;
    ncm|ncm-realtek|ncm-asix)
      add_function ncm usb0
      ;;
    rndis)
      add_function rndis usb0
      ;;
    ecm-rndis)
      add_function ecm usb0
      add_function rndis usb1
      ;;
    *)
      echo "ERROR: unknown mode: ${mode}" >&2
      usage >&2
      exit 1
      ;;
  esac

  echo "${udc}" > "${GADGET_DIR}/UDC"
  sleep 1
  configure_usb_iface
  status
}

configure_usb_iface() {
  if ip link show "${USB_IFACE}" >/dev/null 2>&1; then
    ip addr replace "${USB_ADDR}" dev "${USB_IFACE}" 2>/dev/null || true
    ip link set "${USB_IFACE}" up 2>/dev/null || true
  fi
  systemctl restart systemd-networkd.service 2>/dev/null || true
  systemctl restart dnsmasq.service 2>/dev/null || true
}

reset_g_ether() {
  cleanup_configfs
  stop_legacy_g_ether
  modprobe g_ether
  sleep 1
  configure_usb_iface
  status
}

status() {
  local udc
  echo "== gadget status =="
  echo "time=$(date -Is)"
  echo "gadget_dir=${GADGET_DIR}"
  echo "udc_list=$(find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f ' 2>/dev/null || true)"
  for udc in /sys/class/udc/*; do
    [[ -e "${udc}" ]] || continue
    echo "$(basename "${udc}") state=$(cat "${udc}/state" 2>/dev/null || true)"
  done
  if [[ -d "${GADGET_DIR}" ]]; then
    echo "bound_udc=$(cat "${GADGET_DIR}/UDC" 2>/dev/null || true)"
    echo "idVendor=$(cat "${GADGET_DIR}/idVendor" 2>/dev/null || true)"
    echo "idProduct=$(cat "${GADGET_DIR}/idProduct" 2>/dev/null || true)"
    find "${GADGET_DIR}/functions" -mindepth 1 -maxdepth 1 -type d -printf 'function=%f\n' 2>/dev/null || true
  fi
  echo "== interface =="
  ip -br link show "${USB_IFACE}" 2>/dev/null || true
  ip -br addr show "${USB_IFACE}" 2>/dev/null || true
  [[ -e "/sys/class/net/${USB_IFACE}/carrier" ]] && echo "carrier=$(cat "/sys/class/net/${USB_IFACE}/carrier")"
  [[ -e "/sys/class/net/${USB_IFACE}/operstate" ]] && echo "operstate=$(cat "/sys/class/net/${USB_IFACE}/operstate")"
  echo "== leases =="
  cat /var/lib/misc/dnsmasq.leases 2>/dev/null || true
}

watch_state() {
  local duration="${1:-30}"
  local start
  start="$(date +%s)"
  while (( "$(date +%s)" - start < duration )); do
    local state="none"
    local carrier="none"
    local oper="none"
    local lease="none"
    local udc
    udc="$(first_udc)"
    [[ -n "${udc}" ]] && state="$(cat "/sys/class/udc/${udc}/state" 2>/dev/null || echo none)"
    [[ -e "/sys/class/net/${USB_IFACE}/carrier" ]] && carrier="$(cat "/sys/class/net/${USB_IFACE}/carrier" 2>/dev/null || echo none)"
    [[ -e "/sys/class/net/${USB_IFACE}/operstate" ]] && oper="$(cat "/sys/class/net/${USB_IFACE}/operstate" 2>/dev/null || echo none)"
    lease="$(awk '/192\.168\.7\./ { print $3 " " $4 }' /var/lib/misc/dnsmasq.leases 2>/dev/null | tail -1)"
    printf '%s udc=%s carrier=%s oper=%s lease=%s\n' \
      "$(date +%H:%M:%S)" "${state}" "${carrier}" "${oper}" "${lease:-none}"
    sleep 1
  done
  echo "== recent USB kernel logs =="
  journalctl -k --since "2 minutes ago" --no-pager |
    grep -Ei 'dwc2|g_ether|usb0|rndis|ecm|ncm|gadget|ether|cdc|usb|udc|configfs' || true
  echo "== recent DHCP/FTP logs =="
  journalctl -u dnsmasq.service -u instantlink-bridge.service --since "2 minutes ago" --no-pager |
    grep -Ei 'usb0|192\.168\.7|dhcp|ftp|connect|login|STOR|wired|source=' || true
}

command="${1:-}"
case "${command}" in
  status)
    status
    ;;
  start)
    need_root
    start_mode "${2:-}"
    ;;
  watch)
    watch_state "${2:-30}"
    ;;
  reset-g-ether)
    need_root
    reset_g_ether
    ;;
  cleanup)
    need_root
    cleanup_configfs
    stop_legacy_g_ether
    status
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "ERROR: unknown command: ${command}" >&2
    usage >&2
    exit 1
    ;;
esac
