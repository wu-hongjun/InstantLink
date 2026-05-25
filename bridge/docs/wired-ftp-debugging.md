# Wired FTP Debugging

Date: 2026-05-22

This page is now an admin/diagnostics reference. Direct Sony USB-LAN from the camera to the Pi Zero
USB gadget is not a supported v1 camera wired mode. v1 camera FTP should use the bridge hotspot
first, with Same Wi-Fi advanced FTP as the optional path.

## Expected Diagnostic Working State

When the Pi Zero 2 W USB gadget path is working with a normal computer host:

- The cable is plugged into the Pi Zero data port labeled `USB`, not the `PWR IN` port.
- The Pi is powered independently by the battery case or the `PWR IN` port.
- The host sees a USB Ethernet device with product string `InstantLink Bridge Ethernet`.
- The Pi shows `usb0` carrier up and `192.168.7.1/24`.
- The host receives an address on `192.168.7.0/24`, normally `192.168.7.10` from `dnsmasq`.
- `dnsmasq` records a lease.
- `ping 192.168.7.1` from the host works.

On the Pi:

```bash
scripts/probe-usb-gadget.sh
```

On macOS:

```bash
system_profiler SPUSBDataType | egrep -i 'RNDIS|ECM|Ethernet|Linux|Gadget|CDC|InstantLink Bridge' -A6 -B3
networksetup -listallhardwareports
ifconfig
route -n get 192.168.7.1
ping -c 2 192.168.7.1
```

## Live Test Against The Mac

After reconnecting the same cable on 2026-05-22 at 17:39 EDT, the Mac path worked:

- macOS showed hardware port `InstantLink Bridge Ethernet` on `en10`.
- macOS routed `192.168.7.1` over `en10`.
- `ping 192.168.7.1` succeeded.
- The Pi showed `usb0` carrier up with `192.168.7.1/24`.
- `dnsmasq` offered and acknowledged `192.168.7.10` to client `Hongjuns-MBP`.
- FTP login to `192.168.7.1:21` succeeded with the configured bridge credentials.

This proves the current Pi OS gadget configuration, cable, and adapter chain can work with a normal
computer.

## Earlier Failed Mac Test

With the Pi connected to the Mac through a micro-USB cable and Apple USB-A to USB-C adapter:

- macOS did not show a Linux/RNDIS/CDC/ECM/InstantLink Bridge USB gadget in `system_profiler`.
- macOS listed Ethernet-style interfaces `en4`, `en5`, and `en6`, but all were inactive with
  `media: none`.
- macOS routed `192.168.7.1` over Wi-Fi `en0`, not a USB Ethernet interface.
- `ping 192.168.7.1` failed.
- The Pi had `usb0` configured as `192.168.7.1/24`, but link state was `NO-CARRIER`.
- The Pi `dnsmasq` lease files were empty.

That earlier failure was below FTP and below camera-specific behavior: the USB gadget Ethernet
device had not enumerated as a link to the host yet.

## Likely Causes

Check in this order:

1. The cable is plugged into the Pi Zero `PWR IN` micro-USB port instead of the `USB` data port.
2. The micro-USB cable is charge-only or has a broken data pair.
3. The adapter/cable chain is not passing USB data.
4. The camera/computer is not acting as the USB host for the Pi gadget.
5. The host enumerates USB but rejects the `g_ether` descriptors.

## Sony Camera Implication

The Mac-proven cable/camera retest below completed that check: the same Pi/cable setup enumerated
against macOS, then failed against the Sony. Sony documents the camera side as using a commercial
USB-LAN adapter, and the camera did not accept the Pi gadget as one. Treat direct Pi USB gadget
camera FTP as unsupported for v1. Use Bridge Wi-Fi FTP, or optional Same Wi-Fi advanced FTP.

## Live Sony Gadget Experiment

On 2026-05-22 at 22:55-22:57 EDT, the Pi was tested live against the camera while
the camera was in `USB-LAN Connection` / ready-for-connection state.

The following gadget personalities were tried with
`instantlink-bridge-usb-gadget-mode`:

- `g_ether`
- ConfigFS `ncm`
- ConfigFS `ecm`
- ConfigFS `rndis`
- ConfigFS `ecm-rndis`
- ConfigFS `ecm-realtek` using VID/PID `0x0bda:0x8153`
- ConfigFS `ncm-realtek` using VID/PID `0x0bda:0x8153`
- ConfigFS `ncm-asix` using VID/PID `0x0b95:0x1790`

Every mode stayed at:

```text
UDC state=not attached
usb0 carrier=0
usb0 operstate=down
```

No fresh DHCP lease appeared on `192.168.7.0/24`, and no wired FTP session was
opened. During the same period, the camera did open FTP sessions from
`192.168.5.209`, which confirms it was still able to reach the bridge over
Wi-Fi/peer networking while direct USB-LAN remained unattached.

Interpretation: this failure is below IP, DHCP, and FTP. It is also below the
specific Ethernet function choice, because the Pi UDC never left `not attached`.
The next useful tests are physical/role tests: VBUS/attach measurement from the
camera in USB-LAN mode, validation with a real USB-C Ethernet adapter, and then
a possible hardware redesign around real Ethernet if the camera only supports
adapter chipsets instead of USB gadget networking.

## Mac-Proven Cable, Camera Re-Test

On 2026-05-22 at 23:13 EDT, the same cable chain was attached to a Mac:

- macOS showed `InstantLink Bridge Ethernet` on `en10`.
- macOS received `192.168.7.10`.
- Pi `usb0` became `UP` with `carrier=1`.
- Pi UDC state became `configured`.
- Ping to `192.168.7.1` worked.
- A manual TCP check against FTP port 21 succeeded.

The camera was then connected with the same physical cable path. The camera did
not show the Pi as a valid USB-LAN connection and no FTP transfer occurred. The
FTP session logged at `23:14:08` from `192.168.7.10` was the Mac `nc` port check,
not the camera.

After re-running the gadget-mode sweep with the camera connected, every tested
mode reported:

```text
UDC state=not attached
usb0 carrier=0
0 packets captured on usb0
```

Conclusion: the cable, Pi data port, `dwc2`, `g_ether`, `dnsmasq`, and FTP
listener are good with a normal USB host. The Sony camera still does not accept
the Pi Zero USB gadget as a USB-LAN adapter. Treat direct micro-USB-to-camera
USB-C wired FTP as unsupported until a lower-level USB emulation approach is
proven against a known Sony-supported USB Ethernet adapter.

## Product Policy

InstantLink Bridge v1 should default camera setup to Bridge Wi-Fi FTP at `192.168.8.1`. Same Wi-Fi
advanced FTP is optional for same-Wi-Fi networks. The USB gadget network at `192.168.7.1` is for
admin, SSH, firmware update, and diagnostics only; `usb0` carrier must not make the UI or docs
present direct Sony wired FTP as supported.
