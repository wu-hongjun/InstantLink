# Current Bridge Context

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

The current Mac does not have `rustup`, so it cannot install the
`aarch64-unknown-linux-gnu` target locally. If Rust FFI code changes, build ARM64 artifacts on a
machine or CI runner with the proper Rust target and update the artifact manifest before deploying
with `--instantlink-artifacts`.
