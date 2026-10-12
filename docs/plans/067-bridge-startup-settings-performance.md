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

Local validation and post-deploy measurements are recorded below after deployment. The Settings
contact sheet is at `../assets/bridge-audit-067/settings.png`. This audit does not establish a
16-hour battery runtime; X306 has no host current or fuel gauge. A controlled discharge remains
required. Physical button actuation, a new Sony upload and film colour/throughput remain separate
hardware acceptance checks.
