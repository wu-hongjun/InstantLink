# 058 — Bridge awake and printing performance

## User report and required behavior

On 2026-09-30 the user reported that portable use works well, but printing feels slower than
before. The Bridge must use maximum stock CPU performance whenever awake, and during a photo
job even if the LCD remains locked. The 16-hour battery target from plan 057 remains open.

## Audit findings

- Plan 057 did not change the CPU governor, clock limits, voltage, image pipeline, image quality,
  prepared-preview reuse, or BLE packet pacing. The last verified governor was `ondemand` with
  a 600–1000 MHz range. This is dynamic scaling, with the stock maximum still available.
- Offline Printer searches changed from 5 to 30 seconds. That can extend the wait after turning
  on the Printer. Connected keepalive remains 10 seconds. Dark-screen network status polling
  changed from 1 to 5 seconds; FTP receives remain event-driven.
- The prior real Sony a7C II HIF → Instax Square measurement (2026-08-04) recorded 7.56 seconds
  upload, about 1.85 seconds preview preparation, a configured 5-second confirmation countdown,
  and 24.03 seconds sending/printing. The live saved countdown was already 5 seconds before the
  battery session. It should be checked again rather than assumed to explain the new report.
- USB access was unavailable at the start of this audit: the Mac had no `en8` interface or
  enumerated Raspberry Pi USB gadget; the saved hostname did not resolve. A new live clock,
  temperature, throttling, config, FFI-artifact, and print-log audit is pending data-port access.
  No cause for the slowdown has been confirmed.

## Implementation

| Bridge state | CPU policy |
|---|---|
| Boot, awake LCD, dim LCD | `performance`: requests current stock maximum |
| Manually locked or automatically dark, no photo job | `ondemand`: scales with work |
| Preparing, reviewing/editing, sending or printing a photo | `performance`, including locked LCD |
| Photo job ends or fails | Return to the current screen policy |
| Orderly Bridge shutdown | Restore `ondemand` |

`power/performance.py` owns the policy and helper calls. The physical and virtual LCD use the
existing shared idle transitions. `app.py` holds a boost across the complete photo dispatch,
including preview preparation and confirmation, and releases it on exceptions or cancellation.
An in-flight idle transition reconciles a subsequent wake so it cannot leave the wrong governor.
Helper failures are logged once per failure sequence and do not abort a photo job.

The helper is installed root-owned at `/usr/local/sbin/instantlink-bridge-cpu-mode`. Its sudo rule
allows only `performance` and `ondemand`. It changes no clock or voltage limit and leaves firmware
thermal and undervoltage protection active. Provisioning installs the helper and sudo rule;
source-only deployment to an existing unit must install those two files before restarting.

Linux documents the behavior of both governors in
[CPU performance scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html).
Holding maximum frequency while awake can increase battery draw. No speed or runtime benefit
is claimed until the updated behavior is measured on the device.

## Validation and remaining hardware checks

- Local Bridge suite: 1126 tests passed; Ruff and strict mypy passed. Shell syntax checks passed.
- Policy tests cover lock/wake/dim/automatic screen-off, a wake during an idle helper call,
  nested photo boosts, job failure/cancellation, and helper failure without interrupting a photo job.
- Pending on Pi Zero 2 W / Debian 13: inspect clock limits and boot config; compare governor,
  actual clock and throttling flags awake/locked/during preparation; verify helper ownership and
  constrained sudo access; verify no service restarts or errors.
- Pending camera/Printer timing: collect recent and repeat Sony a7C II → Instax Square stages
  without initiating a film-consuming print remotely. Check `source=preview` reuse, preparation
  time, payload bytes, transfer time, countdown, reconnect delay and power/thermal flags.
- Repeat the battery test with the new awake policy and a realistic workload. Plan 057's overnight
  idle estimate does not establish 16-hour use with this policy.
