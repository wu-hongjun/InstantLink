# Plan 098 evidence

**The socket-ordering experiment was rejected. Final production ordering is unchanged from
accepted a815fb1.** New regression tests protect daemon lifetime ordering and manager recovery.

Hardware: Raspberry Pi Zero2W Rev1.0/ST7789 240×240/X3062300mAh; Debian13.2,
kernel6.12.47+rpt-rpi-v8, Python3.13.5, BlueZ5.82. Saved Instax Link Square INSTAX-52006924.
No Printer image-transfer, print or actuator commands; no film used.

## Experiment and controls

- `baseline-core.json`: unchanged a815fb1 normal reboot, no input, UI13.605683s,
  FTP13.582428s/core13.616155s. Printer absent; null status is not a passing Printer check.
  Initial connected observer timed out after reboot; actual component journal was captured.
- `candidate-core.json`, `candidate-capture.json`: clean80c2c8d orders against active dbus.socket;
  actual process9.398s < daemonREADY9.866s. UI13.595050s, FTP13.593595s/core13.609813s. No
  meaningful end-to-end readiness gain demonstrated (single reboots; no general performance
  inference). The earlier launch did not advance observed readiness. Printer unavailable.
- `candidate-awake-health.json`: actual nonblank ST7789 framebuffer115200bytes/156RGB565values,
  1GHz/performance/backlight high; no runtime Bridge warnings. Not physical panel/contact testing.
- `before-candidate-reboot.json`: candidate deployed/restarted into prior boot asPID1985 before
  full reboot. Unit SHA identifies actual changed dependency during the recorded shutdown.
  Its uptime216s milestones describe a service restart and are not boot-time measurements.
- `candidate-shutdown.json`: full reboot shutdown6.728s, successful/no forced kill. Daemon stops
 235.116s before Bridge239.296s. Retains status-worker cancellation and D-Bus/BlueZ activation
  refusal warnings, proving the removed reverse dependency matters to lifecycle review.
- `baseline-shutdown.json`: prior accepted a815fb1 boot shutdown6.176s/no Bridge warnings;
  Bridge1499.511s before daemon1499.533s. Nonmatched native-worker/radio phases do not isolate
  warning causality or shutdown speed. Baseline is a separate prior boot, not baseline-core's
  subsequent shutdown, which already had the candidate unit installed before restart/reboot.

Both candidate and restored source gates pass2529tests/eight expected Mac GPIO fallback
warnings, Ruff/format165/mypy70/strict docs. On-Pi candidate systemd verification passed.
Three subagents audited, implemented and independently reviewed. Independent review accepted
rejection: tiny/null measured readiness benefit does not justify removing the daemon dependency.
No warning suppression, service disabling, CPU-policy change or manager serialization was added.

All timing is kernel monotonic and excludes pre-kernel firmware startup; wall clocks may differ.
The first previous-boot observer needed boot-ID hyphens removed for journalctl's accepted ID
format; its failed invocation changed no device state or production code.

## Final restored installed acceptance

- `restored-boot.json`: clean1a3a61d, automatic boot LCD14.003s/FTP13.982s/core14.016s,
  registered agent13.595s/fresh Printer19.476s, no Bridge input, film10→10. Single kernel-clock
  observation (firmware excluded), not a speedup versus earlier Printer-off trials.
- `before-restored-reboot.json`, `restored-shutdown.json`: connected restored service, exact
  original unit hash; successful6.320s stop, Bridge343.928s before D-Bus343.942s. One native
  disconnect_failed code=-3 warning when BlueZ stops independently. Not suppressed; no forced
  kill, native grace expiry or resource failure. Native/agent cleanup algorithms unchanged.
- `restored-awake-health.json`, `restored-health.json`: actual framebuffer148RGB565values/
  115200bytes at1GHz/performance/backlight high; later normal600MHz/powersave/backlight low and
  expected cleared framebuffer. Bridge501/manager active/zero automatic restarts, connected
  Printer, FTP220/200, throttle0x0 and network/backup socket active. Source/unit/native hashes
  match accepted a815fb1; no physical panel/button-contact observation.
- `restored-reconnect.json`: external Disconnect→fresh automatic status11.003622s;21samples
  samePID501/600MHz/powersave/backlight low/FTP220+200, film10→10. Samples start1.834s after
  dispatch; no continuous initial observation claim. One absent scan at INFO then prompt retry
  connects, no warning/error/manual Reconnect. Normal screen-off idle, not internal lock flag.
- `isolated-ftp.json`: production FTP component on temporary highport/credentials/directory
  receives886byte JPEG with exact SHA, STOR226/NOOP200. No consumer/backend/Printer calls;
  physical camera and normal print dispatch not verified. Normal port21 retained.
- `live-log-review.json`: complete current-boot five-service128records/current Bridge PID97,
  zero Bridge warnings-errors; three broader notices retained (BlueZ directory-mode and requested
  disconnect, manager bind pending that resolves~1s later). No system/kernel/global warning-free
  claim. Raw current service journal retained privately, reviewed and remote copy removed.

Final independent review accepted the scope, rejection and restored installed validation. No
Printer image-transfer, print or actuator commands; film10→10. The final documentation deployment
refreshes the clean manifest without restarting acceptedPID501. No runtime performance change
or application/native/config/driver behavior change retained.


### Later handoff availability

After the passing boot/reconnect checks, the Printer link dropped and a subsequent automatic
scan reported `not advertising`. No physical power-state observation was made. The Bridge
handled the disconnect without warning/error and remained PID501/600MHz/powersave, FTP220/200,
manager659 active/zero automatic restarts, accepted source/unit hashes and clean manifestad72ada.
`handoff-health.json` records this later snapshot; it does not replace or invalidate the earlier
passing tests. Do not describe the Printer as connected at final handoff. No further Printer
availability is needed to complete the already accepted unit audit; no film used.
