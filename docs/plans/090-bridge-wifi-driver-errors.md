# Bridge Wi-Fi driver errors and hotspot continuity

## Goal and scope

Investigate the remaining `brcmf_vif_set_mgmt_ie: vndr ie set error : -52` records,
remove avoidable hotspot disruption, and preserve camera FTP and automatic Printer reconnect.
Baseline source is `3230a5c`, with runtime `4145e77` installed. Use no film or image/actuator
commands on the Printer. Independent agents cover driver sources, runtime/helper lifecycle,
benchmark isolation and adversarial review. Root owns all Pi mutations.

Hardware: Pi Zero 2 W Rev 1.0, BCM43430/1 Wi-Fi firmware 7.45.96.s1 (June 14, 2023,
FWID 01-70bd2af7 es7), Debian 13.2, kernel 6.12.47+rpt-rpi-v8, NetworkManager 1.52.1,
wpa_supplicant 2.10, BlueZ 5.82. Printer: INSTAX-52006924, Link Square. GPIO/LCD and native
FFI/CLI remain the previously verified configuration. Kernel BRCM tracing is not enabled.

## Driver evidence

- The driver maps any negative firmware reply to Linux `-EBADE` (52); this message cannot
  identify the specific firmware rejection. [Raspberry Pi fwil.c](https://raw.githubusercontent.com/raspberrypi/linux/stable_20250916/drivers/net/wireless/broadcom/brcm80211/brcmfmac/fwil.c).
- AP teardown resets firmware before clearing cached management IEs. Vendor parsing excludes
  WPA/WME IEs. The paired errors fit that cleanup sequence; exact firmware cause remains an
  inference, without a firmware-error/OUI trace. [Raspberry Pi cfg80211.c](https://raw.githubusercontent.com/raspberrypi/linux/stable_20250916/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c).
- NetworkManager translates disabled WPS into `wps_disabled=1`. Supplicant normally enables
  WPS for WPA2-Personal APs unless disabled. Existing WPA2-PSK authentication can remain while
  unused enrollment advertisement is disabled. [NetworkManager 1.52.1](https://raw.githubusercontent.com/NetworkManager/NetworkManager/1.52.1/src/core/supplicant/nm-supplicant-config.c),
  [wpa_supplicant 2.10 source archive](https://w1.fi/releases/wpa_supplicant-2.10.tar.gz).

## Application findings and design

Every Bridge startup applies the saved FTP mode. The old hotspot helper modifies the profile
and activates it even when the correct AP is already healthy. NetworkManager logs show
`new-activation`, AP-DISABLED/AP-ENABLED, address loss and dnsmasq restart. These correlate with
the paired kernel errors. Runtime recovery already has generation/job guards; a Python-only
skip based on an IP address would ignore configuration drift.

The helper should retain an AP only after checking exact selected UUID, desired saved and
applied settings, live address, NetworkManager owner, activation identity and applied version.
Applied settings omit secrets, so a root-private per-boot stamp must bind the desired PSK digest
to a successful helper activation. Unknown/untrusted/malformed state or failed probes must use
the existing activation/recovery path. Root helper mutations are serialized. Keep radio-off,
home transitions, missing-interface driver recovery, SSID/PIN/channel reconciliation and
cancellation operational. Disable WPS while retaining the same WPA2-PSK/RSN/CCMP settings.

The independent review identified cancellation ownership lost through a foreground pipeline.
Direct stdin redirection keeps the owned child in the main shell. The audit also found that
background commands without explicit stdin inheritance read `/dev/null`, affecting activation
stamping and newly generated PIN writes. Validate these with actual Bash/worker/lock tests;
mocked command results alone cannot establish shell process ownership.

## Baseline and controlled WPS experiment

An initial isolated 32 MiB × four-file fixture exhausted the Pi's `/tmp` tmpfs and could not
write its report. Its temporary inputs were cleaned; no production storage fault or result is
claimed. The corrected fixture uses SD-backed `/var/tmp`, storage preflight, streaming checksums
and reporting after cleanup.

A separate instance of the installed FTP receiver accepts synthetic 8 MiB JPEG transport files
on an alternate port/private root with a checksum-only queue consumer. It cannot dispatch a
production print. One unpaced and three paced uploads overlap repeated hotspot calls. This
same-Pi hotspot-address path exercises receiver/SD/service behavior, **not wireless airtime**.
Pacing is included in the continuity timing and must not be called camera throughput. Production
FTP greeting/NOOP probes run alongside NetworkManager, USB, service and BlueZ observations.

| Phase | Three helper times, median | Errors per call | Production FTP probe failures | Upload checksums |
| --- | --- | --- | --- | --- |
| Original helper, default WPS | 3.742 s | 2 / 2 / 2 | 9 | Four pass |
| Original helper, disabled WPS | 3.744 s | 2 / 0 / 0 | 9 | Four pass |

The first disabled-WPS call tears down the previously advertised WPS AP; subsequent actual
reactivations produced no vendor-IE error. This is a measured configuration improvement,
not a kernel patch or decoded firmware error. Reactivation still interrupts FTP probes, so
WPS alone does not resolve continuity. All four transfers in each corrected phase completed
with identical checksums. Unpaced single-transfer timings are retained but are not a radio
throughput comparison. Sampling commands are serial; maximum sample spans were about 0.45 s,
so no 250 ms gap-detection claim is made.

The Printer stopped advertising at 07:50:18, before the first fixture began at 07:52:49.
These early phases do not establish connected Printer retention. The user has powered it on
again for the final locked/status-only acceptance checks. Evidence is retained under
`docs/assets/bridge-audit-090/`; raw logs and credentials remain private.


## Reviewed candidate

The final helper SHA is `736cf4ba661859b16e8f9ebf49cdd289bca7e062b33e91957a6ff925572afed2`.
Independent review cleared 76 targeted tests, including eight actual Bash cancellation/lock
cases and additional PIN creation/preservation/override/permission checks. The implementation
agent passed 110 affected tests. PSK preparation now owns its commands in the main shell;
value retrieval is read-only. The review record retains both cancellation findings/resolutions.

The first unknown-stamp apply took 6.079 s, including verification; this is not boot timing.
Three verified repeat calls had median **2.187 s**, retained one activation object path,
produced **zero vendor-IE errors and zero production FTP probe failures**. All four 8 MiB
uploads completed/checksummed. All 45 samples kept the Printer connected with fresh status,
film 0, camera readiness true, screen locked and board 600 MHz, with no retired status task.
Maximum serial monitor span was 0.407 s. Paced transfers took about 7.86 s instead of 9.35 s
under AP reactivation; the deliberate pace and local address path preclude radio speed claims.
The unpaced single-transfer result (50.54 MiB/s versus baseline 50.11) does not establish a
throughput change. Deployment and final recovery acceptance follow after clean commit gates.
