#!/usr/bin/env bash
set -u

USB_IFACE="${INSTANTLINK_BRIDGE_USB_IFACE:-usb0}"
LOG_PATH="${INSTANTLINK_BRIDGE_USB_PROBE_LOG:-/tmp/instantlink-bridge-usb-gadget-probe.log}"

mkdir -p "$(dirname "${LOG_PATH}")"
exec > >(tee "${LOG_PATH}") 2>&1

log() {
  printf '\n[%s] %s\n' "$(date -Is)" "$*"
}

run() {
  log "RUN $*"
  "$@" || true
}

log "InstantLink Bridge USB gadget probe"
run hostname
run date

log "Kernel modules"
run lsmod
run sh -c 'grep -E "dwc2|g_ether|libcomposite|usb_f_|u_ether" /proc/modules || true'

log "USB gadget interface"
run ip -br link show "${USB_IFACE}"
run ip -br addr show "${USB_IFACE}"
run sh -c "cat /sys/class/net/${USB_IFACE}/carrier 2>/dev/null || true"
run sh -c "cat /sys/class/net/${USB_IFACE}/operstate 2>/dev/null || true"
run sh -c "cat /sys/class/net/${USB_IFACE}/address 2>/dev/null || true"

log "Network manager ownership"
run networkctl status "${USB_IFACE}" --no-pager
run nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status

log "Runtime routes"
run ip route show

log "dnsmasq configuration and leases"
run sh -c 'grep -R "interface=usb0\\|dhcp-range\\|dhcp-host" /etc/dnsmasq.conf /etc/dnsmasq.d 2>/dev/null || true'
run sh -c 'cat /var/lib/misc/dnsmasq.leases 2>/dev/null || true'
run sh -c 'cat /var/lib/dnsmasq/dnsmasq.leases 2>/dev/null || true'
run sh -c 'cat /run/dnsmasq/dnsmasq.leases 2>/dev/null || true'

log "Recent system logs"
run journalctl -u systemd-networkd -u dnsmasq -u instantlink-bridge.service -n 120 --no-pager

log "Recent kernel USB logs"
run sh -c 'journalctl -k -n 160 --no-pager | grep -Ei "dwc2|g_ether|usb0|rndis|cdc|ether|gadget|udc|configfs|usb " || true'

log "Probe complete"
