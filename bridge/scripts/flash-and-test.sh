#!/usr/bin/env bash
set -euo pipefail

echo "InstantLink Bridge target validation commands"
echo
echo "USB gadget modules:"
echo "  lsmod | grep -E 'dwc2|g_ether'"
echo
echo "usb0 address:"
echo "  ip addr show usb0"
echo
echo "USB gadget attachment state:"
echo "  cat /sys/class/udc/*/state"
echo "  networkctl status usb0 --no-pager"
echo
echo "DHCP/FTP logs:"
echo "  journalctl -u systemd-networkd -u dnsmasq -u instantlink-bridge --boot"
echo
echo "Previous-boot reset diagnostics:"
echo "  journalctl -b -1 -k | grep -Ei 'usb|dwc|g_ether|under.?voltage|power|reset'"
echo "  journalctl -b -1 -u instantlink-bridge.service"
echo
echo "Camera link packet capture:"
echo "  sudo tcpdump -i usb0 port 67 or port 68 or port 21"
echo
echo "Run FTP receive slice:"
echo "  instantlink-bridge --config /etc/InstantLinkBridge/config.toml --log-level DEBUG"
