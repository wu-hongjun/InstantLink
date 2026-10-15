# 058 — Bridge awake and printing performance

## User report and required behavior

On 2026-09-30 the user reported that portable use works well, but printing feels slower than
before. The Bridge must use maximum stock CPU performance whenever awake, and during a photo
job even if the LCD remains locked. The 16-hour battery target from plan 057 remains open.
The user subsequently requested a fixed lowest-clock tier while locked, rather than automatic
scaling. The implementation now uses `powersave` in that tier.

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
  battery session. The new live audit confirmed it remains 5 seconds.
- USB access returned during the 2026-09-30 audit. `cpufreq-dt` controls cores 0–3 together,
  with supported frequencies 600/700/800/900/1000 MHz; the existing governor was `ondemand`,
  maximum 1000 MHz, no CPU quota, Nice 0, and `throttled=0x0`. Initial SoC temperature was 45.1 °C.
- Latest recorded real print, `DSC02697.HIF`, reused its preview: `source=preview`, 102303-byte
  JPEG, `prepare_ms=0`. Send/print took **24.837 seconds**, compared with the earlier 24.03
  seconds. Receive-complete → print-start took 6.679 seconds, including preview and confirmation.
  Upload took 11.835 seconds for an **11.26 MB** source, versus the earlier 7.56 seconds for a
  **5.19 MB** source. Total was about **43.35 seconds** versus 38.4 seconds previously. These are
  different images; the main observed increase is upload time, not duplicate preparation or a
  reduced CPU maximum. The Pi's historical timestamps are unreliable, so these are same-job
  intervals within its recorded boot.

## Implementation

| Bridge state | CPU policy |
|---|---|
| Boot, awake LCD, dim LCD | `performance`: requests current stock maximum |
| Manually locked or automatically dark, no photo job | `powersave`: fixed stock minimum (600 MHz on this Pi) |
| Preparing, reviewing/editing, sending or printing a photo | `performance`, including locked LCD |
| Photo job ends or fails | Return to the current screen policy |
| Bridge shutdown/crash | Restore `ondemand` (systemd stop hook covers abrupt process exits) |

`power/performance.py` owns the policy and helper calls. The physical and virtual LCD use the
existing shared idle transitions. `app.py` holds a boost across the complete photo dispatch,
including preview preparation and confirmation, and releases it on exceptions or cancellation.
An in-flight idle transition reconciles a subsequent wake so it cannot leave the wrong governor.
Helper failures are logged once per failure sequence and do not abort a photo job.

The helper is installed root-owned at `/usr/local/sbin/instantlink-bridge-cpu-mode`. Its sudo rule
allows only `performance`, `powersave`, and shutdown reset `ondemand`. It changes no clock or voltage limit and leaves firmware
thermal and undervoltage protection active. Provisioning installs the helper and sudo rule;
source-only deployment to an existing unit must install those two files before restarting.

Linux documents the behavior of these governors in
[CPU performance scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html).
Holding maximum frequency while awake can increase battery draw. Lock controls all four CPU
cores. GPU, RAM, Wi-Fi, Bluetooth, USB and peripheral clocks are separate domains; they retain
their supported operating configuration so camera receive and Printer reconnect stay functional.
No battery-runtime benefit is claimed until a controlled discharge test. The sampler now records
the CPU governor along with frequency so the tiers can be distinguished in subsequent runs.

## Validation and remaining hardware checks

- Local Bridge suite: 1126 tests passed; Ruff and strict mypy passed. Shell syntax checks passed.
- Policy tests cover lock/wake/dim/automatic screen-off, a wake during an idle helper call,
  nested photo boosts, job failure/cancellation, and helper failure without interrupting a photo job.
- Deployed source `892945a` through a clean archive on Pi Zero 2 W, Debian 13.2,
  kernel 6.12.47+rpt-rpi-v8, Bridge 0.1.17. Installed the CPU helper `root:root 0755` and sudo rule
  `root:root 0440`; `visudo` and `systemd-analyze verify` passed. Restart completed with
  `NRestarts=0`; startup logged maximum performance and `bridge.ready` without CPU-mode errors.
- On-device policy controller check: awake 1000 → locked 600 → locked photo job 1000 → job ends
  locked 600 → unlock 1000 MHz. This exercises the real helper/controller; a physical KEY2 cycle
  on the live runtime is still pending. The runtime's automatic screen-off independently logged
  `powersave` after 60 seconds; backlight `bl_power=4`, actual CPU clock 600 MHz.
- At 600 MHz, hotspot, Bridge, manager and Bluetooth services remained active; automatic Printer
  scan attempts continued every 30 seconds. SSH worked. FTP returned its normal greeting and
  NOOP response from the hotspot interface; the USB source remained correctly rejected in the
  saved hotspot-only receive mode. These are control-path checks, not a camera upload or a
  successful Printer reconnect (the paired Instax Square was not advertising).
- Same-source image preparation, live config, alternating governors (two samples each):
  600 MHz **9.909/9.513 s**, 1000 MHz **5.659/5.735 s**, all produced 102303-byte JPEGs. These
  call the real image pipeline without sending film; they demonstrate the need for a photo-job
  boost, not total print speed or battery savings. Per-boot throttling flags stayed `0x0`; SoC
  temperature after the trials was 50.5 °C.
- The updated sampler produced a 600 MHz / `powersave` / backlight-off sample with flags 0 and
  USB carrier 1; it remains disabled between tests. FFI binary was unchanged, SHA-256
  `a974372ec276fdd3e21eab28fdf5f769b68e5216c5bcdec6f63bec9568e1cc96`.
- Pending: a fresh physical lock/wake and a controlled camera/Printer run to verify full photo
  job integration, reconnect timing and print stages after these tier changes.
- Repeat the battery test with the new awake policy and a realistic workload. Plan 057's overnight
  idle estimate does not establish 16-hour use with this policy.
