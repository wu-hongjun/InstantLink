# InstantLink — Engineering Handover (2026-06-12)

This doc is the fast briefing for the next engineer (human or Claude Code session) picking up
this repo. It is meant to be self-contained — read this and you can start contributing without
having to reconstruct context.

Last verified: 2026-06-12. Main HEAD: `596230d`. Bridge HEAD on the test Pi: `ad638be`.

---

## 1. What InstantLink is

Three components under one brand:

| Component | What it is | Where it lives |
|---|---|---|
| **App** | macOS SwiftUI app (`InstantLink.app`). Sends photos to an Instax Link printer over BLE or to a Bridge over HTTP. | `macos/InstantLink/` |
| **Bridge** | Raspberry Pi Zero 2 W appliance. Receives camera photos over FTP (hotspot or same-Wi-Fi), prepares them per Instax model, and prints over BLE. Has its own 240×240 LCD + joystick UI. | `bridge/` |
| **Core / CLI / FFI** | Rust workspace: `instantlink-core` (BLE + image pipeline), `instantlink-cli` (terminal binary), `instantlink-ffi` (C ABI for Swift `dlopen`). | `crates/` |

The App talks **to** the Bridge over HTTP (when on the same network) and **to** a printer
directly over BLE. The Bridge talks to the printer over BLE via the same Rust core, loaded as
`libinstantlink_ffi.so` on the Pi.

**Rules of brand naming** (enforced in `/CLAUDE.md`):
- "InstantLink" alone = the umbrella project. Don't use it to mean the App when the distinction
  matters.
- "App" = the macOS app. "Bridge" = the Pi appliance. "Printer" = the Instax device.
- The Bridge LCD UI shows compact strings. Recent example: "Searching Printer" (not "Looking
  for printer" — that string was renamed in commit `ad638be`).

---

## 2. Current versions

- App + crates: **`0.1.43`** (Cargo.toml in all three crates; App built with `bash scripts/build-app.sh 0.1.43`).
- Bridge service version is governed by `bridge/pyproject.toml` and tracked separately.
- The About sheet in App Settings shows the running App + Core versions side by side — use it
  to confirm the installed `.app` is fresh after a rebuild.

**Always bump the three Cargo.toml versions in sync when you rebuild.** See the rationale in
`/CLAUDE.md`.

---

## 3. What just shipped (this session — commits `ccdbea7`, `ad638be`, `596230d`)

### `ccdbea7` docs: terminology + plans 041–046
- `CLAUDE.md` + `README.md` standardised the brand terms (App / Bridge / Printer).
- Six plan docs landed in `docs/plans/041–046`:
  - 041–044: the App UX optimisation phases (Settings hamburger, Main banner audit/impl, image editor audit).
  - 045–046: the desktop disconnected-printer escape audit + A+B+C implementation.

### `ad638be` fix(bridge): LCD screen-off + atomic re-pair + Searching Printer rename
- **LCD screen-off** actually kills the panel now. Root cause: `/sys/class/backlight/fb_st7789v/bl_power`
  was `root:root 0644`, the service runs as `ib`, and `_FramebufferBacklight.turn_off()` was
  silently swallowing PermissionError. Fix:
  - New udev rule `bridge/udev/60-instantlink-bridge-backlight.rules` (`chgrp video`, `chmod g+w`).
  - `bridge/scripts/provision-sd.sh` installs it.
  - `bridge/src/instantlink_bridge/ui/display.py` promotes the bl_power-write failure log from
    `DEBUG` → `WARNING`.
  - Idle defaults dropped: `idle_dim_after_s=30`, `idle_screen_off_after_s=60`,
    `idle_deep_after_s=300`, `idle_poweroff_after_s=1800` (were 300/1800/3600/7200).
  - **Verified live on `riverps-rpi-zero-2w`**: at T+66 s past restart, `bl_power=4` and
    GPIO 24 went LOW — panel physically off.
- **String rename** "Looking for printer" → "Searching Printer" across controller, render, i18n,
  status_indicator docstring, and three test files. Dead alias "Searching for printer" dropped.
- **Re-pair flow** is now atomic. `_execute_forget_and_repair` no longer renders Settings with
  "Printer forgotten" between confirm and the pairing screen — it skips the intermediate render
  via a new `show_status: bool = True` keyword-only arg on `_forget_selected_printer`. Error
  paths ("No printer saved", "Forget failed") still render Settings so failures stay visible.

### `596230d` feat(app): banner unify + Settings hamburger + disconnected-printer escape + Photos drops + 0.1.43
- **Main banner stack** unified behind a new shared `BannerStrip` component
  (`macos/InstantLink/Features/Main/BannerStrip.swift`). The three legacy banner systems
  (`BridgeDiscoveryBanner` — deleted —, update banners, status banner) are gone; `MainView`'s
  `bannerSection` precedence cascade picks the right one.
- **Settings hamburger**: Experimental section folded into a `⋯` Menu in the Settings sheet
  header. `ExperimentalSettingsSection` + `LedTestChannelChip` removed.
- **Disconnected-printer escape (plan 046, A+B+C)**:
  - A. `Forget Printer` button on the Main view, gated on
    `pairingRecoveryMode == .reconnectFallback` so it only appears after a failure. Reuses the
    Settings confirmation dialog strings. `deleteProfile` chains into a fresh `startPairingLoop`.
  - B1. Hero headline names the failed printer ("Couldn't reach …") instead of the generic
    "No printer connected". Redundant "Connection failed" subtitle dropped.
  - B2. `emitStatus(.show(.warning, autoDismiss: false))` at the end of
    `PrinterConnectionCoordinator.enterReconnectFallback` surfaces the failure through the
    `BannerStrip` from 043. `startPairingLoop` fires `emitStatus(.dismiss)` on retry so the
    banner clears.
  - B3. Bluetooth-recovery hint Label appears only in `.reconnectFallback`.
  - C1. Collapsed the dead `if disconnectCurrentPrinter || isConnected { disconnectPrinter }
    else { disconnectPrinter }` in `startPairingLoop`.
  - C2. Bind `currentReconnectTarget()` once instead of evaluating it twice.
- **Photos.app drops** work now. New `macos/InstantLink/Support/ImageDropHandler.swift` exposes
  a shared `imageDropTypes` list (`.fileURL + .image + .jpeg/.png/.heic/.tiff`) and
  `handleImageDrop(providers:into:)`. Both `MainPreviewView` and `ImageEditorView` use it.
  File-URL providers go through the original path (preserves EXIF/orientation/GPS); image-data
  providers are materialised via `loadFileRepresentation` into a temp file we own, then routed
  through `viewModel.addImages`.

---

## 4. Open / partially done

These are the loose threads. None are blockers.

- **Phase 3 implementation (image editor)** — `docs/plans/044-image-editor-audit.md` exists
  with 10 findings + a two-pass direction (Pass A visual quieting, Pass B move
  `SelectedOverlayInspectorView` out of the row). No implementation plan written yet.
  - Three open questions are at the bottom of 044; the user has not picked. Do not start
    implementing without their answers.

- **Phase 4 (Camera capture audit)** — explicitly deferred until Phase 3 is done.

- **Reconnect timing** (plan 045 finding F9) — `attemptConnection`'s 3-second deadline may be
  too short for cold BLE adverts on real hardware. Not measured. Out of scope for 046.

- **`PrinterPickerSheet` redesign** (plan 045 finding F3) — "Switch Printer" opens a sheet that
  is unhelpful when only the dead saved printer is around. Out of scope for 046; would couple
  with a broader Printers panel rethink.

- **Bridge venv on the Pi has no `pytest`** — when I tried to run the bridge test suite live
  on the Pi during the screen-off work, the deployed venv didn't have pytest installed
  (it's a runtime venv, not dev). Tests pass logically; not run end-to-end on hardware.

- **App-side test coverage** — there is no Swift test harness in this repo. UI changes are
  verified by build + run + manual test. Document any new behaviour with a steps-to-reproduce
  comment if it's non-obvious.

---

## 5. How to do common things

### Build + install the App
```bash
bash scripts/build-app.sh 0.1.44   # bump version per CLAUDE.md
# Always rm before cp — bare `cp -R` over an existing bundle can leave stale files:
pkill -x InstantLink; sleep 1
rm -rf /Applications/InstantLink.app
cp -R target/release/InstantLink.app /Applications/InstantLink.app
open /Applications/InstantLink.app
```

### Verify Rust workspace
```bash
cargo fmt --all && cargo clippy --workspace -- -D warnings && cargo test --workspace
```

### Reach the test Bridge
The Pi is reachable over its USB-gadget link at `192.168.7.1` from this Mac's `en10` interface.
SSH user `hongjunwu`. Use `-B en10` (or `BindInterface=en10` for `scp`) — the `/22` netmask on
`en0` collides with `192.168.7.x` otherwise. Diagnostic recipes:
```bash
# Inspect the LCD backlight path on the Pi:
ssh hongjunwu@192.168.7.1 'ls -la /sys/class/backlight/fb_st7789v/'
ssh hongjunwu@192.168.7.1 'cat /sys/kernel/debug/gpio | grep GPIO24'
ssh hongjunwu@192.168.7.1 'sudo cat /etc/InstantLinkBridge/config.toml | grep ^idle_'
```

### Deploy bridge code to the Pi (when changing bridge code, not config)
The deploy script needs `INSTANTLINK_BRIDGE_HOST` / `_USER` env vars:
```bash
INSTANTLINK_BRIDGE_HOST=192.168.7.1 INSTANTLINK_BRIDGE_USER=hongjunwu \
bash bridge/scripts/deploy-to-pi.sh --restart
```
For the LCD screen-off fix, the udev rule also needs to be picked up at provisioning time — the
existing deployed Pi has the rule manually `install`'d into `/etc/udev/rules.d/`; a fresh image
will get it via `provision-sd.sh`.

### Run bridge tests
```bash
cd bridge && python -m ruff check src tests && python -m mypy src tests && python -m pytest -q
```
No local venv is set up automatically — use whatever Python ≥3.11 you have, or create one in
`bridge/.venv`.

---

## 6. Where the recent stale-doc fixes landed

When picking up this work, treat these as already-current:
- `/CLAUDE.md` (terminology, FFI count corrected, example app version updated).
- `/README.md` (What's Included table reorganised).
- `bridge/docs/current-context.md` (verified date + commit + idle thresholds refreshed).

If you discover further staleness, fix it in the same PR — don't leave it for next time. The
audit pattern for this is:
```bash
grep -rn --include='*.md' \
  --exclude-dir=.claude --exclude-dir=references --exclude-dir=tmp \
  --exclude-dir=.pytest_cache --exclude-dir=plans --exclude-dir=node_modules \
  -E "<keyword>" .
```
Keywords worth sweeping any time you change a UX string, a config default, or a public symbol.

---

## 7. Pointers

- Project instructions: `CLAUDE.md` (root) + `bridge/CLAUDE.md`.
- Architecture: `docs/development/architecture.md`, `bridge/ARCHITECTURE.md`,
  `bridge/HARDWARE.md`, `bridge/DECISIONS.md`.
- Bridge "what's deployed today": `bridge/docs/current-context.md`.
- Plan archive (audits + implementations): `docs/plans/001–046`.
- FFI reference: `docs/reference/ffi.md` (canonical export list; 22 Rust exports, 20 wired by
  Swift).
- BLE protocol notes: `docs/reference/protocol.md` and `bridge/docs/printer-protocol-notes.md`.

---

## 8. Open the next session with

Paste the following as your first message in a new Claude Code session to bring the assistant
up to speed cold:

> I'm continuing work on InstantLink at `/Users/hongjunwu/Repositories/Git/InstantLink`. Read
> `docs/handover.md` first — it's the self-contained briefing. Main HEAD is `596230d`, App at
> 0.1.43, Bridge verified at `ad638be` on the test Pi (`riverps-rpi-zero-2w`, reachable at
> `192.168.7.1` over `en10`). Open threads listed in §4 of the handover. Next user-facing
> priority is Phase 3 image-editor implementation, but only after the three open questions in
> `docs/plans/044-image-editor-audit.md` are decided. Don't start that without explicit user
> direction. For LCD/Bridge work, the `bridge/docs/current-context.md` doc is the freshest
> picture of what's deployed.
