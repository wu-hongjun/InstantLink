# Boot-Time Budget

Design target: cold boot to print readiness in 7 s or less on Raspberry Pi Zero 2 W with X306
hardware power-on. This target has not been achieved on the current hardware.

## Budget

| Phase | Target |
| --- | ---: |
| Bootloader + kernel start | 1.5 s |
| Root filesystem + systemd basic target | 2.0 s |
| Bluetooth controller ready | 1.0 s |
| InstantLink Bridge service init | 1.0 s |
| BLE reconnect to bonded printer | 1.5 s |
| Total | 7.0 s |

## Concrete Boot Diet

Use committed repo artifacts for Pi boot changes. Do not hand-disable services on a target and leave
the recipe outside git. The conservative entry point is:

```bash
/opt/InstantLinkBridge/scripts/boot-diet.sh --report
sudo /opt/InstantLinkBridge/scripts/boot-diet.sh --apply
```

`--report` is the default and makes no changes. `--apply` is idempotent and only disables/stops
non-network, non-BLE background work:

| Unit | Action | Reason |
| --- | --- | --- |
| `NetworkManager-wait-online.service` | disable/stop | Removes online wait without disabling NetworkManager itself. |
| `apt-daily.timer` | disable/stop | Prevents package maintenance from stealing boot CPU/I/O. |
| `apt-daily-upgrade.timer` | disable/stop | Same as above; upgrades should be explicit maintenance actions. |
| `man-db.timer` | disable/stop | Defers manual page indexing. |
| `e2scrub_reap.service` | disable/stop | Defers ext4 scrub cleanup that is not product-critical at boot. |
| `apt-daily.service`, `apt-daily-upgrade.service`, `man-db.service` | stop only | Stops active maintenance spawned by timers; services may be static. |

Protected units are `NetworkManager.service`, `systemd-networkd.service`, `dnsmasq.service`,
`bluetooth.service`, `dbus.service`, and `instantlink-bridge.service`. The diet script refuses to include
those in its safe apply set so hotspot mode, peer Wi-Fi, USB gadget diagnostics, BLE reconnect, and
the UI/app path stay intact.

Report-only candidates still need device validation before any repo-backed apply path is added:

| Unit | Current recommendation |
| --- | --- |
| `tailscaled.service` | Keep for development/remote access; consider a production-only disable later if remote support is not required. |
| `hciuart.service` | Do not disable until BLE reconnect has passed repeated cold-boot tests on Pi Zero 2 W. |
| `ModemManager.service`, `cups.service`, `avahi-daemon.service`, `triggerhappy.service` | Disable only if installed and proven unused on the target image. |
| `dphys-swapfile.service` | Do not disable as a boot shortcut until memory headroom is measured under print and image-processing load. |
| `logrotate.timer` | Leave alone unless it appears in boot blame; it is not in the current critical path. |

## Current Target Measurement

Measured on the current target after the UI/backlight path work-in-progress, reported on
2026-05-21:

```text
Startup finished in 4.664s (kernel) + 23.731s (userspace) = 28.396s
bridge.ready around 16.8s monotonic
```

Known slow entries from that boot:

```text
NetworkManager.service  ~11.962s
tailscaled.service       ~3.709s
instantlink-bridge.service    ~3.474s
```

Observed service state:

- Before this pass, `instantlink-bridge-boot-splash.service` existed but was disabled on the target.
  Provisioning now installs and enables it so the LCD gets an early userspace frame.
- `e2scrub_reap.service` is enabled.
- Many earlier slow-service candidates are already disabled or not installed.

Previous baseline measured on one Pi Zero 2 W target on 2026-05-20:

```text
Startup finished in 5.609s (kernel) + 29.244s (userspace) = 34.854s
multi-user.target reached after 29.236s in userspace.
```

Critical path before the May 20 boot-order change:

```text
instantlink-bridge.service +6.180s
└─dnsmasq.service @22.100s +941ms
  └─network-online.target @22.080s
    └─network.target @22.078s
      └─NetworkManager.service @7.916s +14.158s
```

`instantlink-bridge.service` must not wait for NetworkManager, dnsmasq, systemd-networkd, or Bluetooth
before drawing the LCD. It should want those services so they start, but run concurrently and report
each subsystem as it becomes available. The current slow `NetworkManager.service` measurement is a
reason to keep it off the app critical path, not a reason to disable it; both hotspot provisioning
and peer Wi-Fi depend on NetworkManager.

Dedicated bridge images should also avoid unused camera/display probing and HDMI/KMS setup. The
tracked boot config sets `camera_auto_detect=0`, `display_auto_detect=0`, `auto_initramfs=0`, and
`max_framebuffers=1`, and removes `dtoverlay=vc4-kms-v3d` / `dtoverlay=vc4-fkms-v3d` during
provisioning.

Provisioning also installs `config/instantlink-bridge-unused-media.conf` under
`/etc/modprobe.d/`. It suppresses alias autoload for the unused legacy VCHI camera,
codec, ISP, shared-memory and audio leaf drivers: `bcm2835_v4l2`, `bcm2835_codec`,
`bcm2835_isp`, `vc_sm_cma` and `snd_bcm2835`. VCHI bus devices can advertise media
and audio drivers even with camera autodetection and firmware audio disabled; the
media drivers also pull in the shared-memory driver as a dependency. The Bridge
receives camera uploads over FTP and decodes JPEG/HIF with CPU libraries; its SPI
ST7789 framebuffer uses `fb_st7789v`/`fbtft`. Those paths retain their drivers.

This is an ordinary `blacklist` profile: explicit diagnostic `modprobe` calls and
dependencies can still load these modules. It does not unload an active driver.
Apply it at boot and verify the effective loader configuration and loaded modules
after reboot. `boot-diet.sh --report` reports the tracked file directives only.
For rollback, restore the previous copy of this one file (or remove it if it did
not exist before installation), then reboot. Existing users of local VCHI camera,
video or audio hardware should omit this appliance-specific profile.

## `/boot/firmware/config.txt` Tuning

```ini
camera_auto_detect=0
display_auto_detect=0
auto_initramfs=0
max_framebuffers=1
disable_splash=1
boot_delay=0
initial_turbo=30
gpu_mem=16
dtparam=audio=off
```

## `/boot/firmware/cmdline.txt` Tuning

Track the kernel cmdline through `boot/firmware/cmdline.example.txt`. The serial
console (`console=serial0,115200` + `enable_uart=1`) is intentionally disabled
for boot-speed; see `docs/plans/032`. `quiet loglevel=3 vt.global_cursor_default=0`
suppress kernel and console chatter during boot. `console=tty1` is retained so
the framebuffer console still produces output if needed.

## Measurement

Use:

```bash
systemd-analyze
systemd-analyze blame
systemd-analyze critical-chain
journalctl --boot -o short-monotonic
```

For reproducible before/after captures on a deployed target:

```bash
/opt/InstantLinkBridge/scripts/boot-diet.sh --report |
  sudo tee /opt/InstantLinkBridge/.deployment/boot-diet-before.txt >/dev/null
sudo /opt/InstantLinkBridge/scripts/boot-diet.sh --apply |
  sudo tee /opt/InstantLinkBridge/.deployment/boot-diet-apply.txt >/dev/null
sudo reboot
/opt/InstantLinkBridge/scripts/boot-diet.sh --report |
  sudo tee /opt/InstantLinkBridge/.deployment/boot-diet-after.txt >/dev/null
```

Run the script from a clean deployed commit. `scripts/deploy-to-pi.sh` records the commit SHA and
dirty flag in the deployment manifest, so the boot-diet recipe is tied back to git instead of being
an undocumented target mutation.

Add application milestones through structured logs:

- `bridge.boot.start`
- `bridge.ftp.ready` (listener bound; not proof of an active camera receive path)
- `bridge.bluetooth.ready` (agent initialized; not Printer connection)
- `bridge.ui.ready`
- `bridge.ready`

`bridge.boot.start` follows Python imports. `bridge.ui.ready` confirms the initial LCD draw;
`bridge.ready` confirms UI and FTP initialization for systemd. Bluetooth, Printer status, hotspot
address and Sync readiness are separate. Plan 067 moves Bluetooth registration, Printer
keepalive, health probing and optional Sync construction off the UI/FTP critical path.
Plan 068 additionally starts CPU helper I/O, FTP setup and Bluetooth registration together;
the first UI/input and core READY still wait for the maximum awake CPU tier.

The product metric is time from X306 button press to the LCD showing Ready with healthy FTP and
Printer status. Kernel-monotonic reboot measurements exclude power-button/firmware latency.
The 2026-10-11 controlled baseline at runtime `4574aa9` reached core readiness at 16.146 s,
FTP at 13.964 s, hotspot receive readiness at 18.625 s and manager listeners at 19.131 s.
See plan 067 for the post-change hardware comparison; the older May measurements below are
historical observations, not the baseline for this audit.

## Earliest LCD Output

The Waveshare 1.3" LCD HAT is an SPI display, so Raspberry Pi firmware cannot show the HDMI-style
rainbow splash or bootloader UI on it. To avoid a blank screen, configure the ST7789 as a kernel
framebuffer using the tracked boot fragment at `boot/firmware/config.txt`:

```ini
dtoverlay=fbtft,spi0-0,st7789v,width=240,height=240,dc_pin=25,reset_pin=27,led_pin=24,rotate=270,speed=40000000,fps=30
```

This creates a `/dev/fb*` device named `fb_st7789v`; on the current target it appears as `/dev/fb1`.
The main InstantLink Bridge UI detects that framebuffer and draws to it directly.

Install and enable from the repo on a Pi image:

```bash
sudo scripts/provision-sd.sh /
```

`systemd/instantlink-bridge-boot-splash.service` is also installed and enabled by provisioning. It runs
as early userspace, explicitly wakes the framebuffer backlight, draws the boot frame, and then exits
before the main UI takes over.

## Steps To Defer

Wait until the display/backlight path is validated on the target before integrating the boot diet
script into provisioning:

- Do not disable `hciuart.service` until BLE reconnect to the bonded printer passes repeated cold
  boots.
- Do not tune or disable NetworkManager beyond `NetworkManager-wait-online.service` until hotspot
  mode and peer Wi-Fi are acceptance-tested after each change.
- Decide whether `tailscaled.service` is development-only or production-required before adding it to
  any apply-mode diet.
