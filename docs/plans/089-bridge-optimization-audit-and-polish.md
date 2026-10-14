# Bridge optimization audit and polish

## Scope

Install the existing optimized build, independently audit every optimization in plans 057–088,
fix the findings, review the fixes independently, and deploy the validated result. Each of the
32 plans has its own fresh subagent review of the same clean baseline, `c4a2787`. The code stayed
unchanged until those reviews finished. Review results and exact focused checks are retained in
`docs/assets/bridge-audit-089/individual-audits.json`; overlapping test counts are not additive.

No film, image download or actuator command is needed for hardware acceptance. This work does
not measure battery runtime, wireless camera airtime, mechanical print duration or developed-film
quality. Existing print-byte, quality and orientation evidence remains bounded to its original
Printer models and photos. No Rust source, FFI header, image transformation, Bluetooth fragment
size or pacing policy changes are planned.

## Findings and fixes

| Area | Audit | Correction |
|---|---|---|
| CPU policy | 057, 058 | Retry transient governor failures autonomously with capped backoff and coalesced warnings. Invalidate cached state before external writes, including partial or cancelled writes. |
| CPU shutdown | Fresh review | Join the owned governor restoration through repeated cancellation before propagating cancellation. |
| Saved Looks | 060 | Persist/load clamped vignette; legacy files default to zero. Round hue's inverse scale to preserve every valid UI value. |
| Error footer | 059 | Sync errors show KEY3 iPhone, matching the actual action. |
| Lost input | 062, 077, fresh review | Discard uncertain buffered input, balance queue accounting and relock before a new unlock sequence. Apply to queue overflow, kernel sequence gaps and failed resynchronization/backend fallback. Physical and remote inputs share this behavior. |
| Review duration | 066 | Start the selected interval after the first timed photo frame finishes rendering. Manual confirmation and immediate printing retain their separate behavior. |
| About details | 067 | Identify value dialogs by their information key and refresh them after collection. Explanatory Help remains unchanged. |
| Hidden About work | 075 | Avoid collection behind the locked/unlock overlay; collect once the page is visible. |
| Metadata ownership | 068, follow-up | Shield/join the EXIF thread before releasing preview or sender ownership, including repeated cancellation. |
| Accepted print parameters | 072 | Freeze live UI configuration after confirmation, before consuming prepared bytes. Selection, sender options and detected-model fallback use that same accepted configuration. The captured upload destination stays fixed. |
| Sync originals | 068 | Copy new spool originals to independent inodes. Atomically detach persisted legacy links. |
| Legacy incoming files | Upgrade review | Detach a shared incoming inode before FTP opens it for writing, including the period before deferred Sync initialization. Preserve append/resume content. |
| Outbox publication | Storage failure follow-up | Commit a staged index before publishing arrivals or deleting evicted/acknowledged originals. Failed index writes preserve the committed queue; readers remain responsive during publication. |
| FTP overflow | 069 | Retain source ownership through rejected-photo deletion, including errors and multiple owners. |
| Shutdown admission | 070 | Close FTP admission when shutdown is observed, before joining active photo cleanup. |
| Resource shutdown | 067 | Run every ordered cleanup after an individual resource fails, then report the failure. An input-close failure also preserves Printer/provider/display cleanup. |
| Backlight ownership | 086 | Close the owned GPIO fallback exactly once. |
| Manager responsiveness | 067 | Collect HTTP information off the event loop; share a bounded stable-info cache and serialize CPU sampling. Firmware operations invalidate cached versions. Config, pairing and metrics remain fresh. |
| Snapshot freshness | 078, 081 | Retry a superseded snapshot once and refuse uncertain results; protect consumers as well as the cache. |
| Watch authentication/bounds | 085 | Require the captured authenticated owner for snapshot seeds; abandon an overflowing pending watch and retain polling fallback. |
| Bond removal targets | 082, fresh review | Validate the exact deletion set, never enlarge it from a later inventory. Check the next CLI target last, immediately before dispatching removal. |
| Removal result | Fresh review | Count successful removals only. Failed-only batches do not retire the native session. |
| Recovery logging | 080 | Log the transition from retaining a session to disconnecting it; suppress repeated observations with the same disposition. |

The live-link guard is a fresh check immediately before dispatch, not an atomic transaction with
BlueZ. A state change after dispatch cannot be prevented by application-side checks. Legacy
spool migration fails closed if the filesystem cannot create an independent file: originals and
index remain retained, the failure is logged, and Sync requires a successful restart. No claim
is made that a disk failure can be repaired without sufficient writable storage.

## Independent validation

The initial audits include malformed JPEG/C ABI checks, complete RGB565 color-space comparisons,
original-renderer pixel comparisons, real local FTP transfers, held-worker cancellation,
controlled governor failures, D-Bus reply/signal interleavings and reconnect ownership. Linux-only
Rust transport execution is explicitly distinguished from macOS host tests. Each report records
its limitations; historical hardware observations are not presented as new measurements.

Fixes have separate fresh reviews for power/presets, Bluetooth, files/manager and interface/input.
Review failures are retained along with their resolutions rather than omitted from the record.
The final path-scoped gates, clean source revision, device acceptance and normal-service state
will be recorded after they finish.

The full Python formatting gate also exposed 13 unchanged baseline files. Their formatting is
polished in this round; independent AST comparisons confirm all 13 preserve the baseline code.

## Initial installed measurements

The clean baseline was installed with the standard deployment script. A normal dark/offline
30.056-second sample at 600 MHz used 0.46 process-thread CPU seconds, about 1.53% of one core.
This excludes system/child-process CPU and is not an energy measurement. On the real ST7789,
18 fixed awake frames at 1000 MHz had median render time 7.627 ms, with packing 3.204 ms and
thread CPU 7.385 ms. These are controlled frame measurements, not a full-print timing claim.

All available current-boot Bridge/manager service logs and kernel logs were copied privately and
classified. At the initial review, 14,796 service records included 144 historical flagged records
and no warning/error from the installed baseline process. The 626 kernel records included 177
brcmfmac vendor-IE errors, five early multimedia initialization failures and one earlier HCI
connection-timeout warning. These precede this audit's installation and are retained historical
driver/firmware findings; this application polish does not claim to repair their kernel causes.
Raw journals remain private; only count inventories are committed.

## Final local gates and installed acceptance

Clean source **6a60165ae7993722a034e9389e0516db1819df85** passed the normal commit hooks:
**2,269 Bridge tests**, 27 existing warnings, Ruff, all **152** Python files formatted, and
strict mypy on **67** source files. Strict MkDocs passed. The first full run exposed an old
cancellation test that expected its EXIF reader to outlive its owner; it now requires joined
cleanup while proving input remains responsive. Four independent fix reviews have no remaining
scoped findings, including the later transactional outbox changes. Their histories remain in
`polish-reviews.json`.

Installed on Pi Zero 2 W Rev 1.0 / ST7789 240×240 / X306 2300 mAh; Debian 13.2,
Linux 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82 and NumPy 2.4.6. All 67 installed Python
source hashes match the clean commit. Native source remains `b2b6c8c`; the existing FFI SHA
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031` and CLI SHA
`1068fcb591c94e5a2b8bb888361230ade931b8da5b529528500c58edba4ce38e` are unchanged.

- Eleven real kernel GPIO-mockup cases through the production action queue passed bounce,
  held/mixed controls, 75 ms presses, triple unlock, ten-second abandonment, framebuffer
  restoration and 600/1000 MHz policy. Physical switch contacts were not actuated. The slowest
  observed unlock frame write completed 52.2 ms after accepted input. Queue completion can
  include governor warmup (maximum 400.2 ms); it is not a pure display-latency measurement.
- A one-shot governor failure recovered autonomously in **0.337 s**. Cancellation after the
  real helper wrote performance restored the locked board to powersave/600 MHz, with no photo
  work begun. The intentional warning and traceback remain in the test journal.
- Eighteen awake frames matched every baseline RGB565 byte. Median render **7.627 → 7.703 ms**,
  thread CPU **7.385 → 7.320 ms**; this small sample does not establish a rendering speedup.
- Installed file-ownership tests used synthetic files on the Pi filesystem: separate spool
  inodes/checksums, failed add/ACK publication retaining the committed index/original, legacy
  pre-open detachment and reload migration all passed. No production camera upload was made.
- Eight concurrent real manager hello requests had median 326.1 ms including a shared cold
  collection; fifteen concurrent time requests had median 5.71 ms, maximum 50.46 ms. No manager
  delay was injected; these are HTTP responsiveness observations, not CPU/energy measurements.
- Normal production dark/offline runtime at 600 MHz used **0.37 CPU seconds / 30.029 seconds**,
  about **1.23% of one core**, versus 1.53% in the initial 30-second sample. Neither sample used
  an observer. Short samples and scan phase limit comparison; no battery/energy result is claimed.

Normal Bridge/manager PIDs **45900/45198** are active, NRestarts 0, with powersave/600 MHz,
no throttling, FTP 220/200 on the Pi hotspot address and no normal-runtime warning/error or
input fallback. Removed the owned observer, runtime drop-in/socket, GPIO mockup and helper
scripts. The final complete available service journal has 15,172 records / 148 flagged records:
144 historical, two bounded status-worker cancellation waits during test restarts, and the two
intentional governor fault records. The normal restored process has zero flagged records.
The kernel journal has 637 records / 193 flagged records: 187 vendor-IE errors (ten additional
ones during service reconfiguration), five early multimedia failures and the same historical
HCI timeout warning; no new HCI warning. AP/FTP operation remains healthy. Driver causes are
recorded maintenance limits, not claimed repaired by these changes.

**Pending hardware gate:** INSTAX-52006924 was not advertising throughout this round. Its
power-on was requested; no film was consumed and no actual Printer disconnect/reconnect test
is claimed. Source/mock safety and freshness tests passed, including both selection backends,
current-owner identity changes and failed removal commands. Repeat the installed status-only
reconnect check when the Printer is available.
