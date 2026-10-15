# Plan 097 evidence

Hardware: Raspberry Pi Zero 2 W Rev 1.0, ST7789 240×240 framebuffer, X3062300mAh;
Debian13.2, kernel6.12.47+rpt-rpi-v8, Python3.13.5, BlueZ5.82. Saved Printer:
Instax Link Square INSTAX-52006924. All Printer checks are status/discovery/disconnect only;
no image-transfer, print or actuator command and no film used.

- `import-comparison.json`: two warmups then three counterbalanced fresh processes per source;
  same installed interpreter/dependencies, warm filesystem/precompiled bytecode, observed
  powersave600MHz throughout, no governor mutation. Baseline app-import median2.108s,
  candidate2.026s; overlapping ranges and small sample count limit inference. Whole process
  wall time is recorded separately. Normal Bridge retained; no app run or device operations.
- `image-baseline.json`, `image-candidate.json`: isolated actual image worker prepares retained
  DSC02821.HIF and an asymmetric EXIF6 JPEG for Square/Mini Link3/Wide. All4 JPEG SHA/bytes/
  dimensions/quality/fit/flip fields match exactly. Single timing observations measure worker
  preparation, not full upload latency or physical print quality; candidate first JPEG includes
  deferred processing imports. No consumer/backend/Printer exists in this probe.
- `render-comparison.json`:92 deterministic offscreen Pi frames covering every mode and3 Post
  editors, English/Chinese, light/dark. Exact RGB bytes vs baseline, not physical panel/contact
  observation. No LCD writes or Printer operations.
- `baseline-boot.json`: unchanged clean44e6cb4 normal reboot, no buttons before fresh status,
  LCD13.822s/core13.835s/Printer20.484s, film10→10. Kernel monotonic clock excludes firmware time.

Source079af5a matches every one of the17 production files in the clean temporary benchmark
archive. Independent review accepted source and predeployment evidence. Full2527 Bridge tests,
eight expected host GPIO fallback warnings, Ruff/format164/mypy70/strict docs pass. Review fixed
cancelled-import cleanup and first-editor render import-lock risks; queued input still awaits
that first editor activation while the event loop remains responsive.

Initial AppleDouble-containing staging archive was replaced before accepted probes. Concurrent
import/image timing attempts were rejected and rerun sequentially. Temporary Pi files were
removed by the baseline reboot. No production defect or timing result is inferred from them.

## Installed acceptance

- `installed-boot.json`: clean079af5a, automatic reboot without Bridge input. LCD13.665s,
  FTP13.652s/core13.676s/fresh Printer18.962s, film10→10. Compared with baseline, process launch
  to boot marker3.340→3.233s; whole connected time20.484→18.962s includes radio/bond variation.
  Single paired reboots do not attribute the1.522s difference to Python imports or establish a
  general speedup. Kernel timing excludes firmware startup. Candidate used the retained guarded
  reset while baseline discovery took longer.
- `awake-health.json`, `installed-health.json`: actual framebuffer populated148RGB565values/
  115200bytes at1GHz/performance/backlight high, then normal idle600MHz/powersave/backlight low
  (cleared framebuffer expected). PID482/manager640, zero automatic restarts, connected Printer,
  FTP220/200, active services/backup socket, throttle0x0. Source hashes match079af5a and the
  archived candidate; unit/FFI unchanged. No physical panel/contact observation.
- `reconnect.json`: external BlueZ Disconnect→fresh automatic status12.543s, film10→10.
  All23samples samePID/600MHz/powersave/backlight low/FTP220+200. First sample2.590s after dispatch;
  no continuous initial observation claim. First scan absent at INFO; existing prompt retry
  succeeded. No manual Reconnect or warnings/errors. Normal screen-off idle, not internal
  manual-lock flag introspection.
- `isolated-ftp.json`: installed production FTP service receives JPEG byte-for-byte into its
  queue, STOR226/NOOP200, temporary directory/credentials/highport, no consumer/backend/Printer
  calls. Normal port21 retained. Physical camera and normal application print dispatch not tested.
- `live-log-review.json`: full current-boot three-service journal124records, current Bridge PID
  101records/zero warnings-errors. Retains BlueZ directorymode and requested-disconnect notices,
  manager bind pending resolves1.006s later. System/kernel outside this snapshot; no global
  warning-free claim. Raw service journal retained privately and reviewed; remote copy removed.

No film used. Final independent evidence review accepted scope and findings. Source remains
079af5a; the final documentation deployment refreshes the clean manifest without restarting it.
