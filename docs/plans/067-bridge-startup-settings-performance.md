# 067 — Bridge startup, Settings and resource audit

Date: 2026-10-11. Scope: Bridge runtime, shared physical/virtual LCD and manager listeners.

## Changes

- Start UI and FTP independently of BlueZ. Gate Printer work on Bluetooth readiness, defer
  keepalive/FFI loading and optional Sync construction until core readiness, and track startup
  tasks through cancellation/failure. Health probing and metadata reads run off the UI loop.
- Keep user navigation open during startup and status updates; exiting Settings uses current
  cached home. Help opened during startup resolves current readiness when dismissed.
- Print Settings presents Post, Image fit, Confirmation and Printer, with Image quality and
  Printer options under Advanced. Ordinary helper paragraphs move to KEY3 Help. Read-only rows
  show their complete values in Help; long credentials wrap at all text sizes. About says
  Bridge version. Post still contains independent Looks and Correction; KEY3 opens Post.
- Probe both interface addresses in one subprocess per health/discovery refresh. Bonjour
  address probing runs off the event loop and reuses a snapshot during late registration.
- Cancel/timeout image preparation cleans up its isolated process group, including external
  HEIF decoders and descendants whose worker parent already exited. No image rules change.
- Retry a missing manager address while serving the working listener; remove failed sites
  before retry. Preserve exact address binds, USB authentication and shutdown responsiveness.

Awake/preparing/printing CPU remains at the supported 1000 MHz maximum. Locked idle remains
600 MHz. Radios, recovery cadence, review default (1 second), APIs and native artifacts stay
unchanged. Existing Printer idle auto-off cannot be prevented by status keepalive; the Bridge
reconnects when it is powered on again. No film is used by this audit.

## Baseline and validation

Controlled reboot of deployed `4574aa9`: kernel 2.635 s + userspace 14.313 s = 16.948 s systemd
startup. Core ready 16.146 s, FTP 13.964 s, hotspot receive-ready 18.625 s, manager USB 19.131 s.
The Printer was powered on later, so its baseline first status is excluded from boot comparisons.
These are kernel-monotonic reboot timings, excluding firmware and power-button latency.

Local validation and post-deploy measurements are recorded below. The Settings
contact sheet is at `../assets/bridge-audit-067/settings.png`. This audit does not establish a
16-hour battery runtime; X306 has no host current or fuel gauge. A controlled discharge remains
required. Physical button actuation, a new Sony upload and film colour/throughput remain separate
hardware acceptance checks.

## Local validation

**1,369 Bridge tests** passed, including startup sequencing/failure/cancellation, late Help
readiness, Settings navigation, read-only Help/credential wrapping, address refresh
responsiveness, EXIF responsiveness and real process-group descendant cleanup. Ruff, touched-file
formatting, strict mypy (65 source files), shell syntax, whitespace and strict MkDocs passed.
Normal pre-commit gates passed for both runtime commits. No App/iOS/API/schema/FFI changes require
cross-surface updates in this audit. Before/after Settings frames were visually inspected.

## Hardware observations

Clean runtime `50d2ec6` was deployed, followed by `8eb962d` to cap missing manager listener retry
at 10 seconds after a live trial exposed unnecessary latency with the initial 30-second cap.
Source deployment preserved native artifacts and dependencies. Hardware/OS are Pi Zero 2 W
Rev 1.0 / Waveshare ST7789 / X306 2300 mAh, Debian 13.2, kernel 6.12.47+rpt-rpi-v8,
Python 3.13.5, BlueZ 5.82, Bridge 0.1.17, saved Instax Square INSTAX-52006924 and Sony a7C II
camera profile. No new camera upload or film print was performed.

First post-change reboot: UI frame 14.536 s, core readiness 14.551 s, FTP 14.204 s,
Bluetooth agent 14.617 s, hotspot receive-ready 18.889 s and manager USB 19.435 s.
Splash finished 9.864 s, before the first app frame. Systemd total was 17.178 s; this is
not a material whole-system improvement over 16.948 s. Core readiness improved 1.594 s.
Hotspot activation and Python startup remain practical constraints; the 7-second target is
not met. Timings measure each subsystem separately and do not equate agent/core readiness
with a connected Printer.

A live hotspot-loss trial restarted only the manager with the hotspot address absent.
USB responded after its normal startup; the Bridge restored hotspot readiness about 33 s
from fault injection. The manager rebound automatically without another restart, but its
initial 30-second retry cap delayed HTTP availability to 54.00 s. This led to the 10-second cap.
Bridge PID and post-restart manager PID were unchanged throughout recovery; screen-off idle
was 600 MHz with GPIO24 low.

Comparable 35-second dark-idle samples (Printer absent, one offline scan, 600 MHz): Bridge
process CPU 9.31% → 9.46% of one core, manager 0%, RSS 69,320 → 68,448 KiB. Board busy
7.30% → 3.40% varies with other activity and is not attributed to this change. There is no
measured Bridge idle CPU reduction or battery-duration gain. Deterministic improvements are
fewer network subprocesses, responsive UI and decoder cleanup. See the sanitized measurements
at `../assets/bridge-audit-067/measurements.json`.

Second reboot at final runtime `8eb962d`: UI 14.324 s, core readiness **14.340 s**, FTP
13.995 s, Bluetooth agent 14.403 s, hotspot receive-ready **18.685 s**, manager USB 19.229 s,
splash complete 9.808 s. Systemd total **16.924 s** (2.614 s kernel + 14.310 s userspace).
The two post-change core-readiness trials improved **1.59–1.81 seconds** against the same
hardware baseline. FTP, hotspot and total startup remain effectively unchanged. Neither
post-change boot had a powered-on advertising Printer, so a boot-to-Printer measurement cannot
be claimed; a fresh power-on was requested after its documented idle shutdown.

Final late-address trial with the 10-second cap: both manager endpoints returned HTTP 200
**42.91 s** after fault injection. Bridge PID and manager PID remained unchanged after the
intentional manager restart; final CPU was 600 MHz and backlight GPIO24 low. Hotspot FTP
220 greeting and NOOP/200 passed. Bridge and manager were active with NRestarts=0,
`vcgencmd get_throttled` was 0x0, and deployment metadata reported clean `8eb962d`.
Temporary probes lived in `/tmp`; no service wrapper, drop-in or configuration change remained.
Printer connection continuity was not part of these final trials because it was not advertising.
