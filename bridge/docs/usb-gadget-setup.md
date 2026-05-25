# USB Gadget Setup

The Pi USB gadget network is retained for admin, SSH, firmware update, and diagnostics. It is not a
supported v1 camera wired mode. v1 camera FTP should use the bridge hotspot first, with Same Wi-Fi
advanced FTP as the optional path.

## Compatibility Status

Sony documents a7C II USB-LAN as using a commercially available USB-LAN
conversion adapter attached to the camera. The direct Pi `g_ether` gadget path
has been tested and is unsupported for v1.

On 2026-05-22, the same cable chain and Pi gadget enumerated successfully on
macOS as `InstantLink Bridge Ethernet`, received a `192.168.7.10` lease, and passed
ping plus an FTP port check. Connected to the Sony a7C II immediately
afterward, the Pi remained at `UDC state=not attached` with no `usb0` carrier
and no camera FTP session. A sweep of `g_ether`, ECM, NCM, RNDIS, and
descriptor-spoof variants produced the same result.

Policy:

1. Use Bridge Wi-Fi FTP at `192.168.8.1` for v1 camera operation.
2. Use Same Wi-Fi advanced FTP on an existing same-Wi-Fi network only when that workflow is
   explicitly configured.
3. Use `usb0` at `192.168.7.1` only for admin, SSH, and diagnostics from a normal computer host.
4. Reopen direct camera wired work only for a future hardware/USB compatibility investigation.

The controlled test procedure lives in
[usb-gadget-experiments.md](usb-gadget-experiments.md). It uses
`instantlink-bridge-usb-gadget-mode` to switch between `g_ether`, ConfigFS ECM, NCM,
RNDIS, and descriptor spoof variants without making the experiment permanent.

Diagnostic USB network:

- Pi `usb0`: `192.168.7.1/24`
- Admin host DHCP lease: `192.168.7.10`
- Optional diagnostic FTP/SSH target: `192.168.7.1`

This USB subnet is intentionally separate from the Wi-Fi FTP address. Do not
reserve a Wi-Fi address inside `192.168.7.0/24` while `usb0` uses
`192.168.7.1/24`; `192.168.7.2` looks convenient, but it overlaps the USB
diagnostic link and can create ambiguous routes or ARP replies. For the current home
LAN, prefer a router reservation such as `192.168.5.7` instead.

The preferred Wi-Fi address is configuration, not application code:

```toml
[ftp]
hotspot_host = "192.168.8.1"
preferred_wifi_host = "192.168.5.7"
```

The LCD always shows the actual assigned Wi-Fi address. If it differs from the
preferred address, the Wi-Fi line is highlighted so the router reservation can
be fixed without lying about where FTP is reachable.

See [wifi-ftp-modes.md](wifi-ftp-modes.md) for the Bridge Wi-Fi and Same Wi-Fi advanced setup
commands.

## `/boot/firmware/config.txt`

Append:

```ini
dtoverlay=dwc2,dr_mode=peripheral
```

`dr_mode=peripheral` forces the Pi Zero 2 W USB controller to act as the USB
device for the admin/diagnostic link.

Boot-time tuning may also add:

```ini
disable_splash=1
boot_delay=0
initial_turbo=30
gpu_mem=16
dtparam=audio=off
```

## `/boot/firmware/cmdline.txt`

`cmdline.txt` must remain a single line. Add `modules-load=dwc2,g_ether` after `rootwait` or another existing token:

```text
modules-load=dwc2,g_ether
```

Do not insert a newline.

## `/etc/modprobe.d/g_ether.conf`

Pin stable MAC addresses so the camera does not see a new adapter every boot:

```conf
options g_ether host_addr=02:1a:57:00:00:01 dev_addr=02:1a:57:00:00:02 idVendor=0x1d6b idProduct=0x0104 iManufacturer=InstantLink Bridge iProduct="InstantLink Bridge Ethernet" iSerialNumber=InstantLink Bridge
```

The descriptor strings make the host show a recognizable USB Ethernet device
instead of a generic Linux gadget name.

## `/etc/systemd/network/10-usb0.network`

Use systemd-networkd for the deterministic USB diagnostic link:

```ini
[Match]
Name=usb0

[Network]
ConfigureWithoutCarrier=yes
Address=192.168.7.1/24
DHCPServer=no
LinkLocalAddressing=no
IPv6AcceptRA=no

[Link]
RequiredForOnline=no
```

Enable systemd-networkd for this interface during provisioning. If NetworkManager is active globally, mark `usb0` unmanaged there so it does not race networkd.

## `/etc/dnsmasq.d/instax.conf`

```conf
interface=usb0
bind-interfaces
dhcp-range=192.168.7.10,192.168.7.10,255.255.255.0,12h
dhcp-option=3
dhcp-option=6
log-dhcp
```

`dhcp-option=3` and `dhcp-option=6` intentionally advertise no router or DNS server for the camera link.

## Cable Events

Future udev rules should detect `usb0` link changes and emit diagnostic service events. USB gadget
attach or removal must not gate v1 camera readiness because camera FTP is hotspot-first.

## Physical Connection Checklist

The Pi Zero 2 W has two micro-USB ports. For the USB gadget diagnostic link, plug the computer cable
into the Pi port labeled `USB`, not the port labeled `PWR IN`.
Keep the Pi independently powered by the X306 USB-C/input path, a bench supply, or the Pi `PWR IN`
port.

Use a USB-C to micro-USB data cable with D+, D-, ground, and a usable VBUS
presence signal. The Pi remains independently powered by X306 or another external source, but the OTG
controller still needs to detect a host attach. A charge-only cable, a fully
VBUS-isolated cable, or a cable plugged into the Pi `PWR IN` port will leave the
gadget controller unattached.

For diagnostics, test with a known-good normal data cable into a Mac or PC.
The Mac/PC should enumerate a USB Ethernet/RNDIS/ECM device and the Pi UDC state
should stop saying `not attached`.

The Pi-side expected transition is:

- Before the host/cable is attached: `usb0` shows `NO-CARRIER` and the UDC
  state is `not attached`.
- After the host enumerates the Pi gadget: the UDC state should leave
  `not attached`, `usb0` should become carrier-up, and `dnsmasq` should log a
  DHCP lease for `192.168.7.10`.

If a Mac/PC test does not enumerate and the Pi still reports
`UDC state=not attached`, debug the physical link first: wrong Pi port, no data
lines, no VBUS attach signal, cable orientation/adapter issue, or no common
ground.

If a Mac/PC enumerates but the Sony camera does not, that matches the 2026-05-22 retest. Do not
spend v1 setup time trying to make direct camera USB-LAN work; use Bridge Wi-Fi FTP or Same Wi-Fi
advanced FTP.

Provisioning enables persistent systemd journals with
`/etc/systemd/journald.conf.d/99-instantlink-bridge-persistent.conf` and creates
`/var/log/journal`. This is required for diagnosing cable-induced resets after
the Pi reboots. The `99-` prefix is intentional because Raspberry Pi OS ships a
lower-priority `40-rpi-volatile-storage.conf` drop-in.

## Validation Commands

These commands are documentation only for now:

```bash
ip addr show usb0
cat /sys/class/udc/*/state
journalctl -u systemd-networkd -u dnsmasq --boot
journalctl -b -1 -k | grep -Ei 'usb|dwc|g_ether|under.?voltage|power|reset'
journalctl -b -1 -u instantlink-bridge.service
sudo tcpdump -i usb0 port 67 or port 68 or port 21
```
