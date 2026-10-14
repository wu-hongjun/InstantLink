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

Connected-time measurement and the installed disconnect/reconnect acceptance depend on the
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

**Full automatic boot-to-Printer and installed disconnect/reconnect remain pending availability.**
The saved Printer is not connected at handoff. No firmware-warning-free or live-reconnect claim.
