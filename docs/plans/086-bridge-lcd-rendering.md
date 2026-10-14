# Bridge LCD rendering

## Goal

Reduce display work while preserving exact pixels, button responsiveness, lock/unlock,
backlight ordering and the shared physical/virtual LCD state machine. Hardware benchmarks
use display/status operations only; no film.

## Approach and acceptance

Subagents optimize framebuffer RGB565 packing with existing Pillow operations and audit
controller/render lifecycle. Keep synchronous frame ordering, existing deduplication and
pixel restore before backlight activation. Independent review checks byte order, channel
quantization, input modes/sizes, every UI state, image immutability, and failure paths.

Profile actual Pi frames by layout drawing, RGB565 packing, kernel framebuffer writes and
backlight control, including main-thread CPU and event-loop stalls. Compare baseline,
candidate and installed equivalent frames at 1000 MHz. Validate Linux GPIO mockup input through
production code, same-button triple unlock, mixed-button reset, debounce, 10s abandonment,
dark 600 MHz and awake 1000 MHz, framebuffer equality against the original scalar oracle, fresh
status and reconnect. Preserve actual panel-scanout/contact/energy measurement limitations.
Run all path-scoped gates, deploy clean source and restore normal service/remove owned fixtures.

Hardware: Pi Zero 2 W Rev 1.0 / ST7789 / X306, Debian 13.2 / Linux 6.12.47+rpt-rpi-v8 / Python 3.13.5 / BlueZ 5.82.
Instax Link Square INSTAX-52006924. No image/print commands or physical film-quality retest.

## Implementation and independent review

Clean source `cac3318` replaces the Python per-pixel RGB565 loop with existing Pillow native
band lookup/add/interleave operations. Channel fields are disjoint; addition cannot overflow.
The two-byte LA container preserves low-byte/high-byte ordering without alpha interpretation.
No new dependency or asynchronous frame queue. Existing redraw suppression, dark blanking,
pixel restore before backlight, controller ordering and shared virtual renderer remain intact.

Independent review checked all 16,777,216 RGB colours, 17 Pillow modes, six zero/odd layouts
and 40 light/dark UI snapshots: 64 byte-equivalence checks passed. All 456 independently run
affected tests passed. Normal source gates: 1825 Bridge tests, 27 existing warnings, Ruff,
strict mypy (67 modules), formatting and strict MkDocs passed. No native/C ABI/schema changes.

## Pi rendering benchmark

Eighteen equivalent frames per variant, six UI states repeated three times, actual `/dev/fb1`
at 1000 MHz. Synthetic Printing snapshots exercise display only; no Printer image commands.

| Median milliseconds | Baseline | Candidate | Installed |
| --- | ---: | ---: | ---: |
| Total render | 267.376 | 45.810 | 41.830 |
| Layout/text drawing | 30.930 | 33.718 | 31.022 |
| RGB565 packing | 234.782 | 10.132 | 9.350 |
| Kernel framebuffer write | 0.342 | 0.376 | 0.365 |
| Backlight operation | 0.917 | 1.018 | 0.900 |
| Rendering thread CPU | 266.528 | 43.397 | 41.154 |

All 18 frame hashes match across all three variants. Installed total time fell 84.4% and
rendering thread CPU fell 84.6%; these measure changed frames, not whole-device idle CPU,
energy or battery runtime. Timing ends when the kernel framebuffer write returns, not panel
scanout. Fonts/QR are already cached; layout/text drawing (~31 ms) is the next rendering cost.

Maximum heartbeat lag was 272.445/179.448/48.735 ms baseline/candidate/installed. Concurrent
services were active, including BLE setup during candidate frames. These observations include
other event-loop work and do not establish an isolated LCD or universal button-latency bound.

## Input, lock and reconnect validation

Baseline, candidate and installed each passed 11 checks using an owned Linux GPIO mockup
controller through production input code, actual framebuffer/backlight and CPU tiers. Covered
key 2 lock, rejected bounce/sub-50ms press, accepted 75ms wake, held key counted once,
same-action/different-button reset, same joystick triple unlock, rapid key 1 triple unlock,
10s no-new-press abandonment to black/600 MHz and detached mock inactivity with physical
GPIOv2 input still registered. Wake/home pixels matched the original scalar packing oracle;
dark timeout checks intentionally require black pixels. Awake tier was 1000 MHz.

Queue-to-task-completion sample medians were 218.158/34.340/34.024 ms baseline/candidate/
installed. Initial state/action counts differ (18/15/15); these are descriptive observations,
not controlled physical contact latency. Wake includes CPU transition work and can take longer.
Physical contacts were not actuated; panel scanout was not measured.

Candidate/installed startup status was ready in 3.492/3.815s and subsequent periodic status
remained fresh. Automatic recovery after external BlueZ Device1.Disconnect took 12.135/6.466s,
with all 31/15 observations locked at 600 MHz and camera-ready, followed by new fresh status
and a connected Printer. Advertisement/setup variation remains; no reconnect speedup is
attributed to the LCD change. No image commands or film were used.

## Deployment, running logs and cleanup

Clean Python `cac3318` installed through the normal deploy script. Native `b2b6c8c` unchanged;
FFI SHA256 `9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031` and CLI
`1068fcb591c94e5a2b8bb888361230ade931b8da5b529528500c58edba4ce38e`. Installed source hashes
match the reviewed files. Independent candidate, installed and final health/log/cleanup reviews accepted.

Normal service restored at 20:56 EDT; final health 20:57:05 EDT: Bridge PID38577 and manager
active with zero restarts, connected Printer, GPIOv2, 600 MHz powersave, 51.540°C,
throttle `0x0`, backlight GPIO24 low, hotspot/USB addresses and FTP220/200 healthy.
FTP probe uses the Pi hotspot address locally; it does not measure camera upload or airtime.
All owned drop-in/socket/mockup/source archive/observer/smoke/health scripts removed.
Private raw journals and result traces retained as evidence.

Full current-boot Bridge/manager journal review: 11667 records, 136 matched issue messages.
135 were historical, including two earlier native panic episodes and a PID480 CRITICAL
status-worker-stuck restart. The prior plan085 filter omitted CRITICAL; this audit includes it. The additional baseline
warning `instantlink.status_cancel_waiting_for_worker` occurred at the requested restart while
Printer was offline: the existing serialized FFI cancellation path waits for its worker. No
accompanying grace timeout or display/input fault. Full candidate/installed/normal process
logs (249/231/36 records) have no matched warnings, errors, render/input failures or panics.
This scope does not claim all kernel logs or historical faults are clean.

Evidence: [audit assets](../assets/bridge-audit-086/README.md). Exact framebuffer equivalence,
input reliability, CPU tiers, fresh status, automatic reconnect and normal-service health pass;
no film used. Remaining LCD work is layout/text drawing, subject to preserving exact output
and avoiding delayed frames after lock. No extra optimization is claimed for BLE setup.
