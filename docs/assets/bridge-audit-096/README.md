# Plan 096 evidence

Hardware: Raspberry Pi Zero 2 W Rev 1.0, ST7789 framebuffer LCD, X306 2300 mAh;
Debian 13.2, kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82.
Saved Printer: Link Square INSTAX-52006924. No film, image or Printer actuator commands.

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
