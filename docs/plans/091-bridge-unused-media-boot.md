# Unused GPU/media boot modules

## Goal and boundaries

Remove the remaining legacy VideoCore media initialization failures, preserve the SPI LCD,
camera FTP/HIF handling and automatic Printer reconnect, and measure normal boot milestones.
No film or Printer image/actuator commands. Three independent agents cover pinned driver/loader
sources, implementation and adversarial review. Root performs hardware changes.

Baseline application source: `966b316`; native source `b2b6c8c` and the reviewed Wi-Fi AP
cleanup backport remain unchanged. Pi Zero 2 W Rev 1.0, ST7789 240 × 240, X306 2300 mAh,
Debian 13.2, kernel 6.12.47+rpt-rpi-v8, BlueZ 5.82, Python 3.13.5; Printer Link Square
INSTAX-52006924. Current boot uses `gpu_mem=16`, camera/display autodetect disabled,
no KMS overlay, `auto_initramfs=0`. Camera inputs are external uploads, not a CSI sensor.

## Cause and candidate

The pinned [VCHIQ driver](https://raw.githubusercontent.com/raspberrypi/linux/359f37f0faefb712add32a39f98751aea67d5c1f/drivers/staging/vc04_services/interface/vchiq_arm/vchiq_arm.c)
registers legacy camera/codec/ISP/audio/shared-memory children without firmware service discovery.
The [16 MB firmware profile](https://www.raspberrypi.com/documentation/computers/config_txt.html#start_file-fixup_file)
uses cut-down firmware. Udev coldplug therefore attempts unused legacy drivers whose services
are unavailable, producing VCHI/shared-memory/MMAL errors. They occur at about 8.4–8.6 seconds
in the retained baseline boot. No video or vcsm device survives; no detected vchiq consumer.

Use a tracked modprobe profile to blacklist alias loading of only `bcm2835_v4l2`,
`bcm2835_codec`, `bcm2835_isp`, `vc_sm_cma` and `snd_bcm2835`. Ordinary blacklists keep explicit
diagnostic loads available. Retain VCHIQ and shared media, DRM, framebuffer, SPI, Bluetooth and
Wi-Fi drivers. The ST7789 staging/SPI-ID messages concern essential LCD drivers and remain visible.

Provisioning installs the owned fragment; boot-diet reports file directives without claiming
active enforcement. Reboot is required; rollback restores the previous owned fragment or removes
it if initially absent. Do not alter GPU memory, boot overlays, camera/network credentials or
service ordering. Reassess alias/dependency/builtin changes when updating kernels.

## Validation design

- Two baseline and two candidate normal reboots with identical application/native source and
  instrumentation. Kernel-monotonic timestamps exclude power-button and firmware latency.
- Record first LCD/FTP/core readiness, hotspot and Bluetooth availability separately; systemd
  total time is not the product-ready metric. Printer-off results do not measure connected readiness.
- Dry-run effective modprobe alias blacklisting and essential hardware dependencies, with explicit
  media loads still allowed; verify actual module census and warnings after reboot and rollback.
- Compare HIF/JPEG preparation output and LCD data; isolated checksum-only FTP fixture cannot print.
- Final status-only Printer reconnect while locked, same-button unlock/timeout, normal services,
  source hashes, Wi-Fi backport and full available running/boot log review.

## Measured candidate

Two normal baseline reboots versus two candidate reboots, same application/native source:

| Kernel-monotonic readiness | Baseline median (range), s | Candidate median (range), s |
| --- | --- | --- |
| LCD UI | 13.815 (13.725–13.905) | 13.681 (13.543–13.819) |
| FTP | 13.781 (13.693–13.869) | 13.630 (13.530–13.730) |
| Hotspot receive ready | 20.005 (19.884–20.127) | 19.411 (19.088–19.734) |

These small samples overlap for LCD/FTP and do not establish a repeatable boot speedup.
Printer was available only in baseline1 (fresh status 20.029 s); other trials had no fresh
Printer status, so connected startup times cannot be compared. Software reboots exclude
firmware and physical power-on latency.

Both candidate boots removed all 17 modules in the unused media/audio dependency closure
(1,122,304 mapped module bytes in baseline), four VCHI service failures and four NULL video
unregister messages. This census is not a measurement of total RAM or battery savings.
Essential LCD, Wi-Fi, Bluetooth and USB dependencies remained unchanged. Effective loader
dry-runs passed all five leaf names/aliases and ten essential dependency cases; explicit
loads by real module name remain available. Independent adversarial source/loader review
passed with no outstanding source findings.

Retained DSC02821.HIF prepared for Mini, Square and Wide before/after: encoded JPEG and decoded
RGB hashes, dimensions, selected quality and transport orientation flags were identical.
Original identity/content preserved. This CPU fixture used no BLE/image commands or film.
