# Current Bridge Context

## RGB565 packing deployed, 2026-10-13

Plan088: clean Python **398dde5** installed; native b2b6c8c unchanged (FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`).

- Optional existing NumPy packs exact little-endian RGB565 with local uint16 output/scratch.
  Original Pillow fallback, conversion, quantization and order preserved. No dependency,
  native/C ABI/config/schema change, shared mutable buffers or asynchronous frame queue.
- First successful paint/backlight finishes before one owned background preload starts.
  Closing prevents late swaps; missing NumPy keeps quiet fallback, other load failures warn
  once. No-loop boot splash stays Pillow. Review fixed provisional import contention.
- Settled actual framebuffer: 18 equivalent 1000 MHz frames per variant, exact hashes.
  Median total **14.121 → 7.905 candidate / 7.784 ms installed**, packing 9.852 → 3.186 / 3.311 ms,
  rendering thread CPU 13.772 → 7.513 / 7.479 ms (45.7% lower installed). Changed-frame
  measurements do not establish whole-device idle CPU, energy or battery runtime.
- First frame 129.009/128.165/149.037 ms, same pixels; candidate/installed loading starts after
  paint and finishes ~1.486/1.468s later. Warm service ExecStart-to-first 2.729/2.758/2.398s
  with prebaked bytecode/pagecache warm; no cold-power-on speed claim. Standalone NumPy import
  531ms and ~15.4 MiB peak RSS increase retained. Settled samples replace preliminary trials.
- Independent 16,777,216-colour arithmetic oracle is unchanged by final scheduling delta;
  71 additional checks, 594 affected tests and lifecycle probes pass. Producer 63/runtime 122
  tests pass. Normal 1956 Bridge tests (27 existing warnings), Ruff/touched formatting,
  strict mypy 67 modules and strict docs pass.
- All 11 kernel GPIO mockup cases per variant pass through production input/controller and
  actual LCD: debounce, held/rapid, same-button triple unlock, mixed-button reset, nonblank
  wake, 10s timeout, awake 1000/locked 600 MHz. Physical GPIOv2 input retained; contacts not
  actuated and queue timing is descriptive, excluding contact/scanout.
- Printer-off candidate 100s status timeout retained. After the user turned it on, installed
  successful status 3.443s then fresh periodic reads; 243.459s availability-inclusive wait is
  not startup timing. Automatic recovery 11.649s, all 31 observations locked at 600 MHz and
  camera-ready, final fresh connected status. No manual Reconnect/image/print commands/film.
- Final normal 22:14:50 EDT PID43539/manager43015 active, zero restarts, connected, 600 MHz
  powersave, 44.008°C/throttle0x0/GPIO24low/GPIOv2/FTP220+200/hotspot/USB healthy; clean exact
  source/native hashes. Owned fixtures including bytecode removed. Independent source,
  candidate, installed and final health/log/cleanup gates accepted.
- Full boot 14728 records/146 matched: 144 historical plus two baseline requested-restart
  status-worker cancellation warnings, no accompanying grace-expired/worker-stuck faults.
  Provisional/final candidate/installed/normal logs have no matched issues. Historical
  panic/CRITICAL/systemd faults retained; raw journals private.
- Evidence docs/plans/088-bridge-rgb565-packing.md and assets/bridge-audit-088. Current changed
  frame costs: ~3.3ms packing, ~2.7ms drawing, ~1ms backlight, excluding physical scanout.

## LCD text/layout drawing deployed, 2026-10-13

Plan087: clean Python **06bbe86** installed; native b2b6c8c unchanged (FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`).

- Bounded text metrics/glyph-mask LRUs reuse exact Pillow work (512 metrics/256 masks).
  Retained mask pixels below 3 MiB; metadata/fonts additional. Effective font/core/text/anchor
  keys, original fallback for unsupported cases. Current layout/theme/clipping/clock remain
  live; no async frames/controller/GPIO/config/C ABI/dependency changes.
- Pi actual framebuffer, 18 equivalent 1000 MHz frames per variant: median rendering
  **42.092 → 18.576 candidate / 13.994 ms installed**; text/layout 31.158 → 3.656 / 2.663 ms;
  rendering thread CPU 41.417 → 15.600 / 13.728 ms (66.9% lower installed). All frame hashes
  identical. Candidate heartbeat includes BLE setup and is not an isolated LCD latency.
- Glyph-cache-cold/warm installed draw-only 27.013/2.899 ms vs original 30.263/30.019 ms;
  fonts loaded, all 12 original RGB comparisons match. Pi 240 mode/theme/language/font-size
  RGB comparisons exact and preview unchanged. First mixed-clock baseline trial rejected;
  accepted baseline rerun sequentially at 1000 MHz. No film/image/print commands.
- Independent 1303 pixel/behavior/cache checks + 80 concurrent frames and 454 affected tests
  pass. Producer 220 and runtime 136 tests pass. Normal 1926 Bridge tests (27 existing
  warnings), Ruff/touched formatting/mypy 67 modules/strict docs passed.
- All 11 kernel GPIO mockup cases per variant pass through production input/controller/actual
  LCD: bounce/held/rapid presses, same-button triple unlock, mixed-button reset, nonblank wake,
  10s timeout/black/600 MHz and awake 1000 MHz. Physical contacts not actuated; queue timing
  excludes contact/scanout. Physical GPIOv2 reader preserved after detach.
- Candidate/installed startup status 3.534/3.910s, later polls fresh. Baseline first-to-ready
  123.760s included initially offline Printer; actual successful baseline attempt 3.749s.
  Automatic recovery 8.848/12.463/6.650s; all 21/32/15 observations locked 600 MHz/camera-ready,
  final new fresh status and connected Printer. No LCD-attributed reconnect-speed claim.
- Final normal 21:27:25 EDT PID40805/manager40331 active, zero restarts, connected, 600 MHz
  powersave, 49.388°C/throttle0x0/GPIO24low/GPIOv2/FTP220+200/hotspot/USB healthy; exact clean
  hashes. All owned fixtures removed. Independent source/candidate/installed/final-health reviews accepted.
- Full boot review 12949 records/144 historical matched messages, including eight systemd
  priority3 startup failures omitted by the older filter. Two older native panic episodes,
  worker-stuck CRITICAL and prior cancellation warning retained. All task087 baseline/
  candidate/installed/normal logs have no matched issues. Raw journals private.
- Evidence docs/plans/087-bridge-lcd-text-layout.md and assets/bridge-audit-087. Next measured
  rendering cost: RGB565 packing (~10 ms); these are changed-frame CPU/write timings, not
  whole-device idle CPU, battery lifetime or physical scanout measurements.

## LCD rendering deployed, 2026-10-13

Plan086: clean Python **cac3318** installed; native b2b6c8c unchanged (FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`).

- Existing Pillow native band operations replace the Python RGB565 pixel loop. No dependency,
  asynchronous frames, controller/config/C ABI changes. Exact quantization and byte order;
  synchronous render, deduplication, dark blanking and pixels-before-backlight preserved.
- Pi actual `/dev/fb1`, 18 equivalent frames per variant at 1000 MHz: median total rendering
  **267.376 → 45.810 candidate / 41.830 ms installed**; packing 234.782 → 10.132 / 9.350 ms.
  Rendering thread CPU 266.528 → 43.397 / 41.154 ms (84.6% lower installed). All frame hashes
  identical. This is changed-frame work, not whole-board idle CPU, energy or panel scanout.
- Exhaustive independent RGB oracle (16,777,216 colours), 17 modes, six layouts and 40 UI
  frames pass; 64 checks and 456 independent affected tests. Normal gates 1825 Bridge tests,
  27 existing warnings, Ruff, strict mypy 67 modules, formatting and strict docs pass.
- All 11 kernel GPIO mockup cases pass in baseline/candidate/installed through production
  input/controller and actual LCD. Same-button triple unlock, mixed-button reset, held/bounce
  filtering, rapid 75ms presses, 10s abandonment, awake 1000/dark 600 MHz and nonblank wake
  preserved. Physical contacts not actuated; queue-to-done is not contact-to-photon latency.
- Candidate/installed startup status 3.492/3.815s, later polls fresh; automatic recovery
  12.135/6.466s. All 31/15 recovery observations locked 600 MHz and camera-ready, final fresh
  status/connected Printer. Advertisement/setup variation means no LCD reconnect-speed claim.
- Final normal 20:57:05 EDT PID38577/manager active, zero restarts, connected, 600 MHz
  powersave, 51.540°C/throttle0x0/GPIO24low/GPIOv2/hotspot/USB/FTP220/200 healthy, exact clean
  source/native hashes. Owned fixtures removed; no film/image/print commands.
- Full boot logs: 11667 records, 136 matched messages (135 earlier, including two older panic
  episodes and a CRITICAL worker-stuck restart omitted by the prior filter; one baseline
  shutdown status-worker cancellation warning retained). No matched
  errors/warnings/render/input faults/panics in candidate/installed/final normal logs.
  Independent source, candidate, installed and final-health reviews accepted; evidence in
  docs/plans/086-bridge-lcd-rendering.md and assets/bridge-audit-086.
- Next LCD cost: layout/text drawing (~31 ms); fonts/QR already cached. Measurements end at
  kernel writes, and heartbeat includes concurrent work. No battery-runtime claim.

## Initial disconnect-watch registration deployed, 2026-10-13

Plan085: clean Python **57e7db9** installed. Native b2b6c8c is unchanged (FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`).

- Complete owner/lifecycle-bound identity state is seeded by existing fresh snapshots and
  authenticated signals. Initial watch registration fell from 10.984/13.524ms to 0.495ms
  candidate/0.484ms installed, removing one snapshot. No extra startup task/query or per-poll
  work; 512-row cap, live bus and unique connected identity required. Fresh bond gate preserved.
- Safe fallback remains: installed reconnect 26.486ms used one snapshot when cache was
  inconclusive; installed forced fallback 10.061ms passed and removed its temporary watch.
  Candidate reconnect 0.792ms and installed resume 0.541ms used no extra snapshot.
- Delayed registration must still own token/generation/current selected identity. Normal gates
  1807 Bridge tests (27 existing warnings), Ruff, mypy (67 modules)/format/strict docs; independent 392
  affected tests plus 3 adversarial cases pass. Native/C ABI/config/sync schema unchanged.
- Recovery 11.824/7.179/12.588s baseline/candidate/installed; failed first scans retained in
  baseline/installed. All 32/15/35 observations locked at 600 MHz and camera-ready, periodic status still
  fresh. Triple unlock, nonblank LCD at 1000 MHz, and relock at 600 MHz and status pause/resume pass through actual
  controller/LCD; contacts not actuated. No film/image/print commands.
- Timing correction: earlier ~223ms Connected→fetch tail excluded watch (which starts later).
  Direct candidate NoFilm render measured 219.344ms; visible LCD rendering is the larger local
  cost. Historical timing stays valid, earlier watch attribution is corrected by plan085.
- Existing model-query retry exercised on hardware: no first-window ACK, one resend after
  1.002s, matching reply 186ms later and fresh status on the same connection. Reply-to-write
  attribution is unknown; no claim that resend caused the response.
- Final normal 19:33:33 EDT PID36582/manager36128 active/NRestarts0, connected, 600 MHz powersave,
  41.856°C/throttle0x0/GPIO24low/GPIOv2/hotspot/USB/FTP220/200 healthy; clean exact hashes.
  All task 085 observed service logs have no matched warnings/errors/panics. Full current-boot
  service review: 10681 records, 134 historical matched messages and two earlier panic episodes
  retained. Source/hardware/final-health independent review passed; owned fixtures removed.
- Evidence in docs/plans/085-bridge-disconnect-watch-registration.md and assets/bridge-audit-085.
  Next: visible LCD render (~220ms per changed frame), advertisement/GATT variation and handshake.

## Startup model-query recovery deployed, 2026-10-13

Plan084: clean Python/native **b2b6c8c** installed. FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`; CLI
`1068fcb591c94e5a2b8bb888361230ade931b8da5b529528500c58edba4ce38e`.

- A missed model reply permits one resend after 1s within the same 10s deadline, command lock
  and delivery guard. Only the eight-byte read-only capability query can replay; terminal
  timeout/cancellation/link/write failure still retires uncertain sessions. Healthy sends once.
- Review fixed partial-frame retention at the retry boundary and end-to-end DIS normalization.
  Authoritative dimensions remain required. Exact FI033 with Mini dimensions and FI017 with Square must
  agree; ambiguous Link 3 identity fails safely. No image bytes/model specifications/C ABI change.
- Initial status timing: baseline healthy 3.673s and timeout/recovery 32.271s; candidate warm starts
  3.734/3.703/3.866s, installed 4.326s. No missed ACK recurred in candidate/installed startup,
  so no measured live retry speedup or universal timeout-elimination claim. Deterministic
  dropped-first-ACK test completes at 1.140s after one resend; no third write. Later polls stay fresh.
- Candidate/installed automatic recovery 11.828/12.486s, each with a scan miss; all 33/33 samples
  locked at 600 MHz and camera-ready. Installed abstract-input triple unlock, nonblank LCD at 1000 MHz, and relock at 600 MHz
  and status pause/resume pass through physical LCD; contacts not actuated. No film/image commands.
- Normal source gates: 322 Rust tests plus 1 doctest, 1773 Bridge tests (27 existing warnings), Ruff, mypy (67 modules), formatting,
  production workspace Clippy/header drift/strict docs pass. Independent core suite (196 tests) and Pi ARM
  8 model-query and 47 device tests pass. Source and hardware adversarial review; evidence in plan084/assets.
- Final normal 18:54:58 EDT: PID34446/manager34001 active, NRestarts0, connected, 600 MHz,
  43.470°C/throttle0x0/GPIO24low/GPIOv2/hotspot/USB/FTP220/200 healthy; clean manifests and
  loaded native hashes match b2b6c8c. Final normal log has no warnings/errors/panics. Full current
  boot service review: 9294 records, 134 historical matched messages retained, including two
  earlier native panic episodes. Independent final-health/log review passed.
- Observer/drop-in/socket/candidate library/ARM binary/health script removed; normal service restored.
  Remaining setup costs: advertisement/GATT variation, BLE handshake and initial watch registration.

## Initial status handoff deployed, 2026-10-13

Plan083: clean Python **83473d4**, native **ffe637e** installed. FFI SHA256
`88974b10dd285f4eb3b31a08fc8af68756d3612e5cdf8910a1c719b74e265e82`; CLI
`e720bef273ebfca85b96743d85b9c77bb99dd8fcce13fc91e9d3ba52b15f7d79`.

- Fresh connect returns its single initial status: **6→3 commands**; established polls still
  make3 fresh hardware requests. No status cache or TTL. Older libraries retain fallback.
- Measured reconnect tail514.530→3.515ms candidate/5.448ms installed (~0.51s removed).
  Observed total recovery12.706/7.069/6.918s, one per variant; baseline had an extra failed
  scan, so total time difference cannot all be attributed to this change. Startup watch
  registration retains about223ms overhead. MTU247/payload236 preserved.
- All35/15/16 recovery samples locked600/camera-ready; installed later periodic polls fresh.
  Same-button triple unlock/nonblank1000/relock600 and statuspause/resume pass through
  actual controller/physical LCD; contacts not actuated. No image commands/film used.
- Baseline/candidate startup model-query timeout each recovered automatically and is retained;
  installed observer log zero warnings/errors/panics. Source gates and independent source/
  hardware adversarial review pass;1773Bridge/308Rust+1doc/App156/PiARM23+2 lifecycle cases.
- Finalnormal18:15:40EDT PID31925/manager31549 active/NRestarts0, connected,600MHz,
  45.084°C/throttle0x0/GPIO24low/GPIOv2/FTP220/200/hotspot/USB healthy, clean manifests.
  Normal startup repeated model-query timeout (2warnings), recovered automatically; no native
  panic. Fullboot8078service records reviewed, historical faults retained.
- Observer/drop-in/socket/candidate source/library/archive removed; normal service restored.
  Evidence in docs/assets/bridge-audit-083/ and plan083. Next setup work: advertisement/GATT
  variance, BLE handshake, model-query timeout recovery and initial watch registration.

## Earlier initial-status checkpoint, before power-on, 2026-10-13

At this earlier checkpoint Plan083 clean source **ffe637e** was implemented/reviewed and
**not deployed**. The Bridge retained
validated Plan082 source82f6097/native d23d3b81…f3d38. Selected Printer is not advertising;
requested power-on is needed for baseline/candidate/installed no-film timing and freshness tests.
No successful hardware command-count/speed claim for083. Source gates1773Bridge/308Rust+1doc/
App156, independent Bridge55/FFI23/corePrinter23/cleanup1, PiARM23+2 connect/lifecycle cases pass.
No status cache; atomic fresh-connect handoff, later polls remain hardware reads.

Baseline observer/drop-in/socket and unit binaries removed, normal service restored. Candidate
archive/library remain inactive under /var/tmp; host baseline artifacts saved for comparison.
No film/image commands. See docs/assets/bridge-audit-083/source-review.json and plan083.

## Discovery and connection setup, 2026-10-13

Plan082 / `docs/assets/bridge-audit-082/`: clean **82f6097** Python/native deployed.
FFI SHA256 `d23d3b817108b0243ab474af2970f1fd7748431c317af64b38bc4c5eb94f3d38`,
CLI `b3fcffc0c0d1a351e2cdafbdddee065393434cb1c01f56e6fa1239874e9502dc`.

- Guarded bond cleanup precedes the first reconnect scan after disconnect events; live links
  are preserved. Fresh single-adapter D-Bus gate avoids CLI info, with conservative fallback.
  Owned CLI children kill/reap on cancellation; print handoff joins mutators or aborts safely
  at6s, replacement polls retain cleanup ownership and continue after child cancellation.
- Read-only MTU lookup overlaps the unchanged200ms settle floor/1.2s budget; default/missing
  MTU refreshed after settle. All real payloads remained247/236; no print bytes/pacing/ABI change.
- Localized licensed BlueZ dependency patch fixes receiver/filter cleanup races and native
  panic. Plan081 zero structured errors missed a stderr panic at09:41:09; full log scan now
  includes panic/unwrap/thread messages. Historical faults retained, not presented as clean.
- No-film status-only recovery: baseline13.141/19.211s, candidate7.990/8.690s, installed12.632s.
  All accepted rows locked600/camera-ready. Installed still had one scan miss; candidate3
  transient missing characteristic recovered by existing rebond. Radio varies; no universal
  speedup. CPU3×20s means0.417→0.500% onecore, child0, all600; no energy/CPU improvement claim.
- Independent review resolved unscoped negatives, subprocess/recovery/print/cancellation races;
  337 targeted tests pass. Normalhooks1763, hostRust298+1doc, App156, PiARMcore197/vendor51+4
  privatebus/FFI39, Ruff/mypy67/format/host+LinuxstrictClippy/header/docs pass. No film/image
  commands; printquality not physically retested. Abstract-input LCD tripleunlock/relock and
  statuspause/resume pass; contacts not actuated. Audit /tmp ENOSPC retained/excluded, fixed
  by removing owned test binaries and using /var/tmp for later unit executables.
- Final normal10:43:26EDT PID29062/manager28530 active/NRestarts0, connected,600MHz/GPIO24low,
  45.084°C/throttle0x0, GPIOv2, hotspot/USB/FTP220/200 healthy, source/native hashes match.
  6642currentboot service records reviewed; finalnormalzero warnings/errors/panics. Rawlogs
  private; no kernel claim. Observer/drop-in/socket/source/lib/testbinary fixtures removed.
- Next: variable advertisement/GATT export,1.3–1.5s BLE handshake, duplicate initialstatus
  (~0.43–0.54s then Bridge status again). Preserve freshness before caching/reusing status.

## Bluetooth disconnect events, 2026-10-13

Plan 081 / `docs/assets/bridge-audit-081/`: clean **ec960c2** Python source installed;
CLI/FFI unchanged from plan 080 (FFI SHA256 b67842fe…bb06a). Shared BlueZ bus events wake
serialized status/recovery; ten-second periodic fallback remains. Watch once per connected
episode, coalesce events, authenticate sender/path/selection/generation and own cleanup.
No print/image replay, new polling, config/ABI change or clock-tier change.

- Aligned baseline first fetch 9.885 s after disconnect request. Final candidate / installed
  signal-to-fetch **261.538 / 261.527 ms**, including intentional 250 ms recovery gap.
  Full recovery observed by baseline 12.401 s, candidates 19.558 / 13.963 s, installed
  **12.888 s**. Target visibility/handshake vary; no universal total-speedup claim.
  All accepted samples locked at 600 MHz/camera-ready; rejected wake-confounded baseline retained.
- Connected idle CPU (3×20 s at 600 MHz) baseline mean 0.900%, candidate 0.383% of one core;
  zero child CPU. Elevated first baseline and separate starts prevent universal energy/CPU
  reduction claims. No observed increase; no per-poll watch IPC.
- Independent review fixed stale alias selection, repeated failed-watch IPC/warnings, and
  model-metadata callback rejection; 36 independent targeted cases passed. Full normal hooks
  1724 tests, agent 48, controller/runtime 288, Ruff, strict mypy67, format and strict docs pass.
- Eleven kernel GPIO mock-to-real LCD/CPU cases passed, including nonblank wake/1000 MHz,
  same-button triple unlock, debounce/held/rapid presses and ten-second expiry to dark600.
  Physical contacts not actuated. Printing serialization/cancellation tested locally;
  status-only hardware tests used **no film** and do not claim a new physical print-quality test.
- Final normal snapshot 09:45:22 EDT: PID25926/manager25301 active, NRestarts0, connected
  Printer, 600 MHz/GPIO24 low, 42.932°C/throttle0x0, hotspot/USB/FTP220/200 healthy,
  GPIOv2, zero warning/errors. Reviewed4300 current-boot service records, 41 final-normal
  records; 99 historical warning/errors retained/classified. Raw journals private.
  Observer/drop-in/socket/source overrides and owned GPIO mock removed; saved photos/config
  unchanged. Runtime and native hashes match; battery last5%, film0. No battery-duration claim.
- Next latency candidate: remaining discovery/handshake after link loss. Preserve target
  visibility/reconnect reliability; current results do not justify reducing safe gaps further.

## Live stale-link recovery acceptance, 2026-10-13

Final follow-up: after the clean 08:33 capture, Printer advertisement stopped at
08:37:01 EDT (cause unobserved), producing two one-time loss warnings. Same PID 23036
handled retirement/bond cleanup and resumed search, keeping networking and 600 MHz
healthy. User power-on restored fresh Square film 0 / battery 20% at **08:43:12.386 EDT**
without manual Reconnect or service restart. Power-on-to-ready latency was not measured.
Final snapshot records both earlier warnings and successful recovery; source 79b53e9 is
clean, native hash unchanged. No film used. See `power-return.json` and final health.

Plan 080 live follow-up completed after Printer power-on, using the reviewed **d8cee35**
source/native binaries. Production code is unchanged. Evidence is in
`docs/assets/bridge-audit-080/live-comparison.json` and the detailed captures.

- Normal installed firmware automatically reconnected to INSTAX-52006924, reporting Square
  film 0 / battery 20% at 08:18:20 EDT. No manual Reconnect action or film was used.
- Two forced Device1 disconnects recovered automatically, **observed by 19.867 / 11.610 s**.
  All sampled states stayed locked at 600 MHz and camera-ready. These are harness elapsed
  times; actual fresh-status timestamps were 19.780 / 11.561 s after disconnect request.
- Historical baseline FFI rebuilt from 4c9e28b exactly matched its prior SHA256 fdd47e…5973.
  Full baseline missed the 100 s deadline then recovered in the same PID at 104.242 s.
  Poll phases and target visibility differ; no universal speedup or radio-cause claim.
- Old cache reused twice, then fresh attempts started at 39.235 / 69.237 / 99.240 s.
  Installed fresh attempts began at 9.849 / 9.390 s, validating retirement/retry behavior.
  Direct native failed-status getter remained 1 on baseline and became 0 on installed.
  Successful ACKs won both direct disconnect races; one-second missing-ACK checks remain
  controlled-test evidence. Failed-write latency was 2.793 / 6.035 ms, not an improvement.
- Initial baseline scan misses and postdeadline state retained. Independent evidence review
  passed with timing/stale-doc clarifications; no additional correctness finding. All
  successful direct status reads showed film 0 / history 68; no image/print commands.
- Final normal PID 23036 / manager 20393 active, NRestarts 0, 600 MHz / GPIO24 low,
  42.932°C / throttle 0x0, hotspot/USB/FTP healthy, Printer connected with fresh status.
  Reviewed 3697 service journal records; normal PID 39 records / zero warnings or errors.
  Earlier controlled baseline/harness faults remain; raw journals private. No kernel claim.
- Observer/drop-in/socket and owned baseline fixtures removed; saved photos/config unchanged.
  Shared build artifacts restored to candidate hashes / clean manifest after baseline rebuild.
  The remaining latency is mostly waiting 9.4–9.8 s for the next status poll. A disconnect
  event on the shared BlueZ bus is the next candidate; idle polling need not increase.

## Stale-link detection and recovery retries, 2026-10-13

Plan080 / `docs/assets/bridge-audit-080/`: clean **d8cee35** source/native installed.
FFI SHA256 `b67842fed5ce50b8b9389acdf7f55c5d2a7ad8859f30d5ec460307260dcbb06a`,
CLI `1d549bc46df1c5819abb24a1f28d830f4b8d7b05929eb55a2adb37228c07c068`.

- Missing replies trigger bounded native connectivity checks after1s; confirmed closure
  closes the old session. Unknown state preserves original10s response deadline. Normal
  ACKs and idle sessions add no checks; no fragment/image/execute replay or ABI change.
- Cheap FFI getter exposes terminal closure; old keepalive exits locally. Python discards
  confirmed-closed cache on first failure and resets failure streak after a fresh connect.
  Two prompt retries after an online drop have250ms gaps, then ordinary offline cadence.
  Startupabsence and Restartprinter pacing preserved. Polling waits for both bond and
  silent-link cleanup, fixing the independently reviewed recovery/connect overlap.
- Gates: host291+1doctest,App156,Bridge1689,PiARM190+39,Ruff,mypy67,headerdrift,format,strict
  docs and normalhooks passed. ProductionLinuxClippy strict; four pre-existing test-only
  lint allowances. Final independent review and16selectedcases passed.
- Eleven kernel-to-UI cases passed for baseline and candidate on physicalLCD/CPU, including
  tripleunlock/nonblankwake/10sexpiry. Contacts not actuated. OfflineCPU2.550→2.600% onecore
  (3×20s each), zerochildCPU; unchanged within variation. Startupofflinecadence ~30s.
- Printer absent; baseline readiness100stimeout retained. Live checks were pending in this initial session; the power-on acceptance above completed
  them. Controlled timer tests remain separate from physical measurements. No film used.
- Reviewed3226current-boot service records. Corrected temporary observer AttributeError
  caused eight restarts; initialUIsocket and awakehealth attempts retained. Final normal
  PID20395/manager20393 active/NRestarts0,600MHz/GPIO24low,throttle0x0,FTP220/200,Wi-Fi/USB
  healthy,GPIOv2,caches0,no appWARNING/ERROR. Both clean manifests/source hashes match.
  Test observer/drop-in/socket/source/library/mock/ARM executables removed; raw logs private.

## Native Bluetooth discovery and agent recovery, 2026-10-13

Plan079 / `docs/assets/bridge-audit-079/` records the native discovery benchmark,
adversarial review and real-device recovery tests. Native **a8b637c** and Python
repair **78d771f** are pushed and installed cleanly. Native FFI SHA-256
`fdd47eaddb35f630534b5f250c8810515c5c14ac0ad5a68fa46a83f46f185973`,
CLI `3744699d034ab1870e563bbca2c3aad88aff43f0485097ae6bf929595d051cee`;
agent source SHA `7f4c9dfb8864a457c6273d9082755841aa8615c0e4ce51b908fb8068b25e9b33`.

- Native discovery uses fresh bulk metadata to skip definitely unrelated handles;
  actual/uncertain Printers retain their old properties, Android and liveness checks.
  Missing/malformed/unavailable data falls back; no metadata cache or scan-cadence change.
- Separate36-second offline traces: baseline12bulk/225individual property reads;
  candidate15btleplug+14prefilter bulk/zeroindividual reads. Ambient/cached devices vary.
  Native five-second search mean CPU **0.526→0.465s**, elapsed **5.413→5.375s**,
  stable descriptors after initialization and scanning stopped after all six trials.
- Offline dark600MHz CPU means **1.876→1.266%** of one core, three30-second intervals
  each, zero childCPU. Observed reduction32.5%; separate process starts/ambient BLE
  prevent universal CPU, energy or battery-life claims. Every accepted/rejected attempt
  is retained. Baseline/candidate ELF compiler/linker versions match.
- Daemon restart testing found lost pairing-agent registration, ending in a real
  `Does Not Exist` cleanup error. Repair tracks owner changes and late selected-interface
  readiness on the same bus, uses unique-owner/generation checks and owns cancellation
  cleanup. No idle polling. Three candidate restarts restored registration in
  **1.000/0.774/0.782s**, same PID/bus and locked600/camera-ready. Installed normal
  restart passed in **1.082s**, samePID17914, 22clock samples all600MHz. These are
  agent-registration timings, not Printer-reconnect timings.
- Live power-return reconnect worked; later an actual agent authorization and Printer
  status succeeded after candidate daemon restarts on the same process. Forced
  Device1 disconnect exceeded65s then recovered; the initial daemon test exceeded180s.
  Do not infer radio causes. Cached-session detection, command-lock/timeouts and retry
  cadence remain the next speed bottleneck. Printer was absent at final normal capture.
- Gates: host Rust282, Pi ARM unit183 including14discovery cases, App156, Bridge1672,
  focused Python83, Ruff, strict mypy67files, header drift, formatting and strict docs.
  Linux library Clippy strict; test-target Clippy allows two existing1.97test-only lints.
  Independent review clear. Eleven kernel-to-UI cases passed before/after agent repair;
  physical button contacts not actuated. No film or image/print commands used.
- Normal installed services PID17914/17912 active/NRestarts0,600MHz/GPIO24low,
  hotspot/USB and FTP220/200 healthy, throttle0x0, zero appWARNING/ERROR. Source/artifact
  hashes match. Temporary observer/drop-in/socket and GPIO mock removed; saved photos
  and configuration unchanged. Raw journals remain private; service-log review only.

## Idle network/recovery lookup acceptance, 2026-10-12

Plan 078 / `docs/assets/bridge-audit-078/` audit the remaining idle work and full running logs.
Clean **3052ef5** is pushed and installed; all five reviewed production hashes match. Native
FFI remains **dedfdb2** / SHA-256
`5622ca8d2cce25f9437ddaad97771a3c4e29fee42e226cfb9444b73fcb9de3b8`.

- Fresh bounded Linux rtnetlink replaces recurring address `ip` launches, preserving scope,
  prefixes, administrative UP, dormant readiness and existing portable fallback. No cache or
  poll/recovery cadence change. Physical-interface parity and seven isolated namespace cases
  passed, including aliases, point-to-point, down-retained addresses and concurrent snapshots.
- Silent-link recovery reads fresh BlueZ objects through the existing agent-owned bus, with
  Address/Alias/default-adapter semantics and CLI fallback. Disconnect rules and mutations are
  unchanged. Review caught a new blocking constructor in an undeployed draft; shared-bus reuse
  resolved it. Cancellation preserves the shared agent and concurrent calls.
- Direct query medians: network **13.822→3.590 ms**, Bluetooth **616.758→22.851 ms**. No discovery
  children in native queries; standalone diagnostic FD count 8→8, no agent registration or
  mutations. These are direct-query measurements, separate from the runtime benchmarks.
- All CPU sets are three 30-second dark / 600 MHz / offline samples. Same PID combined / old
  lookups / combined repeat: **1.576 / 1.998 / 1.754%** of one core including children. Pooled
  candidate mean **1.665%**, 16.7% below old lookups in those samples. Every row retained,
  including the initially higher network-only candidate and baseline/startup differences.
- Installed samples averaged **2.043%** process CPU, **zero child CPU**, 18 network / 2 D-Bus
  reads without lookup CLI/fallback during timing. Shared FFI/executor and Tokio workers
  dominate (~82–85%). Native discovery varies; no general installed total CPU or energy
  improvement claim. Scan/keepalive timings and print/native code remain unchanged.
- Installed eleven kernel-to-UI cases passed with real LCD/CPU, same-button triple unlock and
  10-second abandonment. Physical contacts not actuated. wlan0 down with retained IP removed
  receive readiness and automatically recovered in **28.402 s**, same PID13410, all samples
  locked at600MHz. One fresh ip fallback during interface churn; precise cause not inferred
  from INFO logs. Printer offline; no film or live Printer reconnect/airtime test.
- Gates: Bridge **1647**, focused **221**, Ruff, strict mypy **67** files, touched format,
  strict docs and normal hooks passed. Independent combined review has no remaining blockers.
- Full-boot logs retain historical real faults already recorded in plan076: old BLE timeouts,
  deployment-stop worker-stuck exit and removal timeout. Current normal runtime is clean.
  Final normal PIDs **13865/13408**, active/NRestarts0, kernelGPIOv2,600MHz/GPIO24low,
  42.932°C/throttle0x0,Wi-Fi/USB up,FTP220/200,caches0,zero appWARNING/ERROR. Temporary
  observer/drop-in/socket and owned GPIO mock/namespace fixtures removed; raw logs stay private.
- Final independent log capture: 2016 records. Installed validation 83 INFO / no warnings or
  errors; restored normal 28 INFO / no warnings or errors. One temporary observer connection
  reset ERROR after its client disconnected is retained in evidence. Observer removed; no new
  production fault, service failure or automatic restart. Service logs only, no kernel claim.

## GPIO input acceptance, 2026-10-12

Plan 077 replaces input alert polling with a kernel GPIO v2 event descriptor, 50 ms debounce
and asyncio readiness. Clean **2ccdfa6** is pushed and installed; source hashes match the
independent review. Native FFI remains **dedfdb2** / SHA-256
`5622ca8d2cce25f9437ddaad97771a3c4e29fee42e226cfb9444b73fcb9de3b8`.

- Actual dark / 600 MHz / offline Bridge CPU, three 30-second samples per condition:
  baseline **10.012%**, candidate **1.710%**, forced legacy **10.900%**, installed **1.898%**
  of one core. Installed idle process CPU is **81.0% lower** than the original baseline.
  Whole-system and child counters are separate; no energy or connected workload claim.
- Paired kernel mockup checks passed all eight mappings, bounce, stable 75 ms presses,
  held buttons, triples, distinct Select identities, bursts and lifecycle. Stimulus-to-queue
  p95 **52.47→56.38 ms**, including 50 ms debounce; candidate stable-event-to-queue p95
  **0.583 ms**. Physical switch contacts were not actuated. Simulated pull-up resets the
  startup level, so held-at-claim policy is unit-tested separately. Legacy lifecycle rerun
  applied callback detachment after a retained-callback failure; idle timing was unaffected.
- Eleven kernel-to-production-UI cases passed before and after deployment with real LCD/CPU:
  nonblank wake, held once, key/joystick identity reset, same-button triple unlock, rapid
  75 ms presses, 10-second abandonment to dark / 600 MHz, and inactivity after mock detach.
  Printer offline / film 0; **no film used**. Print/native code and CPU tiers unchanged.
- Independent review found no blocking candidate issues; 68 focused tests and separate
  descriptor checks passed. Full Bridge **1571**, Ruff, strict mypy **66** files, touched
  format, strict docs and normal precommit passed. Evidence: `docs/assets/bridge-audit-077/`.
- Normal service restored: PIDs **10928/10536**, active / NRestarts 0, native GPIO v2 startup,
  no input failure/fallback, 600 MHz / powersave / GPIO24 low, 44.546°C / throttle 0x0,
  caches 0, Wi-Fi/USB up and FTP 220/200 via the Pi hotspot address. This FTP probe measures
  server health, not Wi-Fi airtime or upload. Localhost and Mac USB probes were rejected by
  the existing hotspot/USB-admin-only policy; both warnings are controlled test events.
- Temporary observer, drop-in, socket, source, scripts and owned mockup module removed.
  Saved photos/configuration and native library hash unchanged; no dependency patch or extra
  package. Legacy fallback retains an inherited in-flight callback teardown limit; default
  kernel input avoids that thread. No electrical-contact claim.

## Live runtime acceptance, 2026-10-12

Plan076 deploys the plan075 runtime audit and adds fixes found in the full live logs:
inactive Linux BlueZ cache records, disconnected startup bonds, overlapping rebond/connect,
and wlan0-down readiness with a retained IPv4 address. Clean runtime **8bbbd88** is pushed
and installed; native source **dedfdb2**, FFI SHA-256
`5622ca8d2cce25f9437ddaad97771a3c4e29fee42e226cfb9444b73fcb9de3b8`.

- Reviewed12,693 retained service records across8boots plus403initial/458final current-boot kernel records.
  Clock sync crossed midnight UTC; correlate by boot/PID/monotonic time. Historical shutdown
  errors and controlled deployment/fault-injection events are distinguished from new faults.
- Real framebuffer/CPU, GPIO-equivalent queue inputs: same-button triple unlock, different
  identities sharing Select, immediate nonblank prompt/home and10s abandonment passed.
  Awake1000MHz, locked600MHz. Electrical switch contacts were not actuated.
- One user-selected **DSC02832.jpeg** production FTP print at811d51f: **19.779s** upload start
  to Bridge completion, **15.238s** native download. Captured exact104,552-byte/800×800/quality88
  JPEG/RGB reference,58indexed ACKs and onePrintImage. Film1→0; history67→68 on later fresh
  connection. Job sampled1000MHz; locked600MHz resumed. Saved Vivid/saturation1.5 and neutral
  Correction preserved. Subsequent network-only8bbbd88 keeps identical print/native code.
  Camera Wi-Fi airtime, physical/developed-film quality and mechanical time not measured.
- Forced BlueZ disconnect automatically recovered in**44.340s**, same Bridge PID3981,
  locked600MHz, fresh status and authoritative Connected=true. No manual connect/restart.
- wlan0-down/retained-IP probe failed before the network fix and was manually restored.
  The fixed watchdog restored AP/readiness in**32.706s** while locked600MHz with Printer
  offline. After Printer power-on, the combined repeat passed in **32.672 s**: all **31**
  samples locked at **600 MHz** with authoritative Printer Connected=true. Four successful
  status observations, maximum age **9.543 s**; film **0→0**, history **68→68**. No film used.
  Evidence: `docs/assets/bridge-audit-076/wifi-recovery-connected.json`.
-30s dark/offline process sample:3.1CPU seconds /10.33% of one core at600MHz. Largest observed
  cost was a native GPIO thread (6.9% lifetime CPU): ppoll on8GPIO-line FDs, mostly500µs
  timeout. No GPIO/dependency timer changed; electrical latency/bounce/hold checks are needed
  before changing it. No energy/battery-duration or before/after efficiency claim.
- Gates passed: Bridge1551, Rust282 incl.doctest, App156, Ruff/mypy65source files,
  touched format, Rust build/fmt/Clippy/header drift, strict docs and normal hooks. Pi runtime
  has no pytest; no test dependency installed. Sanitized evidence under
  `docs/assets/bridge-audit-076/`; raw journals/photo captures stay outside Git.
- Temporary observer/drop-in/scripts and owned photo copies/capture removed. Normal service
  After the connected repetition, normal PIDs **7530/5125** active, NRestarts0,
  **600 MHz**/GPIO24low,45.084°C/throttle0x0,FTP220/200,USB/hotspot up,caches0.
  The normal service automatically reconnected with fresh film0 status; authoritative
  Printer Connected=true at the final health sample. The test used installed cee3755,
  a documentation successor to8bbbd88 with identical production code/native artifacts.
- Final kernel review:23brcmfmac vendor-IE -52 records around startup/AP reconfiguration or
  injected interface-down, plus one earlier hci_conn_timeout WARN before the startup/rebond
  fixes. No repeated HCI WARN in subsequent captures; kernel root cause not established.
  Driver/firmware maintenance remains a follow-up; no OS upgrade or driver-warning fix claimed.

## Offline runtime correctness audit, 2026-10-12

The Pi is disconnected for other work. Plan075 / `docs/assets/bridge-audit-075/` record a
local audit of saved runtime logs and current code. Candidate changes are tested locally;
**not deployed**. The last installed native artifact remains f574445 / FFI SHA-256
`b601ec6a8b14138617ebbae5e5c74b892bb461ee2d2747dbfc6ed181f253bacb`.

- Cancelled FFI worker errors preserve cancellation and serialization. Completed worker/sender
  TimeoutError is not mistaken for a stuck operation or process-restart deadline.
- Superseded status results cannot change counters/state or schedule recovery. Bond-reset
  cancellation propagates; retired status tasks remain owned through shutdown cleanup.
- Status logs report first/change/recovery and five-minute heartbeat. Unchanged status/routine
  scans are DEBUG; expected absence is INFO once; genuine errors remain warnings.
- Dark maintenance waits up to5s with expiry deadlines and immediate display-wake rescheduling.
  Hidden About collectors do not start. Awake cadence, CPU tiers, network/FTP/status cadence,
  image data, protocol delays, config/schema and App/iOS contracts are unchanged.
- Offline saved-log replay:25 observations still make25 fetches, with1INFO/24DEBUG. Not a
  hardware CPU/energy measurement.18 new regression cases; Bridge1542 tests, Ruff and mypy65
  passed on macOS/Python3.13.9. Full current journal and hardware smoke await Pi availability.

The user now prioritizes system correctness and operational efficiency over battery-duration
benchmarking. No discharge test is scheduled or required for this audit.

## Chunk-pacing selection, 2026-10-12

Plan 074 selected **25 ms** intermediate pacing for Square/Linux/236-byte/indexed-ACK sessions,
with final **150 ms** and pre-execute **1000 ms** unchanged. Legacy/unknown/smaller/conservative
connections and other models/platforms retain their model baseline. Separate bounded pacing
fallback and full-transfer guards handle uncertain errors/cancellation without replay; known
external film/cover/battery rejection requires reset without falsely penalizing pacing.

- Twelve no-film sweep transfers plus four reversed fresh-connection repeats passed exact JPEG,
  RGB, indexes, padding, checksums and End/Cancel ACKs. Film **1**, history **67** unchanged.
- Paired mean **22.266 → 15.349 s**, saving **6.918 s / 31.1%** for download/end/cancel. This
  excludes camera upload, processing/review, pre-execute and mechanical/developed-film time.
- Shared production-loop candidate passed two runs **14.875 / 14.850 s**, exact 56×25 ms plus
  final 150 ms, no LED/PrintImage/reset/shutdown. All samples 1000 MHz / throttle 0x0.
- One setup attempt lost its connection before model/Data (HCI reason 0x3e). No image command
  ran; normal Bridge recovered automatically. Harness now verifies prior link closed before
  each controlled fresh trial. Failed setup is recorded, not treated as a timing sample.
- Independent final review and pinned timing/model/fallback/cancellation tests passed. Offline
  baseline gates were Rust278, Bridge1524, Pi52, build/fmt/Clippy/header drift and strict docs.
  Clean selected code **f574445** is pushed and installed. FFI SHA-256
  `b601ec6a8b14138617ebbae5e5c74b892bb461ee2d2747dbfc6ed181f253bacb` matches
  the official clean ARM release manifest. Both services active / NRestarts 0, FTP 220 / NOOP
  200, correct USB/hotspot, throttle 0x0 and zero working caches. After 60 seconds idle:
  screen off / GPIO24 low, powersave **600 MHz**, Wi-Fi/FTP operational and Printer connected
  with fresh film1 / battery35 status following the powersave transition.
- The post-deploy same-source shared-core no-film probe passed **14.950 / 15.104 s**, each
  56×25 ms plus final 150 ms, exact JPEG/RGB/padding/checksums and 114 indexed ACKs total.
  Actual installed FFI passed two fresh status/disconnect cycles: MTU247 / payload236,
  film1/history67, RC0, authoritative closed state and physical Disconnect Complete,
  **2.769 / 2.206 s**. Normal Bridge automatically reconnected. Final services/PIDs unchanged,
  Wi-Fi/FTP ready, throttle0x0, caches0. Final independent review has no unresolved issue.
  Transfer probe uses the shared core from the installed source; installed FFI was checked
  with status/teardown, not a film-consuming print call.
- The Printer stopped advertising during build; power-on resolved final validation. An absent
  BlueZ cache aborted a temporary harness precheck before discovery/image commands; fresh
  discovery is now permitted when the cache is absent. Initial disconnected health remains
  recorded separately. No production-source change or film use resulted.
- Extended idle observation: fresh polls continued every 10 seconds through **14:47:03**, over
  three minutes after the 600 MHz transition. At **14:47:13** the Printer was unavailable,
  about 299 seconds after reconnect. This is consistent with Square's documented five-minute
  idle auto-off ([manual](https://instax.com/square_link/assets/pdf/manual_naen.pdf)); physical
  power-light state was not recorded before the user powered it on again. At that observation:
  Printer offline, Bridge still 600 MHz,
  Wi-Fi/FTP ready and services unchanged. Earlier connected checks remain valid. No evidence
  of a pacing regression: idle support-info handling is unchanged; the bond reset followed
  disappearance. These checks do not establish indefinite idle Printer availability.
- User powered the Printer on again. The running Bridge automatically discovered it at
  **15:33:47** and received fresh film1 / battery35 status at **15:33:50**. Screen remained
  off / GPIO24 low and CPU **600 MHz / powersave**. Wi-Fi/FTP ready, same service PIDs13234
  /12101 and NRestarts0, throttle0x0, no working caches. No Bridge restart, unlock, direct
  FFI probe or image command was needed. This verifies recovery after the extended offline
  period; elapsed time from physical Printer power-on was not measured.

## MTU-aware Bluetooth transport, 2026-10-12

Clean final code **`a24b8b7`** is committed, pushed and deployed with new arm64 FFI/CLI. Plan 073 and
`docs/assets/bridge-audit-073/` record the paired physical prints and no-film crossover.

- Linux discovers the exact connected Instax write MTU once per connection with a bounded
  query. Production ceiling **236 bytes**; unknown/non-Linux fallback **182**, known small
  MTU clamped. Protocol/JPEG bytes, orientation, ACK ordering and 150 ms / pre-execute waits
  unchanged. No FFI ABI, config, sync contract, App/iOS UI or SD cache change.
- Full production FTP paired prints of user-selected DSC02825.jpeg, saved Vivid/neutral
  Correction: 182 **27.934 s** versus 244 **28.375 s** start→Bridge completion; native download
  **21.837→22.724 s**. Same-Pi FTP excludes camera Wi-Fi airtime and mechanical/development time.
  244 had 20% fewer GATT writes but was slower, so it is diagnostic-only.
- Pi controller LE buffers are 27 bytes with no Data Length Extension support. Full Square
  packet costs 70 HCI packets at 182/236 versus 75 at 244. Two no-film rounds per size on one
  connection: means **182 21.896 / 244 22.784 / 236 21.778 s**. Small 0.117 s improvement, not
  a large demonstrated full-print gain. Remaining protocol waits/controller scheduling dominate;
  SD cache does not address this bottleneck. No battery-energy or radio-retransmission measurement.
- All transfers used identical 102,846-byte / 800×800 / quality 87 JPEG and decoded RGB hashes,
  exact ordered chunks/ACKs/checksums/padding. User confirmed second physical film upright,
  unmirrored, same colour/detail. Film 3→2→1. Crossover contained zero PrintImage commands,
  film 1/history 67 unchanged. All-model orientation/bytes covered locally; only Square physical.
- Crossover completed all data/counters, then teardown timed out before native JSON emission.
  Retained measurements were independently reconstructed from progress/HCI with that failure
  explicit. Moved physical disconnect ahead of state queries, added a close/reset marker before awaits,
  cancellation-safe recovery and JSON retention. Fresh reset skips the stalled preliminary
  query. No uncertain packet/job replay; only actual enlarged-write uncertainty downgrades size.
- Three subagents implemented, tested and reviewed. No remaining P1/P2 review issue. Rust
  **251 tests**, build/fmt/Clippy/header drift, App **156 tests**, strict docs and normal
  pre-commit passed. **51** independent transport/diagnostic/history tests passed on real Pi arm64.
- Hardware/OS unchanged: Pi Zero 2 W / ST7789 / X306 2300 mAh, Debian 13.2, kernel
  6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17, Instax Square INSTAX-52006924.

Installed FFI SHA-256 `3c283840887b985c4a21dfabfb0af418f4615516049074fb57ec92d8c205b204`;
native and deployment manifests record clean `a24b8b7`. Both services active / NRestarts=0,
hotspot/USB addresses correct, FTP 220 / NOOP 200, throttle 0x0 and zero working caches.
Temporary candidate-library override removed. Final screen-off state: powersave **600 MHz**,
GPIO24 low, Printer connected with fresh status, services unchanged after probe restoration.
Temporary probes, raw captures and duplicate test uploads removed; original user photo retained.

Two status-only cycles verified physical disconnection and fresh reconnect: D-Bus replies took
**2.473 / 2.309 s**, with two HCI Disconnect Complete events and unchanged film. This confirmed
BlueZ's delayed teardown exceeded the old deadline. Linux FFI now allows eight seconds; short
query/write/CCCD budgets remain unchanged. Square history decoding is corrected in core and
Python fallback, preserving the public u16 contract with explicit malformed/overflow failure.

The installed FFI passed two cycles: MTU **247**, payload **236**, conservative mode false;
film **1**, history **67**, disconnect return code **0**, authoritative closed state at
**1.987 / 2.133 s**. HCI confirms two Disconnect Complete events and no Download or PrintImage.
The normal Bridge then automatically reconnected with fresh film 1 / battery 50% status.
Bridge **1,524 tests**, lint, mypy (65 files) and touched-file formatting passed. Full formatting
reports 16 untouched baseline files. No further film consumed.

## Live HIF-to-Printer benchmark, 2026-10-12

The user powered on INSTAX-52006924; the installed **`7249d4e`** runtime automatically
reconnected with film 4 / battery 65%. One real 11.26 MB saved Sony HIF was printed through
production FTP/UI/review/native BLE. No production code/settings/artifact change or service restart.
Plan 072 and `docs/assets/bridge-audit-072/measurements.json` record the measurements.

- Same-Pi hotspot-address STOR through Bridge completion: **32.005 s** (upload 0.153 s).
  This excludes camera Wi-Fi airtime and does not time mechanical ejection/development.
- Worker pipeline 5.850 s: source 5.222 / transform 0.297 / JPEG 0.331 s. Dequeue through
  JPEG-ready 6.618 s includes CPU wake/worker setup; review/UI/lookup adds 2.060 s.
- Native handoff through completion **23.151 s**: actual BLE download **21.811 s**, LED ACK
  **0.026 s**, then the existing one-second pre-execute delay, PrintStatus ACK **0.031 s**.
- Reconstructed actual outgoing JPEG is exactly the prior 102,303-byte Square reference,
  800×800 / quality 76 / no transport flip, identical JPEG and decoded RGB hashes. All 57
  ordered chunks/ACKs/padding/checksums verified. Film **4→3**, confirmed by later live polls.
- User confirmed developed film is **upright, unmirrored, and free of unusual colour or detail
  problems**. One Square photo / saved Vivid settings; no film photograph or colour instrument.
- Next target is BLE transfer: within-chunk fragment spans **10.089 s**, final-fragment ACK
  waits **2.785 s**, post-ACK waits **8.865 s** including the last chunk. Read-only negotiated
  MTU was **247**, but application fragments are fixed at 182 bytes. MTU-aware transport could reduce
  writes (10→8 per full Square chunk at 244 bytes), subject to Printer firmware/reconnect validation.
  Shorter 150 ms sleeps need separate multi-photo/model reliability tests. Neither was changed.
- During the job all 128 retained clock samples were 1000 MHz, throttle 0x0. Final services/PIDs
  unchanged, NRestarts=0, FTP listening, dark powersave 600 MHz / GPIO24 low. Temporary probes/trace/
  duplicate upload removed; original retained. FFI hash remains `8d5ee808…e5f75d` from clean `6ca7035`.
- Film 3 polling continued through 08:28:13 EDT. Printer became unavailable at 08:28:23 and then
  stopped advertising; cause unobserved. Normal Bridge reconnect/search continues. This does
  not establish indefinite radio uptime or the 16-hour battery target. Hardware/OS unchanged.

## Prepared JPEG native handoff, 2026-10-12

Clean code **`6ca7035`** is committed, pushed and deployed with newly built arm64 FFI/CLI.
Subsequent documentation-only deployment carries identical verified runtime code and artifacts.
Plan 071 and `docs/assets/bridge-audit-071/` contain sanitized benchmark, provenance and smoke results.

- Three additive FFI exports strictly validate exact model, transport-flip declaration,
  dimensions/byte limit and complete baseline RGB JPEG before Printer writes. Prepared bytes
  are transmitted unchanged; no native resize/flip/colour correction or JPEG re-encode.
- Mini Link 3 flips before final Python encoding; LCD preview reverses only that transport
  flip. All four models passed asymmetric-image installed worker/ctypes handoff checks.
  Old native builds retain their legacy file path. Cancellation retains buffer/callback/lock;
  errors never fall back to another send.
- Adversarial review caught permissive entropy recovery and replaced it with a bounded static
  TurboJPEG decode treating warnings as errors. Nine independent native tests also passed on
  the Pi. Final review has no remaining P1/P2 issue. FTP test-fixture timing/teardown was repaired
  without product changes or weaker assertions (300 stress cases passed).
- Real 11.26 MB HIF, five same-release interleaved native measurements per model at verified
  1000 MHz: median Mini **738.49 → 13.47 ms**, Link 3 **612.31 → 10.78 ms**,
  Square **943.30 → 15.56 ms**, Wide **1609.59 → 28.87 ms**. About 98% less native preparation
  time; first HIF decode and physical BLE/ejection are outside this measurement.
- All new JPEG hashes equal their Python prepared input. Square retains the existing reference
  102,303-byte JPEG, quality 76 and RGB hash; old native re-encoding produced 104,628 bytes.
  Chunk counts Mini 116→115 / Link 3 61→61 / Square 58→57 / Wide 248→242. No protocol sleep,
  persistent SD cache, swap, public config/sync API or App/iOS behavior change.
- Rust 205 tests, build/fmt/Clippy/header drift, Bridge **1,497 tests**, Ruff/format/mypy 65,
  App 156 tests, strict docs and normal pre-commit passed. Static validator adds CMake/compiler
  build requirements (NASM on x86), documented and installed in CI; no new Pi runtime package.
- Installed FFI SHA-256 `8d5ee8081dc297f9c588038410941433d3f72a5eebe9b8c5f688dad476e5f75d`;
  native manifest records clean `6ca7035`. Services active/NRestarts=0, hotspot/USB correct,
  FTP 220/NOOP 200, powersave **600 MHz**, GPIO24 low, throttle 0x0, zero working caches.
- Printer remains off/not advertising. Installed smoke uses a separate no-device process and
  real C ABI; it does not establish physical BLE/film speed, colour, connected progress or GPIO
  acceptance. No film consumed. Hardware/OS remain Pi Zero 2 W / ST7789 / X306 2300 mAh,
  Debian 13.2, kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17,
  Sony a7C II profile and Instax Square INSTAX-52006924.

## Full print-cycle and SD cache audit, 2026-10-12

Firmware code **`a7f5fc1`** was committed, pushed and deployed cleanly. **1,471 Bridge tests**,
Ruff, touched-file formatting, strict mypy (65 source files), whitespace, strict MkDocs and normal
pre-commit passed. Three agents audited receive/queue/Sync, review/UI and imaging/native states;
independent final cross-review found no actionable P1/P2 issue. Plan 070 contains the state matrix.
Subsequent documentation-only deployment carries the same verified runtime code.

- Early Sync uploads wait for outbox setup inside their cancellable source-ownership scope.
  Construction completes its handoff before cancellation; repeated outer cancellation joins
  one teardown. Failed setup shows `Sync unavailable`, retains the original and keeps Printer
  polling stopped in Sync mode. No endpoint/schema or iOS/App change.
- Print during a pending edit freezes it and reuses the matching completed JPEG. No-op edits
  stop timed printing without another encode. Superseded reviews cannot repaint over a newer
  screen. Immediate auto-model printing now overlaps preparation/connect using a cached model
  hint, with explicit override precedence and actual detected-model validation retained.
- On-Pi production UI/worker smoke using the real 11.26 MB HIF: SELECT during an active edit
  completed in **0.739 s**, two image workers / **one source decode**, matching edited prepared
  handoff (103,366 bytes, quality 80). Seeded Square status, abstract actions and NullDisplay:
  no GPIO press, native Printer send or film. Synthetic real HEIF with a 160×120 embedded
  thumbnail correctly retried its 1600×1200 primary; exact primary RGB pixels matched.
- All **seven** saved HIFs retained exact prior JPEG/RGB hashes, dimensions and quality across
  21 preparations. First preparation **3.116–5.813 s**, cached edits **0.638–0.693 s**; all
  sampled frequencies 1000 MHz, no throttling, dates present and cache cleanup passed.
- SD experiment confirmed active cache is already tmpfs. Edits averaged **0.665 s** from tmpfs,
  **0.667 s** from an SD file with warm pages, **0.876 s** after requesting file-page eviction.
  All output hashes matched. SD durable flush cost **0.245–0.259 s** outside edit timing. Keep
  the active-photo cache in RAM; persistent SD reuse would help only an older-photo revisit
  after expiry/replacement/restart and requires versioned source/model/profile keys.
- Verified services active/NRestarts=0, hotspot/USB addresses correct, FTP 220/NOOP 200,
  dark idle powersave/600 MHz, GPIO24 low, throttling 0x0, zero remaining working caches.
  Saved configuration, dependencies and native artifact SHA were preserved. Temporary probes
  and fixtures were removed. No boot, swap, protocol delay or native ABI change.
- Remaining candidates require separate measurements: native redundant JPEG re-encoding,
  optional LED ACK wait/overlap, mechanical completion and small FTP/Bluetooth lookups. Printer
  remains off/not advertising; physical BLE/film timing, new camera Wi-Fi upload, colour,
  GPIO acceptance and controlled 16-hour discharge remain unverified. Hardware/OS unchanged:
  Pi Zero 2 W Rev 1.0 / ST7789 / X306 2300 mAh, Debian 13.2, kernel 6.12.47+rpt-rpi-v8,
  Python 3.13.5, BlueZ 5.82, Bridge 0.1.17; Sony a7C II profile, Instax Square INSTAX-52006924.

## HIF flow benchmark, 2026-10-12

Clean runtime **`738a088`** is deployed (plan 069), with **1,448 Bridge tests**, Ruff,
touched-file formatting, strict mypy (65 source files), whitespace and strict MkDocs passing.
Normal pre-commit passed; independent adversarial review has no remaining P1/P2 findings.
No public config/API, App/iOS, Rust FFI or native artifact changes.

- One temporary lossless normalized HIF source is reused for later edits. It expires after
  five minutes idle and is removed on cancellation/close or photo/model/source replacement.
  Looks/edit/fit/Correction and JPEG size rules remain; large image jobs stay serialized.
- Largest real HIF (11.26 MB, primary 7008×4672): first preparation remains about **5.8 s**.
  Interleaved A/B same-photo edits improved from **5.75–5.80 s to 0.666–0.676 s**, about
  **88% less time**, with identical JPEG and decoded RGB hashes. Cache size 5,131,254 bytes.
  Source opening remains dominant: **5.115 s**, including 4.793 s external HEIF decode/PNG
  write, about 89% of profiled preparation. No first-photo speedup is claimed.
- All **seven** saved real camera HIFs passed deployed cache parity and nested EXIF date checks.
  Clock-verified first preparation **3.10–5.80 s**, edits **0.649–0.703 s**, all 621 sampled
  frequencies 1000 MHz, throttling 0x0. Cold metadata registration/read was 248 ms; later
  metadata-only reads 17–29 ms. No pixel decode is required for the date.
- Three deployed isolated FTP/controller/HIF/review trials reached the sender boundary in
  **7.106 / 7.038 / 7.035 s**, versus **7.069 / 7.033 / 7.006 s** before; fresh-photo
  performance is unchanged within variation. Review remained 1.004–1.005 s, one preparation
  per photo and exact reference JPEG reuse. Replay uses a same-Pi hotspot-address client,
  seeded Square identity/status and observer sender: no Sony Wi-Fi airtime, native BLE send
  or mechanical ejection measurement. The actual saved Printer remains off/not advertising;
  physical camera-to-print speed is unmeasured in this pass. No film consumed.
- Queued/current originals are protected from pruning. Atomic STOR reservations reject
  overlapping/owned destinations with 450; shutdown rejects uploads with 451 before teardown.
  Pins/reservations release on every completion/failure/cancel/overflow/shutdown path. On-Pi
  real socket checks passed root/incoming overlap, byte preservation, interrupted retry,
  shutdown rejection and zero remaining ownership. Protected originals can exceed the soft
  incoming storage quota while the up-to-100-job queue is held.
- Final normal service: Bridge/manager active, NRestarts=0, same post-deploy PIDs, hotspot
  192.168.8.1/24 and USB 192.168.7.1/24, FTP 220/NOOP 200, GPIO24 low, **600 MHz**,
  throttling 0x0, no remaining working-cache directories or benchmark listener. Native FFI
  preserved (SHA-256 a974372ec276fdd3e21eab28fdf5f769b68e5216c5bcdec6f63bec9568e1cc96).
  Pillow 11.3.0, pillow-heif 1.3.0, pyftpdlib 2.2.0, heif-thumbnailer/libheif1 1.19.8-1.
- Hardware/OS remain Pi Zero 2 W Rev 1.0 / Waveshare ST7789 / X306 2300 mAh, Debian 13.2,
  kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17; Sony a7C II profile,
  Instax Square INSTAX-52006924. Physical print timing/colour, GPIO acceptance and controlled
  16-hour discharge are still separate hardware acceptance work.

## Concurrency audit, 2026-10-11

Clean runtime **`473a62c`** is deployed (plan 068), with **1,406 Bridge tests**, Ruff,
touched-file formatting, strict mypy (65 source files), whitespace and strict MkDocs passing.
The normal pre-commit gate passed. No schema/API, App/iOS, native artifact or image-rule changes.

- CPU helper, FTP setup and Bluetooth start concurrently; first UI/core READY wait for maximum
  performance. Settings Refresh overlaps network/Printer lookup, shares repeated actions and
  permits navigation. Network callers share one probe; changed mode/config invalidates results.
- About version/metric reads run concurrently off loop; one cached collector. QR identity is
  independent, bounded and always real. Model detection and enabled date metadata overlap.
- New sync photo hashing no longer blocks existing-photo reads/acks. Metadata publication and
  arrival order remain atomic/serialized. Large image pipelines and Printer commands remain
  serialized for memory, film order and protocol correctness.
- Shutdown cancels UI tasks together within a fixed six-second budget. Active photo/sender,
  mutating thread and image-worker cleanup retain ownership through repeated cancellation.
  FFI cancellation holds its lock through the original five-second grace; another command
  cannot enter while its blocking call is alive.
- On-Pi controlled software probes under ib passed: two injected 250 ms Settings waits overlapped
  in **271.9 ms**, existing sync depth/get/ack completed in **3.1 ms** during held hashing,
  repeated cancellation retained the FFI lock, real synthetic JPEG worker produced 800×800 /
  4,037 bytes, and closed workers rejected new work. No Printer send or GPIO input was used.
- Reboots reached core readiness **14.429 / 14.224 s**, hotspot **18.797 / 18.620 s**;
  total systemd **17.152 / 16.991 s**. No additional measurable boot improvement versus plan 067.
  Maximum-performance mode was applied before UI; normal dark idle returned to **600 MHz**,
  GPIO24 low. Services active/NRestarts=0, throttling 0x0, hotspot FTP greeting/NOOP passed.
- User supplied fresh Printer power-on for the second reboot. Automatic reconnection yielded
  first status at **17.321 s**, film **4**, battery **65%**, BlueZ Connected=yes. Combined receive
  and Printer status were available by **18.620 s** after kernel start, excluding firmware and
  power-button delay. This resolves the prior pending boot-to-Printer check. Printer's own
  approximate 4.5-minute idle auto-off remains; no physical print-speed claim.
- Latest locked hotspot-loss test recovered IP in **29.75 s** across
  38 samples including 10 s after recovery: CPU 600 MHz, GPIO24 low, Printer
  connected, same Bridge PID and continuing film 4 / battery 65% status. Sampled checks
  establish continuity at each sample; no subsecond radio trace or film print.
- Hardware/OS: Pi Zero 2 W Rev 1.0 / Waveshare ST7789 / X306 2300 mAh, Debian 13.2,
  kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. Instax Square
  INSTAX-52006924; Sony a7C II camera profile. Physical keys, new camera upload, film colour
  output and the controlled 16-hour discharge remain separate acceptance work.

## Startup and Settings audit, 2026-10-11

Clean runtime **`8eb962d`** is deployed (plan 067). UI/FTP startup is independent of BlueZ;
Printer work waits for its agent. Network discovery and EXIF reads run off the UI event loop,
and cancelled image preparation also stops its external decoder descendants. Manager serves
available addresses and retries missing addresses with a maximum 10-second backoff.

- Print Settings now has Post, Image fit, Confirmation and Printer; Image quality and Printer
  options are below Advanced. Fit/confirmation open directly. Detailed copy is in KEY3 Help,
  read-only rows show full values, and closing Settings restores cached home. KEY3 Post,
  Looks/Correction separation and one-second review remain. Shared physical/virtual LCD path.
- **1,369 Bridge tests**, Ruff, touched-file formatting, strict mypy (65 source files), shell
  syntax, whitespace and strict MkDocs passed. Normal pre-commit gates passed.
- First controlled reboot: core readiness **14.551 s** versus **16.146 s** at `4574aa9`;
  UI first frame 14.536 s, FTP 14.204 s, hotspot receive-ready 18.889 s, manager 19.435 s.
  Second reboot core readiness 14.340 s, hotspot 18.685 s, total 16.924 s. Core improved
  1.59–1.81 s across two trials; no whole-system boot-speed claim. Splash completed
  before UI. Kernel-monotonic timings exclude firmware and the X306 power-button delay.
- 35-second dark-idle samples: Bridge CPU about 9.4% of one core before/after, 600 MHz,
  manager 0%. This does not establish improved battery runtime. Awake/job maximum remains
  1000 MHz; native artifacts, network recovery cadence and image quality are unchanged.
- Both post-change reboots had no advertising Printer; boot-to-Printer remains pending a
  fresh power-on after its documented idle shutdown. No film was used.
- Live manager late-address trial restored hotspot automatically, then rebound its HTTP
  listener without another service restart. Initial retry latency prompted the shorter cap. The final trial restored both HTTP
  endpoints in 42.91 s without another restart; final CPU 600 MHz and GPIO24 low. Bridge
  and manager active, NRestarts=0, throttling 0x0, hotspot FTP greeting/NOOP passed.
- Hardware/OS: Pi Zero 2 W Rev 1.0 / Waveshare ST7789 / X306 2300 mAh, Debian 13.2,
  kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. Saved Printer is
  Instax Square INSTAX-52006924; Sony a7C II camera profile. New upload, physical keys,
  film output and the controlled 16-hour battery discharge remain unverified this pass.

## One-second default review, 2026-10-11

Clean runtime **`4574aa9`** is deployed. New/missing configuration defaults to **Review 1s**;
Bridge/App settings now offer manual, immediate, 1-second and 5-second review. The live Bridge
was changed from 5 to 1 under `ib`. Editing still requires manual confirmation, and the countdown
begins only after the photo is ready. Print transport and CPU tiers are unchanged.

- **1,324 Bridge tests**, **156 App tests**, Ruff, touched-file formatting, strict mypy
  (65 files), whitespace and strict MkDocs passed. The App label is translated in all 12 locales;
  the global localization checker still reports pre-existing discrepancies.
- On-Pi software timing smoke loaded the saved config, used a synthetic prepared photo with
  NullDisplay/NullInput, and observed **Print in 1s**, **Review 1s**, acceptance **1.002 s** after
  the first photo frame. No Printer sender or film was used.
- Bridge/manager are active after restart, Bridge NRestarts=0, hotspot 192.168.8.1/24,
  throttling 0x0. Hardware/OS remain as below. App source was updated/tested; no App release
  installation or new physical-print benchmark was performed. See plan 066.

## Simplified printing and locked Wi-Fi recovery, 2026-10-11

Clean runtime **`cbffa65`** is deployed, including pending Wi-Fi recovery and plan 065's shorter
photo flow: Review (when enabled), one Printing layout, then Home with Printed feedback.
Receipt/duplicate Printer-check frames and verbose progress text are removed. Preparation and
edits stay in the same card; meaningful errors and stalled/restarting messages remain.
Completion/no-film timers no longer interrupt navigation. Physical/virtual LCD share this path.

- **1,307 Bridge tests**, Ruff, touched-file formatting, strict mypy (65 source files), shell
  syntax, whitespace and strict MkDocs passed; normal pre-commit gates passed. Independent
  review found no remaining actionable issue. No App/iOS contract changed.
- Camera FTP login exposed a five-minute deferral after hotspot loss. Past hotspot activity now
  allows recovery of its failed link; active jobs and recent traffic on other transports remain
  guarded. No new camera upload or film print was performed.
- Live missing-interface testing exposed the `brcmfmac_wcc` module holding the base driver.
  The helper unloads that fixed Wi-Fi extension before `brcmfmac`, only if `wlan0` is missing.
  Its next background retry recovered the existing fault without a Bridge/Bluetooth restart.
- Accepted locked tests: deactivating the saved hotspot restored IP/readiness in **32.90 s**;
  unbinding SDIO function 1 (missing `wlan0`, driver loaded) restored it in **31.99 s**. Across
  60/59 samples including 31 seconds of post-recovery observation, CPU remained powersave/600 MHz,
  GPIO24 remained low, the controller stayed locked, Printer status advanced and BlueZ stayed
  connected. Final driver-trial D-Bus monitoring saw no connection-loss event. Bridge PID
  remained unchanged in both tests; film remained **4**.
- Tests used a temporary observation wrapper around the real app and its normal KEY2 abstract
  action. LCD/backlight, CPU, network and Rust FFI/Printer were real; no mocks or physical key
  actuation. The wrapper/drop-in/probe files were removed and normal service restored afterward.
- The Printer stopped advertising during the extended earlier failed dependency trial; the user
  powered it back on and automatic reconnection succeeded. Accepted tests establish connection
  continuity through those faults, not indefinite Printer uptime or battery-runtime acceptance.
- Hardware/OS: Pi Zero 2 W Rev 1.0 / Waveshare ST7789 LCD HAT / X306 2300 mAh, Debian 13,
  kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. Instax Square
  INSTAX-52006924; camera profile Sony a7C II. USB SSH returned after data-port reconnection.
- Normal service restored at 21:43 EDT: Bridge/manager/Bluetooth/NetworkManager active, Bridge
  NRestarts=0, Printer connected with film 4/battery 65%, throttling 0x0. Hotspot FTP greeting
  and NOOP passed. Debian 13.2 and BlueZ 5.82 were rechecked.

See plan 065 and its recorded observations/rendered contact sheet. Physical GPIO, a new camera
upload, film colour output and the controlled 16-hour discharge remain pending.

## Missing Wi-Fi interface audit, 2026-10-06

The user reported `Setup needed` / `Bridge Wi-Fi off`. USB SSH initially worked. Wi-Fi was
enabled in NetworkManager, but `wlan0` was absent. Kernel boot logs showed a corrupted SDIO
RAM image, failed NVRAM download and MMC inhibit timeout before runtime CPU policy began.
The Bridge, manager and NetworkManager were active; `vcgencmd get_throttled` was `0x0`.

- A manual `modprobe -r brcmfmac` / `modprobe brcmfmac` restored `wlan0`; the existing root
  Wi-Fi helper then activated the saved hotspot at `192.168.8.1/24`. Bridge `NRestarts=0`.
  No Bluetooth restart, credential reset or film consumption was required. Instax Square
  `INSTAX-52006924` was connected with film 6 / battery 95% before USB access disappeared.
- Plan 064 adds bounded automatic hotspot recovery and truthful unavailable status. Runtime
  implementation `cad66aa` passed **1,282 Bridge tests**, Ruff, strict mypy (65 source files),
  touched-file formatting, shell syntax, whitespace and strict MkDocs. The normal pre-commit
  gate passed. No App/iOS contract changed. Deployment and automatic fault-injection smoke
  are pending: the Mac's `en8` USB interface
  disappeared during work, and the user was asked to reconnect micro-USB.
- Hardware/OS remain Pi Zero 2 W Rev 1.0 / Waveshare ST7789 LCD HAT / X306 2300 mAh,
  Debian 13.2 / kernel 6.12.47+rpt-rpi-v8 / Python 3.13.5 / BlueZ 5.82 / Bridge 0.1.17.
  The Pi's wall clock lagged behind the host date; boot-relative kernel timestamps were used
  for the failure order. This audit establishes no new battery-runtime or camera-upload claim.

## Unlock inactivity timeout, 2026-10-01

Clean runtime **`0c80d83`** now expires an incomplete unlock **10 seconds after its last accepted
button press**. Every press renews the timer, including a different button resetting the count
to one. Three consecutive presses of the same button still complete unlocking and cancel the
timer. Expiry clears progress, keeps the Bridge locked, turns off the LCD and returns idle CPU
to the supported 600 MHz minimum. Active preparation/printing keeps its boost until completion.

- **1,251 Bridge tests**, Ruff, touched-file formatting, strict mypy (65 source files), whitespace
  and strict MkDocs passed. The normal pre-commit gate passed. Deterministic timer tests cover
  stale cancellation, renewal on matching/different presses, dark locked expiry, low idle CPU
  and active-job boost release. No App or iOS source/config contract changed.
- Real framebuffer/CPU smoke under `ib` tested both matching and different button identities:
  first press, six-second wait, second press, then another 4.5-second wait. The prompt remained
  visible at full performance past the former first-press deadline. With no further input, it
  returned to dark locked state about 10.19 seconds after the latest press, with idle CPU checked
  at 600 MHz. Both trials passed; a final same-button triple cancelled the timer and restored
  the latest screen at 1000 MHz.
- Inputs were injected into the controller with GPIO identities; real framebuffer, backlight
  and root CPU helper were exercised. No physical switch or film was used. The service was
  restored after the smoke and restarted at 11:10 EDT. Bridge, manager, Bluetooth and
  NetworkManager are active, `NRestarts=0`, throttling `0x0`; hotspot FTP greeting/NOOP passed.
- Hardware remains Pi Zero 2 W Rev 1.0 / Waveshare ST7789 LCD HAT / X306 2300 mAh, Debian 13.2,
  kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. Saved Instax Square
  was not advertising. Physical GPIO, Sony a7C II upload, film/reconnect and 16-hour discharge
  acceptance remain pending.

Plan 063 supersedes the fixed first-press timeout recorded below.

## Same-button unlock correction, 2026-10-01

Clean runtime **`8dadb69`** replaces the earlier mixed-button rule. Unlock requires the same
physical button three consecutive times. Different buttons reset progress to one without
extending the original 10-second timeout. GPIO pin identity keeps KEY1 distinct from joystick
press even though both perform Select; remote actions have separate identities. The prompt
and App toggle explicitly say same button. Default-on protection, opt-out, first-press CPU
preparation, latest-state restoration and background operations are preserved.

- Local gates: **1,247 Bridge tests**, **154 App tests**, Ruff, touched-file formatting,
  strict mypy (65 files), whitespace and strict MkDocs passed. The App result was completed
  independently on the same change. Its duplicate pre-commit compilation was terminated under
  extreme host load (load average 582); the commit reused the completed checks without changing
  the configured hook. New wording is translated in all 12 App locales.
- Film-free on-device smoke under `ib` passed framebuffer restoration, both updated prompts,
  latest underlying state, same-button completion, alternating GPIO identities resetting to one,
  KEY1/joystick Select separation, timeout after a changed button, automatic-dark wake and opt-out.
  GPIO identities were injected into the controller; no physical switch was actuated.
- Actual CPU checks confirmed 600 MHz locked, 1000 MHz on first press, 600 MHz on expiry and
  1000 MHz on opt-out wake. The runtime service was restored after the temporary framebuffer
  smoke stop. Bridge, manager, Bluetooth and NetworkManager remain active, `NRestarts=0`,
  throttling `0x0`, with a working hotspot FTP greeting and NOOP.
- Hardware/OS: Raspberry Pi Zero 2 W Rev 1.0, Waveshare 240×240 ST7789 LCD HAT, X306 2300 mAh
  cell; Debian 13.2, kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17.

See plan 062 and its Pi-rendered synthetic state image. Physical press/hold confirmation,
Sony a7C II camera upload, Instax Square power-cycle/film checks and 16-hour discharge remain
pending. The earlier mixed-key smoke below is historical, not acceptance of the corrected rule.

## Reliable wake and three-press unlock, 2026-09-30

Clean runtime `fb1f27e` is deployed on the Raspberry Pi Zero 2 W Rev 1.0 / Waveshare
240×240 ST7789 LCD HAT / X306 2300 mAh cell, Debian 13.2, kernel 6.12.47+rpt-rpi-v8,
Python 3.13.5 and BlueZ 5.82. Bridge 0.1.17 restarted at 13:47 EDT after the smoke check.
The default-enabled guard is live: **Settings → System → Unlock: 3 presses**. The App also
exposes the toggle. KEY3 remains Reconnect when the saved Printer is offline, and Post when ready.

- Fixed blank wake caused by black framebuffer pixels plus an unchanged cached UI snapshot.
  The retained frame is restored before the backlight comes on, and wake forces a current redraw.
- First press shows one filled circle and warms the CPU; second shows two; third restores the
  latest state. Inputs are consumed. An incomplete sequence expires after 10 seconds.
- Real framebuffer/backlight smoke passed under the runtime `ib` account with the Bridge service
  temporarily stopped. Tests verified byte-for-byte frame restoration, visible prompts,
  `bl_power` 4→0, same-key and mixed-key sequences, and a newer synthetic error state appearing
  on the third press. One-press opt-out and automatic screen-off wake also passed.
- Actual governor checks recorded locked `powersave` at 600 MHz, first-press `performance` at
  1000 MHz, timeout back to 600 MHz, and opt-out wake at 1000 MHz. The service was restarted
  even if the smoke failed. No film was sent and no production photo/config values were changed.
- Bridge, manager, Bluetooth and NetworkManager are active, Bridge `NRestarts=0`, throttling
  `0x0`; hotspot FTP greeting and NOOP passed. The runtime automatically returned to backlight
  off after the check. The deployed manifest records `dirty=false` and source `fb1f27e`.
- Final checks: **1,241 Bridge tests**, **154 App tests**, Ruff, touched-file formatting,
  strict mypy (65 source files) and strict MkDocs. New toggle strings cover all 12 App locales;
  the global localization checker retains its previously verified baseline gaps.

Frames in plan 061 are Pi-rendered synthetic states. Physical GPIO press/hold confirmation,
Sony a7C II upload, Instax Square power-cycle/film checks and the 16-hour discharge remain
unverified. Shared controller tests cover busy/error FTP guards during unlocking; the overlay
does not replace operational Printer/photo state.

## Post processing and interface implementation, 2026-09-30

Plan 060 implements the plan 059 audit. KEY3 is **Post** on ready Print home, with separate
Looks and persistent Printer Correction. New correction defaults to zero; existing creative
adjustments are preserved. A user choice about moving the live +50 saturation to Correction
remains pending, so the deployment will retain the current Look values.

**Deployed runtime: `10fd031`**, clean archive, Bridge 0.1.17 on Pi Zero 2 W Rev 1.0,
Debian 13.2 / kernel 6.12.47+rpt-rpi-v8 / Python 3.13.5 / BlueZ 5.82, Waveshare LCD HAT and
X306 with 2300 mAh cell. The App contract and copy were updated in `7ca015d`.

- Final gates: **1198 Bridge tests**, Ruff lint and touched-file format checks, strict mypy
  (65 source files), **152 App tests**, whitespace checks and strict MkDocs build pass.
- The localization checker has pre-existing missing/extra keys at baseline `4f6a8e7`; comparison
  found no new diagnostic lines. All introduced App strings are present in all 12 locales.
- On-Pi shared-controller smoke passed Settings without Printer, Post/Looks/Correction navigation,
  staged Correction cancellation, context Help, wake-only input, locking during a simulated print,
  and actual killable-worker preview preparation/cancellation. Real root helper transitions were
  1000/600/1000/600/1000/600 MHz. A dark manual-confirmation wait returned to powersave after
  preparation; only preparation/rebuild and accepted printing hold the boost.
- The smoke uses synthetic state and a sample JPEG, installed Pi fonts and actual CPU controls.
  It does not inject physical GPIO or send film. Its rendered frames exposed clipped instructions
  and a wide printing title; these were fixed with nine additional font-size layout tests.
- Bridge, manager, Bluetooth and NetworkManager are active; Bridge `NRestarts=0`, throttling
  `0x0`, hotspot FTP greeting/NOOP and both manager listeners verified. Runtime automatic
  screen-off entered powersave at 600 MHz with backlight off.
- Saved Printer is still Instax Square `INSTAX-52006924`; it was not advertising during checks.
  Current creative Look is Vivid with saturation +50; Correction is 0. No live image setting was
  silently reinterpreted. The user can move the compensation to Correction independently.

Physical KEY2/KEY3, Sony a7C II upload with edit/confirmation, Printer power-cycle reconnect and
film colour output are pending user smoke checks. The 16-hour discharge target remains unmeasured.
See plan 060 and `docs/assets/bridge-ux-060/validated-screens.png` for details.

## Previous verified context

**2026-09-30 performance tiers deployed and checked:** source commit `892945a` was installed
through a clean archive and the Bridge restarted successfully (`NRestarts=0`). The root-owned CPU
helper and constrained sudo rule were installed and validated. Awake/photo work uses 1000 MHz;
dark/locked idle uses `powersave` at the supported 600 MHz minimum across cores 0–3. The live
runtime automatically switched to 600 MHz with LCD backlight off (`bl_power=4`), and kept the
hotspot, FTP, manager, SSH and 30-second BLE searches operational. `throttled=0x0` throughout.
The policy controller was exercised on-device through awake → locked → boosted job → locked →
awake transitions. A fresh physical KEY2 cycle with these new tiers remains pending.

Latest recorded real print is `DSC02697.HIF` → Instax Square, logged in the earlier session as
2026-09-28: send/print 24.837 s (prior reference 24.03 s), prepared preview reused. Upload took
11.835 s for an 11.26 MB file, compared with 7.56 s for the prior 5.19 MB file. The larger source
and upload account for most of the observed total-cycle difference. No reduced clock maximum
or duplicate preparation was found. Same-file preparation trials measured about 9.7 s at fixed
600 MHz and 5.7 s at fixed 1000 MHz, supporting the photo-job boost. Details and limits are in
`docs/plans/058-bridge-awake-performance.md`. The sampler now records the governor; it remains
disabled between discharge tests. The Pi's clock was resynced to the host on 2026-09-30.

Prior source deployment verified: 2026-09-28 on `riverps-rpi-zero-2w` (bridge 0.1.17,
branch `codex/bridge-battery-day`, commit `4455f53`, clean archive). This source-only deployment
updated the benchmark script and service unit without restarting the healthy Bridge runtime. The
prior runtime deployment restarted successfully with `NRestarts=0`; FTP `:21` and manager `:8742`
listen on the expected addresses.
The Pi clock was corrected from 2026-09-11 by the deployment script and resynced on 2026-09-28;
offline wall-clock timestamps drift or reset across boots. The earlier 2026-08-04 Sony a7C II
`.HIF` → Instax Square reference run is described below.

### Battery session, 2026-09-27

- The X306 now holds a **2300 mAh 18650 cell**. It has no Linux-readable current or charge gauge;
  the first near-full discharge ran overnight, but the exact unplug time is pending. The battery
  directly powers the Bridge. The protocol and evidence are in
  `docs/plans/057-bridge-battery-day.md`. The transient sampler wrote 206 one-minute records through
  00:07:08 EDT, then stopped at an unplanned reboot. The next boot had no USB carrier and ran the
  Bridge for 9 h 9 min before an abrupt stop around morning reconnection. The user observed empty
  battery LEDs and a dark LCD; the Pi nevertheless logged two physical inputs about seven minutes
  before its last journal entry. The final cutoff time is not independently confirmed. The Bridge
  recovered automatically after the midnight reset. A new opt-in persistent sampler unit was
  installed and verified on the Pi; it is disabled between tests and can be enabled for a repeat run.
- KEY2 now locks the LCD from home/status surfaces; the next key wakes it without also activating
  a UI action. The Print/Sync Mode picker is on the top Settings page. Locked screens skip physical
  framebuffer renders, and network status polling slows from 1 s to 5 s while the screen is off.
  These changes pass 1121 local Bridge tests. **Physical KEY2/backlight behavior is not yet
  hand-verified**; the Printer was off during deployment.
- The device's saved Printer search period was changed from 5 s to 30 s (prior config backup:
  `/etc/InstantLinkBridge/config.toml.bak-battery-baseline`). Automatic BLE search remains active.
  With the Printer off and the LCD dark, sampled aggregate CPU busy fell from 8.75% (5 s search,
  four 5 s intervals) to 3.67% (30 s search, seventeen 5 s intervals). This measures activity,
  **not** battery draw. The updated code also defaults new configs to 30 s and leaves 5/15/30/60
  s choices in Settings.
- After the dark-screen network watcher moved to a 5 s cadence, a further seventeen 5 s samples
  averaged 3.42% aggregate CPU busy and 48.6 °C SoC temperature. That small difference from the
  3.93% post-boot-diet sample is within short-run variation; it is not a runtime measurement.
- A powered 5-minute search-rate trial on 2026-09-28 averaged 2.67% aggregate CPU busy at a
  60-second interval, versus 2.94% across the longer 30-second overnight sample. Different trial
  conditions prevent translating this into battery savings. The live interval was restored to
  30 seconds immediately after the trial for faster Printer reconnection.
- The production boot diet disabled `tailscaled` and the OpenFilmAdvance GitHub Actions runner;
  user-level `rpi-connect` was disabled separately. USB SSH remains available. Available RAM rose
  from about 197 MB to 281 MB, and swap use fell from 67 MB to 45 MB. The live Bridge, Bluetooth,
  Wi-Fi hotspot, FTP, and manager services remained active.
- The paired Instax Square was not advertising during this session. A timed power-on reconnect,
  camera FTP upload, and full battery discharge remain the hardware gates.

Print/Sync mode behavior from commit `7a43570` was the prior baseline (2026-07-22). The iPhone
sync feature from plan 050 + UX audit 051 + virtual LCD 054-A was last exercised on-device with a
real iPhone on 2026-07-15.

This file is the fast handoff for anyone opening the bridge code after the InstantLink port. The
source of truth is the InstantLink repository under `bridge/`; the old standalone InstantBridge
Python app is legacy and should not receive new feature work.

## Product Shape

InstantLink Bridge is a Raspberry Pi appliance that receives selected camera photos over FTP,
prepares them for the detected Instax Link printer model, and prints through InstantLink's Rust
backend. The supported v1 camera path is hotspot-first:

```text
Camera FTP upload
  -> Bridge Wi-Fi SSID InstantLink-XXXX
  -> FTP 192.168.8.1:21
  -> pyftpdlib receive queue
  -> Pillow / heif-thumbnailer / rawpy image preparation
  -> InstantLink FFI
  -> Mini / Mini Link 3 / Square / Wide Link printer
```

The Pi USB gadget network is retained for admin, SSH, deployment, and diagnostics at
`192.168.7.1`. It is not a supported v1 camera FTP path. Same Wi-Fi FTP remains an advanced path
for cameras and the bridge on an existing network.

## Current Deployed State

- **Prior deployment: commit `0e1acab` on `main` (2026-08-04)**, clean tree, `--system --restart`.
  Verified on-device: `instantlink-bridge.service` and `instantlink-bridge-manager.service` both
  active with `NRestarts=0`; FTP `:21` and manager `:8742` (on both `192.168.7.1` and
  `192.168.8.1`) listening; no errors in the journal.

### Live print verified (2026-08-04) — closes prior open items

The 2026-07-22 entry recorded that "live printing, live film polling, physical-LCD observation
with a connected Printer" remained unverified because the Printer was not advertising. All three
are now confirmed on hardware:

- **Live print**: `DSC01595.HIF` (5.19 MB) uploaded over the hotspot from the a7C II, previewed on
  the physical LCD, and printed on Instax Square `INSTAX-52006924`. `bridge.print_start` →
  `bridge.print_complete` in 24.0 s; ~38.4 s from upload start to print delivered.
- **Live film polling**: `ui.printer_status film_remaining=2 battery=95 model=square` at the
  configured 10 s keepalive interval.
- **Model auto-detection**: `[printer] model = "auto"` resolved to `square` from the connected
  device.

Still unverified: a physical KEY2 mode switch, and Mini / Mini Link 3 / Wide hardware (only Square
has been exercised end-to-end).

### Plan 056 performance work (deployed 2026-08-04)

- Boot **1 min 35.8 s → 20.1 s**; the LCD boot splash now appears at **9.9 s instead of 95.8 s**.
  Root cause was `instantlink-bridge-boot-splash.service` waiting on a `dev-fb1.device` unit that
  udev never created — fixed by `bridge/udev/61-instantlink-bridge-fb1.rules`, which must be
  installed for the dependency to resolve (`provision-sd.sh`, so a `--system` deploy is required).
  Stable across three cold boots including a power cycle.
- Print path now runs the image pipeline **once per print instead of twice**: the LCD preview's
  prepared image is handed to the printer. Confirmed live by
  `instantlink.image_prepared source=preview prepare_ms=0`. `source=` is the diagnostic to check
  if a print ever feels slow — `inline` means the reuse did not apply.
- `incoming/` is now bounded by `[ftp].incoming_budget_mb` (default 512) **and** a 14-day age
  rule. It had never been pruned; the device was holding 98 MB back to May 25. First run cleared
  **98 MB → 10 MB**. Configs predating the key default to 512.
- `boot-diet.sh --production` drops tailscaled / rpi-connectd / any GitHub Actions runner (~110 MB
  of 512 MB on this unit). Deliberately **not** part of `--apply`, because on a dev unit tailscaled
  is how you reach the Pi.
- Full measurements, and what was ruled out with data (CPU governor, thermal throttling, Pillow
  build, worker overhead), are in `docs/plans/056-bridge-performance.md`.

**Local config drift on this device:** `workflow.auto_print_delay_s` was set to `5` (from `0`) and
`adjustments.sharpness` to `0` (from `5`) during the 056 measurement session. Backup of the prior
values at `/etc/InstantLinkBridge/config.toml.bak-056`. `sharpness = 5` maps to a factor of 1.05
applied at working resolution and then downscaled ~4x — it cost 1911 ms per print to do
essentially nothing visible.

- Prior Print/Sync behavior baseline: commit `7a43570` on branch `main`, delivered through a
  clean `git-archive` deployment with `dirty=false`.
  - On-device verification 2026-07-22: `instantlink-bridge.service` and
    `instantlink-bridge-manager.service` were both active with `NRestarts=0`; FTP `:21` and manager
    `:8742` were listening; `usb0` was up at `192.168.7.1/24` and Bridge Wi-Fi at
    `192.168.8.1/24`; logs contained `ftp.server_started`, `instantlink.library_loaded`, and
    `bridge.ready` with no startup errors.
  - The existing on-disk `destination = "both"` loaded as Print for backward compatibility.
    Sync/virtual-LCD `:8721` was intentionally not listening in Print mode. Pressing KEY2 switches
    to Sync and persists the new two-mode value; KEY2 switches back to Print from Sync.
  - The saved Printer was not advertising during the deploy, so live printing, live film polling,
    physical-LCD observation with a connected Printer, and a physical KEY2 mode switch remain to
    be verified. The connected-film renderer path was previously verified with a synthetic
    `Connected · Film 7/10` snapshot and a 240x240 frame on 2026-07-18.
  - Prior on-device verification 2026-06-12: LCD screen-off drives GPIO 24 LOW after the configured
    idle threshold (was previously a silent no-op because `bl_power` was `root:root 0644` — see
    `bridge/udev/60-instantlink-bridge-backlight.rules` and the commit message).
- Service: `instantlink-bridge.service`
- Install root: `/opt/InstantLinkBridge`
- Config root: `/etc/InstantLinkBridge`
- Runtime user/group: `ib:ib`
- Hotspot SSID pattern: `InstantLink-XXXX`
- Hotspot address: `192.168.8.1/24`
- USB admin address: `192.168.7.1/24`
- FTP port: `21`
- Native backend: `/opt/InstantLinkBridge/lib/libinstantlink_ffi.so`
- Sync service (plan 050): active only in Sync mode; HTTP `:8721`, Bonjour
  `_instantlink._tcp`, token at `/etc/InstantLinkBridge/sync.token`, outbox at
  `/var/lib/InstantLinkBridge/sync-outbox/`. Full API in `docs/reference/sync-api.md`.
- Virtual LCD (plan 054-A): in Sync mode, `GET /v1/screen` (live 240×240 PNG) + `POST /v1/input`
  on the same port, gated by `[sync].remote_ui` (default true).
- The device file still contains the retired `[sync] destination = "both"`; current code maps
  this legacy value to Print. Fresh installs default to `print`, and the UI writes only `print` or
  `iphone` (Sync).

## iPhone Sync (plan 050) — deployed 2026-07-14

Bridge 0.1.17 added the iPhone-sync path: received camera photos spool to a disk outbox and are
served to the iOS app over a bearer-token HTTP API (`/v1/status|queue|photos/{id}|photos/{id}/ack`)
discovered via Bonjour. Verified end-to-end on the device with no printer involved:

- FTP upload from a hotspot-subnet source was accepted with the printer absent (destination-aware
  STOR preflight), spooled (`sync.outbox_added`), and print was skipped quietly
  (`sync.print_skipped_printer_unready`).
- From the deploy host over USB admin: 401 without token; queue listed the item; the download was
  sha256-identical to the upload; `Range` returned 206; ack drained the outbox to depth 0.
- Bonjour initially advertised only `192.168.7.1` because registration raced the hotspot at boot —
  fixed in `8f24c4c` (30 s address refresh, also covers runtime Wi-Fi mode switches); the journal
  now shows `addresses=192.168.8.1,192.168.7.1`.

New runtime deps `zeroconf`/`segno`/`ifaddr` are pinned in `requirements/constraints.txt`. The Pi
had no outbound internet, so the aarch64/cp313 wheels were downloaded on the deploy host
(`pip download --platform manylinux_2_17_aarch64 --only-binary :all:`), scp'd over, and installed
into `/opt/InstantLinkBridge/.venv` before the source deploy. Fold them into the provisioning
offline-deps bundle for fresh devices.

### On-device iPhone session (2026-07-15)

Ran the real iOS app (free-team signed) against the Bridge. Two bugs found and fixed by driving the
actual hardware, both in `502a3bf`:

- **`.HIF` never saved.** Sony writes HEIF stills as `.HIF`, an extension iOS maps to no image
  type, so `PHPhotoLibrary` rejected every save and the app re-downloaded the 6.4 MB file each
  poll. `PhotoSaver` now sets the UTI explicitly (`.HIF`→HEIF, `.ARW`→Sony RAW).
- **Retry loop on complete staging.** Once a full file was staged (from the failed save), the
  resume logic requested `bytes=<size>-` forever (a 416). `downloadPhoto` now verifies the staged
  bytes against the item sha and goes straight to save when complete; corrupt/oversized partials
  restart from zero.
- **Outbox chip stale after restart.** The spool index reloads on boot but the LCD chip started at
  a stale 0 until the next add/ack — startup now announces the reloaded depth
  (`announce_initial_outbox_depth`). Verified live via `GET /v1/screen` showing `iPhone: 1 pending`.

Diagnostics that worked well: `GET /v1/screen` for a live LCD screenshot, `tcpdump` on `wlan0`
port 8721 for the request/`Range` pattern, and `devicectl … process launch --console` for the
app's own logs. Free-team friction: iOS re-prompts to trust the developer profile on every
reinstall (Settings ▸ General ▸ VPN & Device Management), and drops the internet-less hotspot when
idle — both disappear with a paid membership.

Remaining hardware validation: confirm `.HIF` now lands in Photos (the fixed build was installed
but awaited a profile re-trust at session end); run the hotspot-tolerance soak; and exercise the
physical Print/Sync switch with a live Printer and iPhone.

The old `/opt/InstantBridge` install, `/etc/InstantBridge` config, and `instantbridge.*` unit files
are legacy. They were removed from `riverps-rpi-zero-2w` on 2026-05-25 with
`scripts/cleanup-legacy-instantbridge.sh /`. Run the same script after confirming
`instantlink-bridge.service` is healthy on any migrated device.

## Deployment

Normal deploy when the Pi is reachable over USB admin Ethernet:

```bash
INSTANTLINK_BRIDGE_HOST=192.168.7.1 \
INSTANTLINK_BRIDGE_USER=hongjunwu \
INSTANTLINK_BRIDGE_OFFLINE_DEPS=1 \
scripts/deploy-to-pi.sh --system --instantlink-artifacts --deps --restart
```

Use `INSTANTLINK_BRIDGE_SEED_VENV=/opt/InstantBridge/.venv` only for one-time migration from an old
device where `/opt/InstantLinkBridge/.venv` does not yet exist and the Pi has no outbound internet.
After migration, the new install owns its own virtualenv.

The deploy script records:

- `/opt/InstantLinkBridge/.deployment/deployment-manifest.json`
- `/opt/InstantLinkBridge/.deployment/instantlink-artifacts-manifest.json`
- `/opt/InstantLinkBridge/.deployment/runtime-deps-manifest.json`
- `/opt/InstantLinkBridge/.deployment/runtime-installed-packages.txt`
- `/opt/InstantLinkBridge/.deployment/runtime-apt-packages.txt`

The Pi may have no outbound NTP route while it is serving Bridge Wi-Fi. `scripts/deploy-to-pi.sh`
therefore syncs the Pi clock from the deploy host before copying files. Leave this enabled for
normal maintenance; set `INSTANTLINK_BRIDGE_SYNC_CLOCK=0` only if the deploy host clock is wrong.

## Verification Checklist

Run these after every device deploy:

```bash
systemctl status instantlink-bridge.service --no-pager -l
/opt/InstantLinkBridge/.venv/bin/instantlink-bridge --version
sudo ss -ltnp sport = :21
sudo ss -ltnp sport = :8721  # present only in Sync mode
ip -br addr
nmcli -t -f NAME,TYPE,DEVICE,STATE con show --active
journalctl -u instantlink-bridge.service --since "5 minutes ago" --no-pager
```

Expected healthy state:

- `instantlink-bridge.service` is `active (running)`.
- `instantbridge.service` is absent or disabled/inactive.
- `wlan0` has `192.168.8.1/24` when Bridge Wi-Fi is active.
- `usb0` has `192.168.7.1/24` when connected to an admin host.
- FTP accepts the configured user on `192.168.8.1:21` in hotspot mode.
- Sync/virtual-LCD `:8721` is absent in Print mode and listens in Sync mode.
- Logs contain `ftp.server_started`, `bridge.ready`, and `instantlink.library_loaded`.
- Offline-printer status warnings are rate-limited; do not reintroduce per-second warning spam while
  keeping the UI scan loop responsive.
- Source-only deploys must preserve `/opt/InstantLinkBridge/lib` and
  `/opt/InstantLinkBridge/bin`; the native FFI library and CLI live there.
- The deployed NetworkManager state should contain one `InstantLink Bridge-Hotspot` profile and no
  legacy `InstantBridge-Hotspot` profile.

## Current Hardware Notes

- The Waveshare ST7789 display path is wired through the bridge UI and boot splash units.
- The active UPS is a SupTronics/Geekworm X306 18650 shield. It has no host-readable fuel gauge, so
  the UI must not show fake battery percentage.
- Latest on-device audit, 2026-07-22:
  - `instantlink-bridge.service` was active/enabled with `NRestarts=0`.
  - `instantlink-bridge-manager.service` was active with `NRestarts=0`.
  - `/opt/InstantLinkBridge/.venv/bin/instantlink-bridge --version` reported Python 3.13.5,
    BlueZ 5.82, Debian 13.
  - Hotspot mode was active on `wlan0` at `192.168.8.1/24`; USB admin was active on `usb0` at
    `192.168.7.1/24`; FTP was listening on `0.0.0.0:21`, and manager HTTP was listening on both
    device addresses at `:8742`.
  - Legacy config value `both` parsed as Print, and `:8721` was correctly closed in that mode.
  - `/opt/InstantLinkBridge/lib/libinstantlink_ffi.so` loaded successfully.
  - The saved Printer `INSTAX-52006924` was not advertising, so the Bridge remained in its
    printer-searching flow; the repeated scan progress was healthy and status warnings remained
    rate-limited.
  - Earlier Printer/BLE history:
    - The old BlueZ bond for `INSTAX-52006924 (IOS)` was removed after native connects failed with
      BlueZ `InProgress`, `le-connection-abort-by-local`, and `Timeout waiting for reply`.
    - A 2026-05-25 follow-up saw both `INSTAX-52006924 (ANDROID)` and
      `INSTAX-52006924 (IOS)`, then native connect reached GATT but failed with
      `write characteristic not found`. Commit `9a54b4f` retries Linux BLE characteristic
      discovery; commit `8860be6` includes that fix plus display idle defaults. Fresh ARM64
      artifacts were deployed from `8860be6`.
    - After the failed connect attempts, the Printer stopped advertising in both InstantLink and
      BlueZ scans. The LCD should show the no-Printer/pairing flow until the Printer is
      power-cycled and paired again from the Bridge.
    - Runtime idle display timers were dropped in source defaults (commit `ad638be`): dim after
      30 s, screen off after 60 s, deep idle after 300 s, poweroff after 1800 s. The earlier
      30-minute screen-off default was effectively "never" on battery; the new defaults
      materialise the GPIO-24-LOW kill into observable power saving within the first minute of
      idle.
- Physical printing is still the remaining hardware validation step after successful re-pairing.

## Local Development Checks

From `bridge/`:

```bash
python -m ruff check src tests
python -m mypy src tests
python -m pytest -q
```

From the InstantLink workspace root:

```bash
cargo fmt --all --check
cargo test --workspace --locked
cargo clippy --workspace --locked -- -D warnings
```

The current Mac has rustup with the `aarch64-unknown-linux-gnu` target, cargo-zigbuild and Zig.
Native JPEG validation also needs CMake and a C compiler (NASM for x86 SIMD builds). Build clean
ARM64 artifacts with `scripts/build-instantlink-artifacts.sh`, which records source and artifact
provenance, before deploying with `--instantlink-artifacts`. The validator is statically bundled;
no extra JPEG library is required on the Pi.

## 2026-10-14 — Optimization audit and polish (plan 089)

- Installed clean runtime `6a60165ae7993722a034e9389e0516db1819df85`; all 67 Python source hashes
  match. Native `b2b6c8c` / FFI `9e31f998…34031` / CLI `1068fcb5…ce38e` unchanged. Bridge package
  version remains 0.1.17. Pi Zero 2 W Rev 1.0, ST7789 240×240, X306 2300 mAh; Debian 13.2 /
  Linux 6.12.47+rpt-rpi-v8 / Python 3.13.5 / BlueZ 5.82 / NumPy 2.4.6.
- One fresh subagent per plan 057–088 audited frozen `c4a2787` (32 reviews). Fixed CPU retries
  and cancelled writes/close ownership; preset vignette/hue round trips; lost-input unlock
  safety; full review duration; About/metadata ownership; accepted print settings; immutable
  Sync originals and legacy detachment; transactional index publication; early FTP shutdown
  admission/all-resource cleanup; authenticated fresh BlueZ snapshot/watch state, exact bond
  deletion guards/results, recovery logs; manager off-loop collection and GPIO backlight close.
- Four fresh fix reviews clear after corrections. Normal hooks: 2,269 Bridge tests, 27 existing
  warnings, Ruff, full formatting (152 files) and mypy (67 sources); strict docs passed.
- No film used. Eleven GPIO kernel-mockup/controller/physical LCD cases passed, including held,
  mixed/rapid triple presses and 10-second abandonment; switch contacts not actuated. All 18
  benchmark frames have identical RGB565 bytes; median 7.63 → 7.70 ms (no speedup claim).
  Real governor failure recovered in 0.337 s; cancelled post-write boost restored locked 600 MHz.
  Isolated installed filesystem/index-failure and concurrent manager HTTP checks passed.
- Normal runtime offline idle: 0.37 CPU seconds / 30.029 seconds, 1.23% of one core at 600 MHz;
  initial same-round sample 1.53%. These short process-only samples are not energy/runtime data.
- Restored normal services, PIDs 45900/45198 active / NRestarts 0, powersave/600 MHz, throttle0x0,
  FTP220/200 on Pi hotspot address, no normal warnings/errors or input fallback. Removed owned
  observer/drop-in/socket/mockup/helpers. Final retained service/kernel logs classified in
  plan089; old driver findings plus ten vendor-IE reconfiguration errors remain maintenance
  limits. Raw journals private; sanitized evidence under `docs/assets/bridge-audit-089/`.
- Initially, Printer INSTAX-52006924 was unavailable and live reconnect was pending. The
  follow-up below resolves that gate; no camera airtime or developed-film verification.

### 2026-10-14 — Live locked reconnect follow-up

- The normal Bridge at 600 MHz automatically connected after the user powered on
  INSTAX-52006924 (Link Square, film 0, battery 80%). No film/image/actuator commands used.
- Source `6a60165` passed locked reconnect in 12.373 s, but its published fresh-status flag
  briefly outlived the timestamp invalidation. Fixed immediate state publication/render wake
  in clean source **4145e771e4c2f46ff4d2fa06c654666b5a3878de**, now installed; all 67 Python
  source hashes match, native artifacts unchanged. Independent review clear; 27 targeted tests
  and normal hooks (2,270 tests / 27 existing warnings, Ruff, mypy) passed; touched format passed.
- Updated runtime PID47347 recovered automatically in **10.887 s** from external BlueZ
  Disconnect dispatch to new fresh status. Event→first fetch 0.466 s. All samples locked/600 MHz,
  camera receive readiness true, same PID; invalid timestamp always published stale. New status
  restored a single disconnect watch. Radio timing uncontrolled; no transport speedup claim.
- Same-button triple unlock restored a nonblank LCD/1000 MHz, then relocked/600 MHz;
  status pause/resume rearmed the watch and refreshed status while locked. Shared production
  action queue used; physical switch contacts not actuated. Evidence in plan089/live JSON files.
- Restored normal Bridge/manager **47710/47345**, active/NRestarts0, Printer connected,
  powersave/600 MHz, GPIO24 low, 42.932°C, throttle0x0, hotspot FTP220/200, no working cache
  or input/network fallback. Removed owned observer/drop-in/socket/helpers/bytecode; no mockup.
- Full available current-boot journals reviewed: 262 added service records, zero new flagged
  records; six added vendor-IE driver errors during service reconfiguration, no new HCI fault.
  Earlier kernel/firmware limitations remain; AP/FTP healthy. No further application finding.
  Raw logs retained privately; sanitized inventory/evidence under plan089.


## 2026-10-14 — Wi-Fi continuity and AP driver cleanup (plan 090)

- Clean application source `982d8c6` installed; privileged helper SHA `736cf4ba…afed2`, all
  67 Python hashes match, native `b2b6c8c` / FFI `9e31f998…34031` / CLI `1068fcb5…ce38e` unchanged.
- Healthy repeated hotspot setup now retains the verified activation; median 3.742 → 2.187 s,
  FTP greeting/NOOP failures 9 → 0 during four isolated 8 MiB checksum-verified receives.
  Same-Pi hotspot IP path only; no wireless airtime/physical camera throughput claim.
  Candidate trial retained connected Link Square, lock/600 MHz, fresh status in all 45 samples.
- WPS enrollment disabled while retaining SSID/PIN/WPA2-PSK/RSN/CCMP. After radio cycling, one
  residual cleanup error persisted. Scalar probes identified wrong probe-request AP cleanup;
  disabling P2P did not fix it and was removed by restarting the supplicant.
- Exact upstream `aba23b0` backported to Raspberry Pi source `359f37f0` for running
  `6.12.47+rpt-rpi-v8`. Native unchanged rebuild matches packaged stock source identity; all 254
  imported CRCs and all 11 exports/types/namespaces match stock. Candidate module SHA
  `a2b930a1…a02c7`, srcversion `2254D80EF43499080344466`. Stock module remains unchanged.
- Reversible exact-kernel override installed under `updates/instantlink/brcmfmac.ko`; private
  manifest/stock backup under `/var/lib/InstantLinkBridgeKernelBackports/6.12.47+rpt-rpi-v8`.
  Build/install/rollback/verify instructions in `bridge/patches/README.md`. This separate kernel
  override is not automatically installed by application firmware updates or rebuilt for new kernels.
- Install/rollback/reinstall passed on Pi. Loaded AP cleanup now uses association-response IE
  `0x4`/return 0; station probe-request scan handling retained. Wi-Fi-only reload retained USB,
  Bridge PID, locked at 600 MHz/camera readiness; Printer was offline. Out-of-tree taint expected; no
  kernel/firmware/initramfs change. Final connected recovery/reboot acceptance follows below.


### Plan090 final acceptance

- Installed clean source `a745c9136882283dc7071fabd1f721e2d6b0b186`; all 67 hashes, reviewed
  privileged helper/tool and unchanged native artifacts match. 2,370 Bridge tests/27 existing
  warnings, Ruff, strict mypy, script compilation, targeted formatting and strict docs pass.
  Independent tool review:31 tests plus4 actual filesystem failure/rollback transactions clear.
- Automatic AP loss recovery **32.693s** retained PrinterConnected/locked at 600 MHz/same PID/fresh
  status with0 vendor-IE errors. Administrative radio-off remained off by the accepted plan064
  policy;187 samples retained connected/fresh/locked at 600 MHz, then explicit restoration succeeded
  with0 errors. An incorrect fixture expectation of automatic radio re-enable is retained as
  a failed test expectation, not an application bug; guard unchanged.
- Real reboot preserved the patched loaded module and healthy normal services/FTP. Post-boot
  external BluetoothDisconnect→newfresh status passed **7.170s**, all samples locked at 600 MHz,
  camera ready/same PID; final watch 1 / retired tasks 0. Triple unlock/nonblank1000→relock600 and
  pause/resume/watch rearm passed. GPIO contacts not actuated; no film/image/actuator commands.
- Host-private0600 observer scripts caused21 test-only failed startups; fixed root:ib0640,
  finished validation and removed observer/drop-in/socket again. Final normal PID1542, active
  services/0 automatic restarts, powersave at 600 MHz, 45.084°C/throttle0x0, GPIOv2/no fallback, FTP220/200.
  Printer offline at final normal capture after idle; successful connected checks recorded.
- Fresh boot kernel 397 records / 21 existing or expected warnings, **0 vendor-IE errors**. Normal
  application faults 0; existing GPU/media/VCHI/LCD/regulator notes remain. Complete logs private,
  classified evidence in plan090. Owned build/test artifacts removed; Wi-Fi stamp and per-kernel
  override/provenance/stock rollback backup retained. Future kernel changes need new assessment.
