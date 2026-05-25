# USB Gadget Experiments

The provisioned InstantLink Bridge default uses Raspberry Pi `g_ether`. That path
enumerates on macOS, but the Sony camera has not attached to it in USB-LAN mode:
the Pi remains at `UDC state=not attached` and `usb0 carrier=0`.

This file records the controlled experiment path that led to declaring direct Sony USB-LAN
unsupported for v1. The USB gadget remains useful for admin, SSH, and diagnostics with a normal
computer host.

## Experiment Tool

Install or run:

```bash
sudo scripts/usb-gadget-mode.sh status
sudo scripts/usb-gadget-mode.sh start ncm
scripts/usb-gadget-mode.sh watch 30
sudo scripts/usb-gadget-mode.sh reset-g-ether
```

Provisioning installs the same tool as:

```bash
sudo instantlink-bridge-usb-gadget-mode status
```

The tool is non-persistent. Rebooting or running `reset-g-ether` returns the Pi
to the normal `g_ether` setup from `/etc/modprobe.d/g_ether.conf`.

## Historical Modes Tried

These modes were tried one at a time while the camera was on:

```bash
sudo instantlink-bridge-usb-gadget-mode start ecm
sudo instantlink-bridge-usb-gadget-mode start ncm
sudo instantlink-bridge-usb-gadget-mode start rndis
sudo instantlink-bridge-usb-gadget-mode start ecm-rndis
sudo instantlink-bridge-usb-gadget-mode start ecm-realtek
sudo instantlink-bridge-usb-gadget-mode start ncm-realtek
sudo instantlink-bridge-usb-gadget-mode start ncm-asix
```

For each mode, the experiment used this procedure:

1. Put the camera in `USB-LAN Connection`.
2. Replug the test cable into the Pi Zero `USB` data port.
3. Run `instantlink-bridge-usb-gadget-mode watch 30`.
4. Record whether the UDC state changes from `not attached`, whether `usb0`
   carrier becomes `1`, and whether `dnsmasq` issues `192.168.7.10`.

## How To Interpret Results

If every mode stays at:

```text
UDC state=not attached
usb0 carrier=0
```

then the blocker is lower than USB Ethernet descriptors. Focus on USB-C role,
VBUS/attach signaling, cable wiring, and whether the camera actually sources
host attach in USB-LAN mode.

If a mode reaches `attached`, `powered`, `default`, `addressed`, or
`configured`, the camera is electrically seeing the Pi. At that point inspect
kernel logs and tune descriptors, class, VID/PID, or DHCP.

If `usb0 carrier=1` but no lease appears, the USB layer worked and the blocker
is network configuration. Check `dnsmasq`, camera IP mode, and the camera FTP
server profile.

## Notes

- `ecm` tests CDC-ECM.
- `ncm` tests CDC-NCM, which is the most plausible class-mode alternative to
  `g_ether`.
- `rndis` is mostly useful as a negative control for PC-style tethering.
- `ecm-realtek` and `ncm-realtek` spoof Realtek RTL8153 VID/PID while still
  exposing class Ethernet functions. This cannot emulate the Realtek vendor
  protocol, but it helps test whether the camera is only gating on VID/PID
  before class binding.
- `ncm-asix` is a similar spoof for an ASIX-style adapter family.

## 2026-05-22 Camera Result

Against the Sony camera in `USB-LAN Connection` mode, all listed modes remained:

```text
UDC state=not attached
usb0 carrier=0
usb0 operstate=down
```

This means the camera did not enumerate the Pi gadget in any tested personality.
The later Mac-proven cable/camera retest confirmed the same cable and Pi gadget
worked with macOS but not with the Sony camera. Do not use direct Pi USB gadget
FTP as a v1 camera mode; continue direct-USB work only as a future
hardware/compatibility investigation.
