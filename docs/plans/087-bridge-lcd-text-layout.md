# Bridge LCD text and layout drawing

## Goal and acceptance

Reduce text/layout CPU time while preserving exact display pixels, font fallback, clipping,
language/font/theme changes, current animation clocks, button responsiveness and reliable
same-button triple unlock with 10s abandonment. Physical and virtual LCDs keep one synchronous
renderer and state machine. No image/print commands or film during hardware validation.

Subagents profile and implement bounded text reuse, audit renderer/controller lifecycle,
and independently compare original/candidate output across UI modes, themes, font sizes,
English/Chinese strings, clock phases, transitions and difficult clipping. Include cold/warm
work, bounded cache memory and concurrent virtual/physical rendering in acceptance.

Pi benchmark: actual framebuffer draw/pack/write/backlight spans at 1000 MHz, equivalent
baseline/candidate/installed frames, main-thread CPU and event-loop observations. Kernel
GPIO mockup tests exercise production button queues, actual LCD and 600/1000 MHz tiers.
Physical contacts and panel scanout are not measured. Fresh status and automatic reconnect
remain required when the Printer is available. Deploy clean reviewed source, restore normal
service, remove owned fixtures and review running logs including CRITICAL messages.

Hardware: Pi Zero 2 W Rev 1.0 / ST7789 / X306, Debian 13.2, Linux 6.12.47+rpt-rpi-v8,
Python 3.13.5, BlueZ 5.82. Instax Link Square INSTAX-52006924.

## Implementation and source review

Clean source `06bbe86` adds bounded LRU caches for text bounding boxes (512 entries), grayscale
masks (256 entries) and variation capability (32 entries). Mask pixels cap at 256 × 240 × 48
bytes, below 3 MiB; font, text and cache metadata overhead are additional. Keys retain actual
resolved font and underlying font core, text and anchor. Direct text calls keep their original
font choice; CJK fallback resolves before caching where it did previously.

Each frame still resolves current layout, theme, clipping, coordinates and animation clock.
Private grayscale masks use Pillow's bitmap route, preserving antialiasing rounding on coloured
backgrounds. Output images remain independent. Variable fonts, multiline/long text, oversized
masks, fractional coordinates and unsupported image/font modes use original drawing. No new
dependency, asynchronous frame queue, controller/GPIO/framebuffer/Bluetooth/config/C ABI change.

Subagents implemented and audited. Frozen renderer SHA256
`df10cadf41ea34c9b3baabcd5edcb08b75764804fda851151a4f6c60ebed7775` independently passed
1303 pixel/behavior/cache checks against the original `e895b44` renderer, plus 80 concurrent
frames and 454 existing affected tests. Producer 220 tests and runtime audit 136 tests pass.
Normal gates: 1926 Bridge tests, 27 existing warnings, Ruff, touched-file formatting, strict
mypy (67 modules) and strict MkDocs pass.

## Pi rendering benchmark

Eighteen equivalent actual framebuffer renders per variant, six states repeated three times,
1000 MHz with fonts/text warmed. All 18 framebuffer byte hashes identical across variants.

| Median milliseconds | Baseline | Candidate | Installed |
| --- | ---: | ---: | ---: |
| Total render | 42.092 | 18.576 | 13.994 |
| Layout/text drawing | 31.158 | 3.656 | 2.663 |
| RGB565 packing | 9.502 | 11.662 | 9.873 |
| Rendering thread CPU | 41.417 | 15.600 | 13.728 |

Installed total rendering fell 66.8%, layout/text 91.5%, and rendering thread CPU 66.9%.
These are changed-frame samples, not whole-device idle CPU, energy or battery runtime.
Timing ends at kernel write completion, not panel scanout. Normal concurrent services were
active; BLE setup overlapped candidate measurements. Heartbeat maxima 48.523/157.346/18.683 ms
include unrelated work, so do not attribute all lag or guarantee button latency from these.

The first baseline trial overlapped GPIO/profile operations; a clock assertion rejected its
mixed 600/1000 MHz samples. Those results were excluded and replaced by the sequential,
fixed-1000-MHz baseline above. No failed trial is included in accepted result files.

A separate fixed-clock draw-only experiment clears added text caches before each of six
states, then repeats immediately. Fonts are already loaded, and the frozen original renderer
runs as an RGB oracle in the same process. Candidate cold/warm medians 26.045/2.743 ms versus
original 29.160/29.034 ms; installed 27.013/2.899 ms versus original 30.263/30.019 ms.
All 12 frames per variant match original RGB pixels. This is glyph-cache-cold work, not a
font-disk-cold startup benchmark. The main improvement is repeated text reuse.

An additional Pi draw-only matrix checks 240 frames: all 20 modes, light/dark, English/Chinese,
three font sizes, using actual installed font files. Every RGB frame matches the frozen
original and preview pixels remain unchanged. No framebuffer/Printer operations in this matrix.

## Input and automatic reconnect

Baseline/candidate/installed each pass all 11 Linux GPIO mockup checks through production input,
controller and actual LCD. Covered key 2 lock, bounce/sub-50ms rejection, accepted 75ms wake,
held button counted once, mixed-button reset, same-button joystick triple unlock, rapid key 1
triple unlock, 10s no-new-accepted-press timeout, black/600 MHz abandonment and detached mock
inactivity with physical GPIOv2 reader still registered. Awake tier is 1000 MHz, and wake/home
framebuffer pixels match the frozen original renderer plus scalar RGB565 oracle.

Queue-to-task-completion sample medians 34.454/16.643/16.670 ms have differing initial states
and action counts (15/15/18). They are descriptive production-queue observations, excluding
physical contact and panel latency. Wake also includes CPU-tier transition work.

Candidate/installed initial status 3.534/3.910s, with subsequent fresh periodic reads.
The Printer was initially off in baseline; its first-attempt-to-ready 123.760s includes an
availability wait and is not a boot or connection benchmark. Successful status-attempt spans
are recorded separately. Baseline/candidate/installed automatic recovery 8.848/12.463/6.650s;
all 21/32/15 observations locked at 600 MHz and camera-ready, final BlueZ connected and a new
fresh status. BLE advertisement/setup variation remains; no recovery speedup is attributed
to the text caches. No image/print commands or film.

## Deployment, normal state and log review

Clean Python `06bbe86` installed by the normal deploy script. Native `b2b6c8c` unchanged:
FFI SHA256 `9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`, CLI
`1068fcb591c94e5a2b8bb888361230ade931b8da5b529528500c58edba4ce38e`.
Installed renderer/source hashes match reviewed source. Candidate and installed independent
hardware reviews and final normal health/log/cleanup review accepted with no blockers.

Normal entrypoint restored at 21:25 EDT. Final health 21:27:25 EDT: Bridge PID40805 and manager
PID40331 active, zero restarts, connected Printer, 600 MHz powersave, 49.388°C, throttle `0x0`,
GPIO24 low/GPIOv2, hotspot/USB addresses and FTP220/200 healthy. FTP probe is local through the
Pi hotspot address; no wireless airtime/camera-upload measurement. Owned observer/drop-in/
socket/mockup/source/archive/oracle/benchmark/smoke/health/cleanup scripts removed.

Full current-boot Bridge/manager logs: 12949 records, 144 matched messages, all historical.
The expanded filter includes ANSI-stripped Python/Rust WARN/WARNING/ERROR/CRITICAL/FATAL and
journald priority 0–3. It adds eight historical systemd startup-failure records to the earlier
136 matches; those records, two old native panic episodes, an old CRITICAL worker-stuck restart
and prior task086 shutdown cancellation warning remain explicit. Historical plans unchanged.
Full task087 baseline/candidate/installed/normal process logs (353/348/375/34 records) have no
matched warnings, errors, rendering/input failures or panics. Raw journals retained privately;
no kernel-log cleanliness claim.

Evidence: [audit assets](../assets/bridge-audit-087/README.md). Exact display output, button and
unlock reliability, CPU tiers, fresh status and automatic reconnect pass with no film used.
Framebuffer RGB565 packing (~10 ms per changed frame) is now the largest measured rendering
cost. Cache reuse improves changed-frame drawing; no whole-boot or battery-runtime claim.
