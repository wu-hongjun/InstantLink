# Plan 096 evidence

Hardware: Raspberry Pi Zero 2 W Rev 1.0, ST7789 framebuffer LCD, X306 2300 mAh;
Debian 13.2, kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82.
Saved Printer: Link Square INSTAX-52006924. No Printer image-transfer, print or actuator commands;
no film used. The isolated FTP fixture never dispatches to a Printer.

- `import-cost.json`: fresh Python app imports with warm filesystem cache in
  powersave/performance/performance/powersave order, retaining the production service and
  restoring powersave. Includes runuser/process startup. Isolates import CPU cost, not full boot.
- `baseline-core.json`: normal installed `0d79921` reboot with Printer unavailable. Kernel
  monotonic timings exclude pre-kernel firmware time; no injected input. SSH sampling starts
  after SSH becomes available and does not prove the governor during interpreter imports.

Three subagents investigated startup, implemented the changes and independently reviewed them.
Primary review found a pending trust-snapshot race, independently confirmed and corrected before
installation. Changed/invalidated trust now forces the existing bounded fresh retry. Final review
accepted the correction; 166 independent focused tests passed. Initial corrected Bridge gate: 2,497 tests,
eight expected host GPIO warnings, Ruff/format (161 files), strict mypy (68 source files), strict docs.

`candidate-core.json` and `candidate-core-repeat.json` are rejected CPU pre-start experiments,
with the trust optimization also installed. They reached UI14.306/13.918 s and core14.930/14.640 s,
versus baseline UI14.045/core14.059 s. The extra CPU hook did not demonstrate a clear readiness
benefit and was removed, together with its two tests. Service startup ordering now matches the
baseline; final no-hook hardware results must be evaluated separately. In the experiments,
FFI-loaded→first discovery policy fell from baseline0.722 s to0.104/0.104 s, consistent with removing
redundant inventory/trust processes. That is pre-discovery setup, not a connected-time result.

At the initial handoff, connected-time and installed reconnect acceptance were pending the
Printer advertising. The attempted connected baseline timed out before reboot or Disconnect;
it is not a passing connection result. A later reconnect readiness observer was interrupted by
the repeat reboot before it could obtain status or issue Disconnect; it is not a reconnect test.
Current verified measurements are scoped explicitly above.

## Final installed runtime

Clean `4049bcd`, without the CPU pre-hook, passed the final **2,495-test** Bridge gate (eight
expected host GPIO warnings), Ruff, format (160 files), mypy (68 files) and strict docs.

`final-core.json` records normal boot: LCD13.742 s, FTP13.728 s, core13.756 s and hotspot
receive-ready19.995 s. Baseline was LCD14.045/FTP14.036/core14.059/receive20.178 s. First discovery
policy moved from15.013 to14.035 s; native-library-loaded→discovery setup from0.722 to0.072 s.
These are single final/baseline reboots with no Printer advertisement or button input; they
demonstrate less setup overhead, not a measured full connected-time improvement.

`awake-health.json` verifies a nonblank 240×240 framebuffer (156 distinct RGB565 values), 1 GHz
and backlight high. `installed-health.json` verifies subsequent normal screen-off idle at600 MHz/
powersave/backlight low; its uniform cleared framebuffer is expected. Both retain Bridge475/
manager639, zero automatic restarts, FTP220/200, services/backup socket active, throttle0x0,
reviewed installed source hashes and unchanged native FFI. Full current-boot Bridge PID journal
has26 records and zero warning/error matches at the dark capture. Physical panel quality and
button contacts were not observed.

`isolated-ftp.json` records an on-Pi production FTP service receiving a valid JPEG into its
`ReceivedImage` queue with matching SHA256, authenticated STOR226 and NOOP200. It uses a temporary
directory/credentials and high port with no application consumer or native backend, so it cannot
use film. It does not test a physical camera or normal print dispatch. The first fixture inherited
an unreadable login-home cwd; retry used the deployed service's normal `/opt/InstantLinkBridge`
working directory. No production FTP change was required. Temporary files/server were cleaned up.

Full automatic boot-to-Printer and installed reconnect were pending at that checkpoint. The live
follow-up below completes them; the earlier offline results remain separately scoped.

## Live follow-up — accepted

After Printer power-on, the unchanged production source booted automatically to fresh Printer
status at **19.186 s**, LCD at13.911 s and core at13.924 s, with no button action. Film **10→10**.
`boot-connected.json` records clean manifest40e0911 (docs over production4049bcd). Kernel startup
clock excludes firmware latency. Earlier plan095 measured20.041 s; this individual run was0.855 s
lower, not a controlled radio/bond/cache comparison or a general percentage speedup.

This live cached-but-untrusted device needed the retained trust command and guarded startup
bond reset: FFI-loaded→first discovery was **0.874 s**. The offline absent-target0.072 s result
does not describe every connection. Remaining measured startup costs include process launch→
boot marker3.349 s, trust/reset about0.85 s and BLE-connect→service-discovery1.763 s.

`reconnect.json` records external BlueZ Disconnect dispatch→accepted fresh status **11.267 s**.
All21 samples retained Bridge497,600MHz/powersave/backlight low and FTP220/200; film **10→10**.
Samples begin2.273 s after dispatch because Disconnect blocks initially; no continuous observation
claim during that initial interval. Normal automatic screen-off idle was observed; no physical
button contacts or internal manual-lock flags were tested. No setup failure or warning/error.

`connected-health.json` confirms Bridge497/manager655 active, zero automatic restarts, Printer
connected/fresh, throttle0x0, active network/Bluetooth/backup socket, reviewed source and unchanged
FFI hashes. Complete current-boot Bridge PID journal91records has no warning/error matches.
`live-log-review.json` retains three wider records: BlueZ directory mode, manager hotspot bind
pending (listening1.007 s later), and BlueZ's no-matching-connection notice. No whole-system
warning-free claim. Independent evidence review accepted both trials. No film or Printer image/
print/actuator commands; physical camera and film output were not tested.
