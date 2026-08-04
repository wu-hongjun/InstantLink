# 056 — Bridge performance: boot time and image conversion

## Why

Two user-reported symptoms — "the Zero 2 W boots too slowly" and "it converts
images too slowly" — were audited against the live device (`192.168.7.1`,
2026-08-02) by four parallel agents: boot path, Python startup, image pipeline,
and OS/runtime. Every number below is measured on real hardware unless marked
*estimated*.

**Both symptoms turned out to be bugs, not slow hardware.**

## Verified on hardware (2026-08-03)

Deployed to the live Pi and confirmed with a real print: Sony a7C II →
`DSC01595.HIF` (5.19 MB) → hotspot FTP → Instax Square `INSTAX-52006924`.

### Boot — fixed

| | Before | After |
|---|---|---|
| `systemd-analyze` total | **1 min 35.8 s** | **20.1–20.5 s** |
| Boot splash on screen | **95.79 s** | **9.87 s** |
| `/dev/fb1` tags | `:seat:` | `:systemd:seat:` |
| `dev-fb1.device` | inactive | active |
| FTP listening | 14.34 s | 13.72 s |
| `bridge.ready` | 16.55 s | 15.33 s |

Confirmed stable across three separate cold boots, including an unplanned
power cycle.

### Print path — both changes fired

```
07:37:29.312  bridge.print_start         path=…/DSC01595.HIF
07:37:29.316  instantlink.image_prepared source=preview model=square
                                          bytes=102728 quality=90 prepare_ms=0
```

* **T1.1 confirmed** — `source=preview`, `prepare_ms=0`, logged 4 ms after
  print start. The pipeline ran once (building the preview), not twice.
* **T1.3 confirmed** — `quality=90` handed to the core, not the configured
  `100`. At 102 728 bytes against Square's 105 000 budget the core's search
  accepts on its first encode instead of inflating to ~400 KB.
* **No OOM kills**; 181 MB available throughout.

Full cycle: FTP upload 7.56 s → preview build ~1.85 s → 5.00 s countdown →
BLE transfer and print 24.03 s ≈ **38.4 s** end to end. The 24 s print and
7.6 s upload dominate; transcode does not. Square's `packet_delay_ms=150`
across ~57 chunks is ~8.5 s of that 24 s by design.

### Import cost

Min-of-7 subprocess runs on the Pi: ~1676 ms → **1442 ms**. `-X importtime`
confirms `segno`, `importlib.metadata` and `multiprocessing` are absent from
the service import path.

### Transcode, and a caveat that changes Tier 2's priority

Benchmarked on the Pi with a realistic 29 MB / 33 MP JPEG (the quality search
actually engaging), Square:

| Profile | Time |
|---|---|
| Live config after T2.1 + `sharpness = 0` | **2743 ms** |
| Same with `sharpness = 5` restored | 4654 ms |
| No adjustments at all | 2612 ms |

* Dropping `sharpness` 5 → 0 saved **1911 ms**, within 1 % of the audit's
  1893 ms prediction. That setting is a factor of **1.05** applied at 8.2 MP
  and then downscaled 4× — it was costing 41 % of transcode to do something
  the resize almost entirely erased.
* Saturation now costs **131 ms instead of 923 ms** (T2.1), same pixels.

**But the real print was a `.HIF`, not a JPEG.** The HEIF path uses
`heif-thumbnailer -s 1600`, so the working image is ~1600 px rather than the
3504×2336 the JPEG draft path produces. The JPEG benchmarks above therefore
do **not** describe a HIF workflow: T2.1's saving is proportionally smaller
there, and **T2.2 (the `MINI_WORKING_EDGE` constant) barely matters at all**.
Re-measure against the actual source format before investing in T2.2.

### Not yet exercised

**T1.6** cannot fire while T1.1 succeeds — it is the fallback for
`auto_print_delay_s = 0`, where no preview is built. Measuring it needs a
separate run with that config.

## Measured baseline

### Boot

| Milestone | Time |
|---|---|
| First pixel on the LCD | **14.4 s** |
| `bridge.ready` (`READY=1`) | 16.55 s |
| Wi-Fi camera can associate and upload | **20.97 s** |
| `multi-user.target` | 20.86 s |
| `systemd-analyze` total | 1 min 36 s ← **artifact, see B1** |

Within the service: ExecStart → FTP listening = 4.06 s, → `bridge.ready` = 6.27 s.
`import instantlink_bridge.app` is 1.81 s warm, ~2× that cold.

### Transcode

Source: 7008×4672 (32.7 MP) 11.1 MB JPEG q90 4:2:0 — matches a Sony a7C II Fine JPEG.

| Profile | Time |
|---|---|
| Identity adjustments | **2491 ms** |
| Non-identity adjustments | **OOM-killed** (see I1) |

Stage breakdown at the current 8.2 MP working size: decode 973 ms, `exif_transpose`
85 ms, `convert("RGB")` 27 ms, fit (LANCZOS) 449 ms, encode search 270 ms (8 encodes).

## The two headline bugs

### B1 — the boot splash has never run early

`systemd/instantlink-bridge-boot-splash.service:19-20` declares
`After=`/`Wants=dev-fb1.device`. udev does not tag fbdev nodes with `systemd`
(`udevadm info /dev/fb1` → `TAGS=:seat:`), so `dev-fb1.device` never activates and
the unit blocks on the full 90 s `DefaultDeviceTimeoutUSec`. It runs at **t+96.17 s**.

The entire 1 min 36 s `systemd-analyze` figure is this one unit. Real boot is ~21 s.

Consequence: the LCD is dark from power-on until the main UI's first `_render()` at
~14.4 s. **This is the most likely source of the "boots too slowly" perception** —
there is no feedback for two-thirds of the boot, and the thing designed to provide
it never fires.

The unit's own comment block (lines 13-18) documents choosing `dev-fb1.device` over
`systemd-udev-settle` to avoid a race. The chosen alternative simply never fires.

### I1 — the pipeline OOM-kills the Pi, and runs 3–5× per print

**OOM:** `_apply_vignette` (`imaging/postprocess.py:265`) does
`np.array(image, dtype=np.float32)` on the 8.2 MP working image = **98 MB**, plus a
33 MB factor map, on top of three live 25 MB RGB buffers. The Pi has ~230 MB
available with 150 MB of swap already consumed. Two reproducible kills
(`dmesg`: `Out of memory: Killed process … total-vm:640000kB`). A non-identity
adjustment profile on a 33 MP source is not slow — the worker dies.

**Repeated work:** nothing caches a decoded image anywhere in `imaging/` or
`ui/controller.py`.

| Site | What it does |
|---|---|
| `ui/controller.py:860` | Builds the preview by running the entire pipeline |
| `ui/controller.py:1058` | Re-runs the entire pipeline from the original 33 MP file on **every joystick nudge** of zoom/crop/rotate (~2.5 s each) |
| `app.py:996`, `app.py:1009` | Pass `received.path` — the *original* file — to the print backend |
| `ble/instantlink.py:495` | Runs the whole pipeline **again** |

End-to-end for a previewed print with two edit nudges: **~12 s**, projected **~2 s**
after Tier 1 + Tier 2.

## Tier 1 — pure wins, no output pixels change

**All implemented** (2026-08-02). `ruff` + strict `mypy` clean, 1106 tests
passing (14 new in `tests/test_prepared_print_reuse.py`). Not yet deployed —
every gain below is projected from the measurements above, not yet re-measured
on the device.

| # | Fix | Gain | Status |
|---|---|---|---|
| T1.1 | Reuse the preview's `PreparedImage` for the print (option B) | **halves the default config: 2 pipeline runs → 1** | done |
| T1.2 | Fix the `dev-fb1.device` dependency via a udev `TAG+="systemd"` rule | 5 s of blank screen; −80 s off the reported number | done |
| T1.3 | Stop the Python→Rust double encode | 270 ms + a JPEG generation | done |
| T1.4 | Guard the two no-op full-buffer copies | 112 ms + 50 MB peak | done |
| T1.5 | Lazy-import `segno`, `importlib.metadata`, `multiprocessing` | 274 ms warm, ~2× cold | done |
| T1.6 | Run image prep concurrently with the BLE connect | hides seconds, `auto_print_delay_s=0` path | done |
| T1.7 | `boot-diet.sh --production` drops tailscaled / rpi-connectd / Actions runner | ~110 MB of 512 MB; tailscaled is +5.17 s in the boot critical chain | done |

### T1.6 detail

Prep needs no BLE link, so it is submitted to a single-worker
`ThreadPoolExecutor` *before* `_ensure_connected_blocking`, and collected after
model detection. Only speculated when `model_override` is set — that is the
model it builds for — and the result flows through the **same** mismatch guard
as T1.1's, so a wrong guess is discarded rather than printed. A speculative
failure returns `None` (`_speculative_prepared`) so the synchronous prepare
still raises the authoritative error; the executor is shut down with
`wait=True` so a prep can never outlive its print.

Note this only bites when T1.1 did *not* supply an image — i.e. at
`auto_print_delay_s = 0`, where no preview is built. At the shipped default the
preview already covers it.

### T1.7 detail

Deliberately **not** added to `SAFE_DISABLE_UNITS`: `--apply` is routine, and on
a dev unit tailscaled is how you reach the Pi. The new `--production` mode is
opt-in, warns before disabling, and discovers Actions runner units by glob
(`actions.runner.*.service`) since they are named per registration.

### T1.1 status: B implemented, A outstanding

**B is done.** The preview now builds the InstantLink-backend flavour
(`apply_model_flip=False`) and stashes it; `BridgeUi.take_prepared_print_image`
hands it to the print path, consumed once, keyed on `(source path, edit)` and
dropped whenever a new preview session starts. `print_file_to_printer`
re-verifies `prepared.model` against the model detected on connect and falls
back to preparing normally on any mismatch. Bound via `functools.partial` at the
sender selection site so the `PrinterSender` protocol keeps its 5-positional
signature and injected test senders are unaffected.

Effect: with the shipped default (`auto_print_delay_s = 5.0`) a print goes from
**two full pipeline runs to one**. At `auto_print_delay_s = 0` the preview is
skipped entirely (`ui/controller.py:754`), nothing is cached, and the print path
behaves exactly as before.

**Side effect — a display bug fixed.** `create_preview_from_prepared` never
un-flipped, so the LCD preview on `MINI_LINK3` (the only `flip_vertical` model)
was showing vertically flipped. Building the preview in backend flavour makes it
upright. Covered by `tests/test_prepared_print_reuse.py`.

**A is still outstanding**, and the constraint below is why it needs care.

### Why the obvious version of A does not work — process isolation

The audit's fix ("cache the decoded image keyed by source path") **does not work
as stated.** The two paths do not share a process:

- **Preview and every edit nudge** go through `prepare_for_instax_async`
  (`ui/controller.py:860`) → `imaging/worker.py:_create_process`, which forks a
  **fresh `multiprocessing.Process` per job**. A module-level cache is populated
  in the child and dies with it.
- **The print** goes through `asyncio.to_thread` (`ble/instantlink.py:308`) — a
  thread in the *main* process, and a single run with nothing to reuse.

So an in-process LRU buys nothing. Three viable designs:

**A — disk-backed working-size cache.** Write the decoded, EXIF-corrected,
working-size image once, keyed by `(path, mtime, working_size)`; later runs decode
that instead of the 33 MP original. Works across processes. Its remaining value
after B is the **edit-nudge loop only**.

Format is load-bearing, not a detail — measured against the 973 ms decode it
replaces, at the SD's 22.7 MB/s:

| Format | Size | Write | Read | Decode | Net |
|---|---|---|---|---|---|
| Raw RGB / BMP | 24.6 MB | ~1.08 s | ~1.08 s | ~0 | **~1.1 s — slower than no cache** |
| PNG lossless | 15–20 MB | slow | ~0.8 s | ~1 s | worse |
| **JPEG q95–98** | **3–5 MB** | ~0.2 s | ~0.2 s | ~0.4 s | **~0.5 s saved** |

So JPEG only, and ~3–5 MB is small beside the 11.1 MB original FTP already writes
to `incoming/`. Two constraints:

- **Eviction cannot rely on cleanup-on-completion.** `incoming/` is already never
  pruned (94 MB of stale files), the worker gets OOM-killed, and the appliance is
  hard-powered-off — all three skip a delete step. Needs a budget-bounded cache
  with LRU eviction plus a clear-on-start sweep, reusing the `SyncOutbox` /
  `outbox_budget_mb` pattern rather than a second mechanism.
- **Compounding with B**: if a nudge repopulates from the cache and B then hands
  that image to the print, the print inherits the cache's JPEG generation. q98
  keeps that under control for ~1 MB more.

**C — run preview prep in a thread instead of a fork**, making a normal in-memory
LRU work. **Rejected: conflicts with a deliberate safety property.** The worker
exists to be *killable* (`ImagePreparationTimeoutError`, `worker.py` — "Async,
killable image preparation worker"). A hung or oversized decode would become
unkillable.

Recommended sequence: B (done) → measure the nudge path on-device → then decide
whether A's ~500 ms/nudge justifies a cache subsystem.

### T1.3 detail

`ble/instantlink.py:495` prepares a JPEG already sized under `spec.max_image_size`
(typically q74), writes it to a temp file, then passes the **config** quality —
default **100** — to `instantlink_print_with_progress` (`:529`). The Rust core
decodes that JPEG and re-encodes it with its own binary search
(`crates/instantlink-core/src/image.rs:170` → `:153` → `encode_jpeg` at `:72`),
inflating it back to ~412 KB before searching down again.

That is a third full encode pass **and** a generational double-JPEG quality loss.
Minimal fix: pass `prepared.quality` instead of the config quality, so the Rust
search converges on its first encode. Longer term, exactly one layer should own the
size budget.

### T1.5 detail

`segno` is the best ms-per-line-of-diff in the repo: 164 ms, one call site
(`ui/render.py:2431`, only reached in `SYNC_PAIRING`). `segno/__init__.py`
unconditionally loads `writers`, dragging in `xml.sax.saxutils` →
`urllib.request`/`http.client`/`email` — 93 ms of stdlib on every boot.

The existing lazy-import discipline is otherwise **already excellent**: aiohttp,
zeroconf, bleak, rawpy, pillow-heif, numpy, dbus-fast, gpiozero, luma, spidev,
pyftpdlib and cryptography are all verified absent from the service import path.

## Tier 2 — large wins that change output pixels or need validation

### T2.1 — adjustments after the fit (17–19×, and it removes the OOM)

Move `apply_adjustments` (`pipeline.py:206`) after `_fit_image` (`:208`). Measured
on the Pi, working res (3504×2336) vs output (600×800):

| Axis | @working | @output | Ratio |
|---|---|---|---|
| saturation | 923 ms | 51 ms | 18× |
| exposure | 1060 ms | 57 ms | 19× |
| sharpness | 1893 ms | 105 ms | 18× |
| vignette | **OOM** | 95 ms | — |
| hue | **OOM** | 408 ms | — |
| all four | ~5.5 s *(est.)* | 313 ms | ~17× |

**Safe to move now** (pointwise, commutative with resampling apart from clipping):
saturation, exposure, hue.

**Changes the look — but arguably fixes bugs:**

- **sharpness**: `ImageEnhance.Sharpness` is a 3×3 convolution. Applied at 8.2 MP
  then downsampled 4×, it is almost entirely low-passed away — the slider is close
  to a no-op today. Post-fit it actually does something.
- **vignette**: geometry is normalized to image dimensions
  (`postprocess.py:248-253`). Pre-fit it centres on the *uncropped* working image
  and `ImageOps.fit` then crops 25–50% away, so print corners are unevenly
  darkened. Post-fit it centres on the actual print.
- **overlays** (`_render_overlay`, `postprocess.py:271`): a bottom-left watermark on
  a 3:2 source cropped to 3:4 can be cropped clean off, and the font size
  (`h//30` clamped to 48, `:296-300`) is computed on working height then shrunk
  2.9× → ~16 px on an 800 px print instead of the intended 26.

`postprocess.py:147` documents pre-fit as deliberate. That reasoning does not
survive the AUTO-crop case. **Requires a product decision on the look change.**

### T2.2 — working size is one constant from a 1.79× win

`draft()` only scales by powers of two, and `MINI_WORKING_EDGE=1200`
(`pipeline.py:423`) sits *just above* the /4 boundary for a 3:2 33 MP source
(7008/4 = 1752×1168; 1168 < 1200 → rejected → /2):

```
draft(800)  -> 1752x1168  2.0 MP   812 ms
draft(1100) -> 1752x1168  2.0 MP   764 ms
draft(1200) -> 3504x2336  8.2 MP   973 ms   <-- current MINI
draft(1600) -> 3504x2336  8.2 MP   909 ms   <-- current SQUARE/WIDE
```

A 32-pixel constant quadruples the pixel count of every downstream stage. Measured
end-to-end 2491 → 1390 ms. Decode itself barely improves (17%) because entropy
decoding dominates over IDCT scaling — the win is all downstream.

**Must be made zoom-aware.** `_zoom_and_offset` (`pipeline.py:319`) crops to
1/zoom with zoom up to 3.0, so use `edge = max(w,h) * max(1.0, zoom)`. Note today's
1200 is *already* below what zoom=3 needs — a latent quality bug independent of
this change.

### T2.3 — `cgroup_disable=memory`

`/proc/cmdline` carries `cgroup_disable=memory` (firmware-injected on ≤512 MB
boards). `/sys/fs/cgroup/cgroup.controllers` = `cpuset cpu io pids` — no memory
controller. Every `MemoryMin=`/`MemoryMax=` on the bridge unit is **silently
inert**, memory PSI is empty, and systemd-oomd cannot function.

Concretely: the bridge has 30.8 MB swapped to zram against 25 MB RSS, with
`pgmajfault 10730` / `pswpin 7070`. Fix: append `cgroup_enable=memory` via
`bridge/config/cmdline-token.txt` (later args win). Cost ~1–2% RAM for accounting.

### T2.4 — `dtparam=sd_overclock=100`

SD measures 22.7 MB/s sequential, 10.8 MB/s at 4K — that is the 50 MHz bus limit,
not the card. Boot is dominated by ~2500 small Python/`.so` reads, and the Python
audit independently found cold-cache SD reads (not CPU) to be the bottleneck:
a cold import attributed 13.7 s with `yarl._quoting_c` alone at 2.13 s.

Risk: card-dependent, silent-corruption failure mode. The BOM's SanDisk Industrial
A1 handles it, but it must be validated per-SKU. Apply in
`bridge/config/boot-firmware-config.append`.

### T2.5 — encode seeding

The search runs **8 encodes** (`[100, 50, 75, 62, 68, 71, 73, 74]`, 270 ms) on every
print, because `printer.quality` defaults to 100 and q100 yields 412 KB against a
102 KB budget — the full descent is guaranteed. Measured curve (600×800,
`subsampling=2`): `q100=412K q90=170K q80=118K q75=102K q70=92K q60=76K q50=65K`.

Seed from a per-model table (Mini ≈ 78) plus one or two corrections → 2–3 encodes,
~180 ms saved. `MINI_LINK3` has `max_image_size=55_000` (`ble/models.py:56`), half
of Mini's, so its search runs deeper.

Note: dropping `optimize=True` during the search saves only ~14 ms on the Pi
(53 → 29 ms/encode). **Deprioritised** — the Mac ratio (4.4×) badly overstates it.

## Tier 3 — deferred

- **`@dataclass(frozen=True)` costs ~377 ms**, ~21% of all import time (107
  decorators; 62 classes / 349 fields on the service path). `slots=True` is nearly
  free — the cost is `frozen=True` (~123 ms) plus irreducible dataclass machinery.
  Naive removal breaks nested defaults (`config.py:508` → `ValueError: mutable
  default`), so each site needs `field(default_factory=…)` and loses immutability.
  `typing.NamedTuple` is ~55% cheaper per class and keeps the guarantee.
  *Medium-high risk; revisit only if boot is still the complaint after Tiers 1–2.*
- **Bind FTP before importing UI/BLE** — worth ~710 ms to time-to-uploadable
  (`import camera.ftp` alone is 1097 ms vs 1807 ms for `app.py`). Large mechanical
  diff; `BridgeUi` construction (`app.py:283`) must move after the FTP thread spawn.
- **`arm_freq` 1000 → 1100/1200** — ~10–17% on transcode, but a 60 s bench load
  already hit 73.1 °C bare-board and still climbing, and `over_voltage` raises draw
  on a single 18650. Enclosure venting is an aspiration in `HARDWARE.md`, not a
  validated design.
- Blacklist the unused V4L2/camera stack and shrink CMA (`CmaFree` is 184 kB of
  65 MB; ~2 MB module text, ~32 MB reclaimable).
- vm sysctls: with zram-only swap and a 10.8 MB/s 4K SD path the usual advice
  inverts — `vm.swappiness` 100–150, `vfs_cache_pressure` 50.
- Manager service ordering: it imports aiohttp at module scope (4.0–4.4 s warm,
  13.7 s cold) starting 5.4 s into the bridge's startup on a box with 30 MB free,
  evicting the bridge's page cache. Add `After=instantlink-bridge.service`.
- `/boot/firmware` fstab passno 2 → 0 (~0.8 s; `fsck.fat` finds the dirty bit every
  boot because the appliance is hard-powered-off).
- Swap setup chain ~1.0–1.5 s (`rpi-resize-swap-file` re-runs `mkswap` on a 463 MB
  file every boot). **Medium-high risk** — 135 MB of swap is currently in use.

## Ruled out with measurement — do not revisit

- **CPU governor.** `ondemand`, but the CPU sits at 1000 MHz (max) 98–100% of the
  time; ramp under load was 0.00 s. `initial_turbo=30` makes it structurally
  irrelevant to boot. Pinning `performance` buys ~0% and *costs* battery at idle.
- **Thermal throttling.** `throttled=0x0`, no history bits; 60 s 4-core saturation
  went 58 → 73.1 °C with zero throttle events (soft limit 80 °C).
- **Pillow build.** 11.3.0 with libjpeg-turbo 3.1.1 and zlib-ng 2.2.4 — already
  optimal.
- **Worker process overhead.** `worker.py:306-317` forks per job; measured **90 ms**
  (2488 vs 2398 ms). Not worth pooling. Only 1 of 4 cores is used, but Pillow ops
  are single-threaded and one image is inherently serial.
- **`reducing_gap=2.0`** — measured *slower*, because `ImageOps.fit` crops first.
- Already covered by `boot-diet.sh` and verified live: `NetworkManager-wait-online`
  disabled, apt/man-db timers disabled, `gpu_mem=16`, `initial_turbo=30`,
  `disable_splash`, `boot_delay=0`, `camera_auto_detect=0`, `auto_initramfs=0`,
  `max_framebuffers=1`, `audio=off`, serial console off, `quiet loglevel=3`,
  `noatime`, `/tmp` on tmpfs, zram correctly tuned (485 MB zstd, 4.2:1).

## Landmines

- **Do not move `incoming/` to tmpfs naively.** `SyncOutbox.add()`
  (`sync/outbox.py`) uses `os.link(source, spool_path)` with a `shutil.copy2`
  fallback. `os.link` requires the same filesystem, so splitting `incoming_dir`
  (`config.py:161`) from `outbox_dir` (`config.py:336`) silently degrades every
  sync from an inode link to a full multi-MB copy. Net loss in sync mode, win in
  print-only mode — gate on delivery mode if pursued.
- **Keep zram.** It is correctly configured and is what keeps a 512 MB box with
  36 MB image buffers from OOMing. Reduce demand (T1.7, T2.3), don't retune it.
- **`resample` and working size overlap.** Once T2.2 drops the working size to
  2 MP, fit falls to ~110 ms and a `reduce()` prepass saves little. Measured at
  8.2 MP: LANCZOS 449 ms, `reduce()`+LANCZOS 247 ms, BICUBIC 317 ms, BILINEAR
  183 ms (aliases visibly — not acceptable for print). **Do not count both.**

## Bugs found incidentally

- **`incoming/` is never pruned.** 94 MB of `.HIF` files dated May–June 2026 on the
  live unit. `bridge/CLAUDE.md` states "storage is ephemeral" — this is a spec
  violation and unbounded SD wear. **Fixed (2026-08-03):** new
  `[ftp].incoming_budget_mb` (default 512), enforced by `prune_incoming_dir`
  oldest-first at startup *and* on every arrival. Both call sites are needed
  for the reason recorded under T2.5's landmines: the appliance is
  hard-powered-off and the image worker can be OOM-killed, so no
  completion-time hook can be relied on. The most recent 8 files and anything
  modified within 5 minutes are exempt regardless of budget, which is what
  keeps a queued or mid-print file safe — the queue drains one job at a time
  and a print takes tens of seconds.
- **`boot_splash.py` (93 lines) is dead code** — the unit uses `dd` (`:31`) and
  nothing imports it.
- **Stale venv path**: `_editable_impl_instantbridge.pth` points at the removed
  `/opt/InstantBridge/src`. `site` drops it, so cost ≈ 0, but it is stale state.
- **Stale NM profiles** accumulating: `InstantLink.2YJ1R3`, `InstantLink.LDE2S3`.
  `delete_stale_hotspot_profiles` (`scripts/wifi-mode.sh:134`) only cleans
  hotspot-named ones.
- `arm_boost=1` is in the live `config.txt` but is a **no-op on Zero 2 W** (Pi 4B
  only); it is not in `boot-firmware-config.append`, so it is stray.

## Not yet measured

The boot capture ran with the Instax powered **off**, so BLE reconnect scanned in a
5.3 s-scan / 2 s-backoff loop throughout. The print-ready half of "ready to receive
and print" is unmeasured. Re-capture with the printer on before ranking any
BLE-side work.
