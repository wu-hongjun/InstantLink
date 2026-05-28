# 032 — Bridge Startup Speed & Power Efficiency

Status: **Measured baseline; optimization candidates prioritized**
Author: 2026-05-28
Hardware: Raspberry Pi Zero 2 W (BCM2710A1, 4× Cortex-A53 @ 1 GHz, 512 MB) / Raspberry Pi OS Lite 64-bit Trixie / kernel 6.12.47

## 1. Goal

Minimize "Pi powered on" → "bridge actively scanning for the selected printer" — the user-perceived startup. Today the bridge is **~18 s** from kernel boot to scanning (measured below). Realistic target with the cheap wins: **~12–13 s**. Aggressive target with more invasive work: **~8–10 s** (the hardware floor on this SoC).

Secondary goal: **idle power efficiency** while searching / connected — measured separately in §6 (data TBD).

## 2. Measured baseline (kernel 6.12.47, 2026-05-28)

```
systemd-analyze:    5.191 s (kernel) + 26.257 s (userspace) = 31.449 s
multi-user.target:  26.247 s (userspace)
```

The "31 s" headline is misleading — the **bridge starts scanning much earlier** because it isn't gated on `multi-user.target`. Its actual critical path:

```
instantlink-bridge.service  +3.591 s        ← bridge READY=1 ≈ 12.957 s userspace
└─ dbus.service             @9.366 s +381 ms
   └─ basic.target          @9.346 s
      └─ instantlink-bridge-boot-splash.service @6.943 s +2.400 s  ★ blocker
         └─ local-fs.target @6.895 s
            └─ swap.target  @6.012 s        ← zram + rpi-setup-loop + swap.target ~1.5 s
               └─ systemd-remount-fs @4.252 s +303 ms
                  └─ systemd-fsck-root @3.649 s +487 ms
                     └─ systemd-journald.socket @3.296 s
```

**Bridge scanning ≈ kernel 5.2 s + userspace 12.96 s = ~18.1 s from power-on.**

Top blame (slowest units):

| Unit | Time | On bridge crit path? |
|------|------|----------------------|
| `NetworkManager.service` | 11.710 s | **No** (delays multi-user only) |
| `tailscaled.service` | 4.668 s | **No** |
| `instantlink-bridge.service` (READY=1) | 3.591 s | **Yes** (Python init) |
| `dev-mmcblk0p2.device` | 2.980 s | partial (rootfs wait) |
| `user@1000.service` | 2.476 s | No |
| `instantlink-bridge-boot-splash.service` | 2.400 s | **Yes** (blocks `local-fs.target` for the bridge) |
| `ssh.service` | 1.218 s | No |
| `dnsmasq.service` | 1.030 s | No |

Python import cost of the bridge entrypoint (`python -X importtime -c "import instantlink_bridge.app"`, top contributors):

| Module | Cumulative ms |
|--------|---------------|
| `instantlink_bridge.app` (root) | 1 535 |
| `asyncio` | 506 |
| `instantlink_bridge.ble.client` (incl. `instax` / FFI) | 364 |
| `instantlink_bridge.ble.instax` → `imaging.pipeline` (PIL) | 232 |
| `instantlink_bridge.ui.controller` | 196 |
| `instantlink_bridge.camera.ftp` (pyftpdlib) | 125 |
| `argparse` | 97 |
| `instantlink_bridge.config` | 89 |
| `instantlink_bridge.power.monitor` | 80 |

CPU governor: `ondemand` (all 4 cores). `arm_boost=1`, `initial_turbo=30` already set in `/boot/firmware/config.txt`. `auto_initramfs=0`, `boot_delay=0` already set. Serial console **on** (`enable_uart=1`, `console=serial0,115200 console=tty1`).

## 3. Critical-path budget breakdown (where the ~18 s actually goes)

| Phase | Cost | Notes |
|------|------|-------|
| Kernel + bootloader → userspace handoff | **5.2 s** | quiet/no-console could save ~1 s |
| Early sysinit (fsck + remount-fs + swap/zram) | **~2.7 s** | structurally required; small wins possible |
| Boot splash | **2.4 s** | ★ blocks `local-fs.target`; biggest single-cut |
| `basic.target` → `dbus.service` ready | **~0.5 s** | unavoidable |
| Bridge `ExecStart` → `READY=1` (Python init + agent + provider setup) | **3.6 s** | ★ lazy-import + defer subsystems |
| **Total** | **~18 s** | scanning starts shortly after `READY=1` |

## 4. Quick wins (low risk, single-session)

Each is independently shippable and reversible. Estimates assume no other change.

| # | Change | Est. save | Risk | Effort | Where |
|---|--------|-----------|------|--------|-------|
| Q1 | **Defer the boot splash off the critical path.** Make `instantlink-bridge-boot-splash.service` `Type=oneshot` with `WantedBy=multi-user.target` and **no** ordering before `local-fs.target`/`basic.target`. The splash is cosmetic; nothing should wait on it. Confirm `basic.target` no longer waits. | **~2.4 s** | Low — splash may flash slightly later; bridge unaffected. | Trivial | `bridge/systemd/instantlink-bridge-boot-splash.service` |
| Q2 | **Lazy-load heavy imports in the bridge entrypoint.** Defer `PIL`, `pillow_heif`, `rawpy`, `pyftpdlib`, and the `imaging.pipeline` module until the first FTP image arrives. They are not needed for scanning. Defer `power.monitor` if it does any blocking probe. | ~1–1.5 s | Low — restructure import sites; covered by existing tests. | Medium | `bridge/src/instantlink_bridge/app.py` + imports inside `camera/ftp.py` and `imaging/pipeline.py` |
| Q3 | **Remove serial console from `cmdline.txt` + `enable_uart=0` in `config.txt`** (USB gadget ether stays). Console kernel messages over UART measurably slow boot. | ~1 s | Low — keeps `console=tty1`; SSH over `usb0` unchanged. | Trivial | `/boot/firmware/cmdline.txt`, `/boot/firmware/config.txt` |
| Q4 | **Disable services not needed for scanning at boot:** `tailscaled` (mask or `systemctl disable`), the `actions.runner.wu-hongjun-OpenFilmAdvance.*` GitHub runner (not part of the appliance), `sshswitch`, `rpi-eeprom-update`. Don't disable `ssh.service` (we use it). | ~0.5 s (crit) + frees CPU during boot, helps overall steady-state load | Low — keep tailscaled if remote admin is wanted; can be `WantedBy=multi-user.target` with `After=instantlink-bridge.service`. | Trivial | `systemctl mask <unit>` / `systemctl disable` |
| Q5 | **Add `quiet loglevel=3 vt.global_cursor_default=0`** to `cmdline.txt`. Suppresses kernel boot prints; mild effect. | ~0.3 s | Low — silences boot console; tty1 still usable. | Trivial | `cmdline.txt` |
| Q6 | **Switch CPU governor early to `performance` for the boot window**, then back to `ondemand` once `READY=1` fires. `initial_turbo=30` already gives 30 s of full-clock at boot — verify it's actually engaged (`/sys/.../cpuinfo_cur_freq`); if not, add `force_turbo=0` semantics or set governor explicitly in a pre-`basic.target` oneshot. | ~0.3–0.5 s of bridge init | Low | Trivial | `systemd-tmpfiles` / pre-`basic.target` oneshot |

**Q1+Q2+Q3+Q5 stacked target: ~13 s power-on → scanning.** Test the stack as a unit because Q1 changes the critical path, which can expose or hide other costs.

## 5. Medium-effort optimizations (require care / hardware iteration)

| # | Change | Est. save | Risk | Notes |
|---|--------|-----------|------|-------|
| M1 | **Move zram + swap setup off the early critical path** (defer to after `local-fs.target` or remove entirely; the bridge doesn't need swap). | ~0.5–1 s | Medium — verify nothing pages out under load. | The `rpi-setup-loop@var-swap` + `systemd-zram-setup@zram0` chain costs ~0.8 s on the critical path. |
| M2 | **Pre-import the bridge** via `python -c "import instantlink_bridge.app"` once at image bake time, persisting `__pycache__` (bytecode cache). May already be present; verify. Also `python -O` or `python -OO` to skip docstrings. | ~0.3–0.5 s | Low | Tests behavior under `-O`. |
| M3 | **Spawn the BLE scan in parallel with the rest of bridge init.** Currently the controller waits for the status provider + pairer + UI to be up before scheduling its first poll. Kick off a passive scan as soon as `bluetooth.service` is up and the FFI library is loaded, even before `READY=1`. | ~0.5–1 s | Medium — needs careful sequencing so the first scan doesn't race FFI init. | Code change in `controller.py` startup. |
| M4 | **Slim Python venv**: only install what the bridge actually uses; ensure no `rawpy` / `pillow-heif` import at startup (they're huge wheels). Confirm wheel ABI matches Python 3.13 to avoid build-from-source costs (one-time, but affects deploy). | Mostly disk/RAM, not boot time | Low | `bridge/pyproject.toml`. |
| M5 | **Custom `bluetooth.service` dependencies**: ensure the bridge doesn't sequentially wait on bluetooth (it shouldn't — bridge is `After=dbus.service` only and reports BT readiness asynchronously). Verify `wpa_supplicant` doesn't gate anything we need for BLE-only scanning. | Often 0 (already async) | Low | Read-only audit. |

## 6. Power efficiency — measurement plan (next session)

Not yet measured. Need:
- **Idle power draw** (Pi searching, no printer): probe with a USB-inline meter, or use `vcgencmd measure_temp` + `vcgencmd measure_volts` deltas as a proxy, or instrument `/sys/class/power_supply/*` if the X306 UPS exposes it (likely not).
- **Connected steady-state draw** (keepalive at 10 s).
- **Per-mode drain estimate** when battery is the supply (X306 is LED-only — no fuel gauge — so this is best-effort: time-to-LED-step at known ambient).

Likely-effective levers, once measured:
1. **BLE search rate** — already user-configurable (5/15/30/60 s). 60 s is the low-power option; the search window is 5 s, so the duty cycle is 5/60 ≈ 8 %.
2. **Wi-Fi power_save** on the hotspot interface (`iw dev wlan0 set power_save on`) — usually 50–150 mW.
3. **CPU governor** = `schedutil` or `powersave`. Currently `ondemand`. For an event-driven appliance, `schedutil` is generally a small win.
4. **LCD dim/off** during idle — the existing settings cover this; quantify in mW.
5. **Bluetooth off when no printer selected / fully disconnected for N minutes** — coarse but effective if the appliance is rarely used.
6. **Tailscale runtime cost** (4.7 s boot + continuous keepalives) — quantify; consider opt-in.

## 7. Methodology / how to validate any change

1. **Before/after `systemd-analyze blame` and `systemd-analyze critical-chain instantlink-bridge.service`** — pin the numbers in a comment or commit message.
2. **Wall-clock from power-cut → first `connect_progress stage=scan_started`** — the user-perceived metric. Capture with `journalctl -b --since '@0' -o short-monotonic` filtered to bridge.
3. **Python import cost: `python -X importtime`** before/after lazy-load changes.
4. **Reboot at least 3× per change** — boot times vary by ~5–10 % run-to-run on the Pi Zero 2 W. Take the median.
5. **End-to-end functional test** (clean print) after every shipped change — startup optimizations regress integration if heavy modules are deferred wrong.

## 8. Out of scope

- Replacing Raspberry Pi OS with a custom minimal init (Buildroot/Yocto) — significant payoff but a different appliance.
- Pre-compiled Python (PyOxidizer / Nuitka) — significant rewrites; revisit only if §4–5 are exhausted and we still need to shave seconds.
- Hardware changes (faster SoC, eMMC vs SD) — out of scope until v2.

## 9. Suggested first sprint

1. **Q1** (boot-splash off critical path) + **Q3** (no serial console) + **Q5** (quiet boot) — three trivial config changes, measure together, expect ~13 s.
2. **Q2** (lazy-load) — one focused refactor, executor + codex, expect ~11.5 s after Q1+Q3+Q5.
3. **Q4** (disable tailscaled / GitHub runner / sshswitch / rpi-eeprom-update at boot) — declare appliance defaults; expect tiny crit-path win, but cleans up steady state.
4. Re-measure; decide whether to chase **M1–M3**.

---

## 10. Sprint outcome (2026-05-28)

Q1+Q3+Q5 shipped, Q2 attempted and reverted, splash slimmed, M3 implemented. Final
measurement on hardware: **~15.0 s power-on → bridge `Started` (scan_started ~20 ms before).**
**Net save: ~3 s** (18.1 s → 15.0 s).

### What's deployed
- **Bridge `0.1.16`** (commit `5cdf729`). FFI `libinstantlink_ffi.so` is crates **`0.1.17`** (commit
  `66b95a0`, hybrid connect; unchanged this sprint).
- **Q1 boot-splash** (`bridge/systemd/instantlink-bridge-boot-splash.service`): `Before=` dropped
  from the bridge critical path; `WantedBy=sysinit.target` so it still activates early.
- **Q3 no serial console / Q5 quiet boot** (`bridge/boot/firmware/{config.txt,cmdline.example.txt}`):
  applied to the Pi's `/boot/firmware/cmdline.txt` and `config.txt` (backups at `*.bak.032`).
  Kernel boot **5.19 s → 2.62 s**.
- **Splash slim** (`bridge/src/instantlink_bridge/boot_splash.py`): rewritten to stdlib-only,
  writes a solid RGB565 colour to `/dev/fb1`. Splash unit time **3.7 s → ~1 s**.
- **M3 parallel BLE/FTP setup** (`bridge/src/instantlink_bridge/app.py`): `run_ftp_receive_slice`
  uses `asyncio.gather(start_ftp_service, start_ble_stack)` and `asyncio.to_thread` for the entire
  FTP setup including the pyftpdlib import. Codex-reviewed (HIGH + 2 MEDIUM fixes folded in).

### What got reverted and why (read before retrying)
- **Q2 lazy-load** (commit `92f93a6` reverted `0cec5a6`): deferring pyftpdlib / imaging.pipeline
  out of `app.py` module-load *without* parallelising the consumer just moves the same cost into
  the bridge's serial startup. Measured +1.7 s consistent across 3 boots — not cold cache.
  Lesson: the lazy-load only helps when paired with parallelism (M3). M3 now keeps the deferred
  import inside the to_thread call so its cost overlaps with BLE setup.
- **`0.1.15` stop-scan-before-connect** (Rust, reverted `d035bf6` ↦ restored `4f57404`-style
  active-scan during connect): unrelated to this plan but documented in plan 031 §13 — the
  hybrid `0.1.17` is what currently ships and it preserves both fast and recovery paths.

### Why M3 saved less than the spec predicted (honest)
The journal across cold reboots shows FTP and BLE branches finishing within ~100 ms of each other
at ~3 s into the bridge process — so the gather IS parallel. But:
- ~2 s of pre-gather work (Python imports, `BridgeUi` construction, `build_power_monitor`) is on
  the critical path before `gather` starts.
- ~1 s of post-gather work (FFI library load, ui startup tail) is between `gather` completing and
  `READY=1` firing.
- Both gather branches take ~3 s, so `max(branch_a, branch_b)` doesn't save much vs serial because
  pre-/post-gather already dominate.

Result: scan_started fires only **~20 ms before READY=1**, not the predicted 0.5–1 s. M3 is
*structurally correct* (parallel setup) but speed-neutral on this architecture. Keeping it for the
cleaner control flow.

### Measurement evidence (cold reboot, 2026-05-28)
```
[10.10s] systemd: Starting instantlink-bridge.service
[13.19s] ftp.server_started        ← FTP branch finished
[13.29s] bluetooth.agent_registered ← BLE branch finished (100 ms later)
[14.27s] instantlink.library_loaded ← FFI lib load (post-gather)
[15.02s] bridge.ready
[15.04s] stage=scan_started
[15.08s] systemd: Started instantlink-bridge.service
```
Kernel: 2.62 s. Userspace to bridge `Started`: 12.46 s. Power-on → scanning: ~15.0 s.

### Remaining levers (in cost order)
1. **`dd`-splash** (replace Python boot_splash with a pre-rendered framebuffer blob shipped in the
   repo + `ExecStart=/usr/bin/dd if=… of=/dev/fb1`). Splash ~1 s → ~0.05 s. **Expected: ~14.0 s.**
2. **Lazy FFI library load** (defer `libinstantlink_ffi.so` `dlopen` until first BLE poll instead
   of during `BridgeUi` construction). Saves ~1 s. **Expected: ~13.0 s.** Risk: lifecycle.
3. **Bytecode pre-compile + warm `__pycache__`** at provision time. ~0.5–1 s. **Expected: ~12.5 s.**
4. **§5 M1 — zram off the critical path** (defer to post-`local-fs.target`). ~0.5–1 s.
5. Custom init (Buildroot/Yocto), pre-linked native bridge — out of v1 scope.

### Hard floor
With current Python entry + RPi OS Lite + Pi Zero 2 W, **~12 s is the practical floor**. The
kernel + sysinit chain alone is ~6 s. Anything below ~10 s on this hardware needs a non-Python
bridge or a custom init.

### Open items / lessons for the next session
- The deploy script does **not** sync `bridge/systemd/*.service` — unit changes require manual
  `scp` + `daemon-reload`. **One-line fix in `bridge/scripts/deploy-to-pi.sh`** would prevent this
  trap.
- Python interpreter cold start on the Pi Zero 2 W is ~0.7–1 s; this is the floor for any
  Python-based splash or helper. Replacing with `dd` / shell / native binary is the only way to
  beat it.
- "Q2 was a regression" diagnosis (in §13's earlier draft) was partially wrong — Q2 alone
  regresses, Q2 *with* M3 doesn't. Future maintainers: don't try Q2 again without the M3 thread
  parallelism in place.
