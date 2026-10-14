# Bridge RGB565 packing

## Goal and acceptance

Reduce changed-frame framebuffer packing CPU while preserving exact little-endian RGB565
quantization, pixel order and input conversion. Synchronous frames, pixels-before-backlight,
button responsiveness, same-button triple unlock and 10s timeout/600MHz idle remain intact.
No image/print commands or film during validation.

Subagents implement/profile, audit runtime/dependency/lifecycle, and independently review
all RGB colours, Pillow modes/dimensions/concurrency/memory/fallback. Compare Pi baseline,
candidate and installed equivalent actual framebuffer frames at 1000 MHz, and first-frame
backend initialization. Existing NumPy supplied by RAW dependencies is optional; its import
must not block first framebuffer paints or lock blanking. Retain the exact Pillow path while
an owned background preload, scheduled after the first successful paint, prepares the backend and in minimal/no-event-loop runtimes.

Pi alternatives measured separately: Pillow 9.859 ms, byte-output 4.722 ms, word-expression
4.222 ms and word-output 3.160 ms per 240×240 frame, identical bytes (100 rounds). Chosen
word-output uses explicit little-endian uint16 output plus local scratch. Fresh NumPy import
531.424 ms wall/858.105 ms CPU and ~15.4 MiB peak RSS increase with filesystem pagecache
already warm; production first-paint behavior requires a separate gate.

Validate owned preload completion/failure/close/cancellation, kernel GPIO mockup through
production input/controller and real LCD/CPU, fresh status and automatic reconnect. Deploy
clean reviewed source, restore normal entrypoint, remove owned fixtures and review full
running logs including native severity labels and journald priority errors.

Hardware: Pi Zero 2 W Rev1.0 / ST7789 / X306, Debian13.2/Linux6.12.47+rpt-rpi-v8,
Python3.13.5/BlueZ5.82/NumPy2.4.6, Instax Link Square INSTAX-52006924.
Measurements do not claim contact-to-photon latency, physical scanout or battery lifetime.

## Implementation and adversarial review

Final clean source `398dde5` uses optional NumPy already pinned through RAW dependencies.
Exact uint16 output (`<u2`) plus one local uint16 scratch array replaces repeated Pillow band
operations after loading. RGB export, quantization and little-endian row/pixel order remain
exact. Buffers are per-call and the returned bytes immutable; traced 240×240 peak ~519 KiB
excludes Pillow native storage. 1000 repeated packs retained ~760 traced bytes. NumPy module
memory is additional; standalone fresh-process import increased peak RSS by ~15.4 MiB.

The display constructor creates no preload task. First successful frame write/backlight
finishes before one owned `asyncio.to_thread` import task starts. Frames and black blanking use
the ready callable synchronously, initially exact Pillow. Success switches only while open;
close cancels the task, and the worker never mutates the display. Missing NumPy keeps a quiet
cached fallback; unexpected loader failures warn once without interrupting frames. Failed
first writes/backlight do not start loading; no-loop boot splash uses Pillow without NumPy.

Review found and fixed first-paint import contention in the provisional constructor-start
variant. Final display SHA256 `608d52b29c5b4aad4c116fd0e63111b4f6155dfa81e26ab2fe679513ac17af1a`.
Packing arithmetic was exhaustively validated for all 16,777,216 RGB colours on the preceding
hash and is unchanged by the final post-paint scheduling delta. 71 additional mode/size/frame/
mutation/concurrency checks, independent blocked-worker lifecycle cases and 594 affected tests
pass. Producer 63 display tests/runtime audit 122 pass. Normal 1956 Bridge tests, 27 existing
warnings, Ruff, touched formatting, strict mypy 67 modules and strict MkDocs pass.
No dependency/C ABI/native/config/schema changes.

## Settled Pi rendering and first paint

Eighteen equivalent actual framebuffer frames per variant at 1000 MHz, six states repeated
three times after warming/settling. All 18 framebuffer hashes match across variants.

| Median milliseconds | Baseline | Candidate | Installed |
| --- | ---: | ---: | ---: |
| Total render | 14.121 | 7.905 | 7.784 |
| Text/layout draw | 2.682 | 2.813 | 2.742 |
| RGB565 pack | 9.852 | 3.186 | 3.311 |
| Kernel write | 0.361 | 0.425 | 0.402 |
| Backlight | 0.943 | 0.974 | 0.992 |
| Rendering thread CPU | 13.772 | 7.513 | 7.479 |

Installed packing fell 66.4%, total rendering 44.9% and rendering thread CPU 45.7%. This is
changed-frame work, not whole-device idle CPU, energy or battery runtime. Timings end at kernel
write/backlight return, not panel scanout. Maximum heartbeat lag 18.826/11.382/13.020 ms captures
other loop activity too and is not a physical button latency guarantee.

First-frame render 129.009/128.165/149.037 ms baseline/candidate/installed; first hashes identical.
Candidate and installed first paint finish before loader start, then NumPy becomes ready about
1.486/1.468s later while frames retain Pillow. Warm service ExecStart-to-first completion
2.729/2.758/2.398s with prebaked bytecode and filesystem pagecache warm; no power-on boot or
universal startup-speed claim. Installed first-frame variation is retained explicitly.

Early uncompiled/provisional measurements overlapped startup/import work and were replaced by
settled, prebaked comparisons. Raw preliminary results retained privately. First GPIO fixture
attempt at Booting was rejected before input and its owned module unloaded; the fixture now
waits for startup to finish, and all subsequent cases pass.

## Input validation

Baseline/candidate/installed each pass 11 owned kernel GPIO mockup cases through production
input/controller and actual LCD. Debounce/short rejection, held-once, 75ms accepted/rapid
presses, same-button triple unlock, mixed-button reset, nonblank wake, 10s no-new-press timeout
to black/600 MHz and awake 1000 MHz preserved. Frame pixels match the frozen renderer plus
independent scalar RGB565 oracle. Mock detach leaves physical GPIOv2 input registered.

Queue-to-task-completion medians 16.502/10.299/11.952 ms, with action counts 18/15/18 and
varying initial states, are descriptive only. Physical contacts and scanout were not measured.
No image/print commands or film.

## Installed status and reconnect

The Printer was initially unavailable: candidate status wait timed out after 100s without a
fresh result. This is retained; no candidate reconnect success claimed. After the user turned
it on, installed successful status-attempt duration was 3.443s and subsequent periodic reads
were fresh. Availability-inclusive first-to-ready 243.459s includes the powered-off wait and
must not be interpreted as a boot/setup benchmark.

Installed automatic recovery from external BlueZ Device1.Disconnect took 11.649s, all 31
observations locked at 600 MHz and camera-ready, final BlueZ connected with new fresh status.
No manual Reconnect, image commands or film. Advertisement/setup timing remains variable;
no recovery-speed attribution to RGB565 packing.

## Deployment, normal health and running logs

Clean Python `398dde5` installed with native `b2b6c8c` unchanged. FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031` and CLI
`1068fcb591c94e5a2b8bb888361230ade931b8da5b529528500c58edba4ce38e` verified; loaded
library mapping and reviewed source hashes match. Candidate and installed independent
LCD reviews passed, then installed Printer status/reconnect and final normal health/log/cleanup
reviews passed.

Normal service restored at 22:12 EDT. Final health 22:14:50 EDT: Bridge PID43539/manager43015
active, zero restarts, Printer connected, 600 MHz powersave, 44.008°C/throttle0x0,
GPIO24 low/GPIOv2, hotspot/USB and FTP220/200 healthy. FTP probe uses the Pi hotspot address
locally; no wireless airtime/camera upload measured. All owned observer/drop-in/socket/mockup/
source archives/oracle/scripts/bytecode/health fixtures removed, private raw evidence retained.

Full current-boot Bridge/manager review: 14728 records, 146 matched messages, including
144 historical faults and two baseline shutdown `status_cancel_waiting_for_worker` warnings
at requested restarts while the Printer was unavailable. No accompanying grace-expired,
worker-stuck, display or input faults. Earlier native panic/CRITICAL/systemd failure records
retained; historical plans unchanged. Provisional/final candidate/installed/normal logs
(192/246/515/51 records) contain no matched warnings/errors/render/input/packer failures or
panics. Filter includes ANSI-stripped Python/Rust severity labels and journald priority0–3;
no kernel-log cleanliness claim.

Evidence: [audit assets](../assets/bridge-audit-088/README.md). No film used. NumPy's measured
initialization/RSS tradeoff is explicit; first paint and synchronous ordering are preserved.
Remaining local rendering costs are packing (~3.3ms), text/layout (~2.7ms) and backlight (~1ms)
per changed frame; further changes should preserve measured startup and pixel equality.
