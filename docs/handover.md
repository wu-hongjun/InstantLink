# InstantLink — Engineering Handover (2026-06-13)

This doc is the fast briefing for the next engineer (human or Claude Code session) picking up
this repo. It is meant to be self-contained — read this and you can start contributing without
having to reconstruct context.

Last verified: 2026-06-13. Main HEAD: `9d00c22` (Plan 048 PR #17 lands on top of this). Bridge HEAD on the test Pi: `ad638be` (unchanged from the previous handover).

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
- The Bridge LCD UI shows compact strings (recent rename: "Searching Printer" — landed in
  `ad638be`).

---

## 2. Current versions

- App + crates: **`0.1.45`** (Cargo.toml in all three crates; App built with `bash scripts/build-app.sh 0.1.45`).
- Bridge service version is governed by `bridge/pyproject.toml` and tracked separately.
- The About sheet in App Settings shows the running App + Core versions side by side — use it
  to confirm the installed `.app` is fresh after a rebuild.

**Always bump the three Cargo.toml versions in sync when you rebuild.** See the rationale in
`/CLAUDE.md`.

---

## 3. What just shipped (this session — plan 048, all 17 PRs)

The entire Photos-style editor rebuild scoped in `docs/plans/047-photos-style-editor-audit.md` /
`docs/plans/048-photos-style-editor-implementation.md` landed across 17 PRs. The legacy
`EditorViews.swift` (1364 lines) is **deleted**; the `useNewEditor` feature flag is **gone**;
the new editor is the only editor. See plan 048 §PR Status for per-PR commit hashes.

Shipping summary by surface:

- **Editor shell** (PR #1) — top tab bar, HSplitView, active-tab routing, observable
  `EditorViewState`, undo/redo with 200 ms debounce, MTKView preview via `CIRenderDestination`.
- **Crop tab** (PR #2) — aspect / straighten / V/H / flip / frame; print-aware Mini / Square /
  Wide aspect presets.
- **Adjust tab** — Light (PR #3), Color (PR #4), Curves + Levels + Histogram (PR #5), Vignette
  (PR #6), Sharpen (PR #7), Noise Reduction (PR #8), Definition (PR #9), Selective Color
  (PR #10, 6 user-defined wells via custom `CIColorKernel`), Red Eye (PR #11, Vision
  auto-detect + click-to-fix), White Balance + shared Eyedropper infrastructure (PR #12),
  Black & White mode (PR #13).
- **Annotate tab** (PR #14) — ported the legacy overlay system (text / QR / timestamp / image /
  location) into the new shell; deleted `EditorViews.swift`; retired the `useNewEditor` flag.
- **Filter rail** (PR #15) — vertical thumbnail strip + `FilterThumbnailCache` + `FilterCatalog`
  with the B&W ↔ Filters interop override from decision Q9.
- **Auto buttons** (PR #16) — per-section Auto wired to `CIImage.autoAdjustmentFilters` + global
  Enhance (magic-wand) toolbar button.
- **Polish + fidelity pass + version bump** (PR #17 — this session's commit):
  - `AdjustmentSlider`: option-drag extended range (±2× via a simultaneous `DragGesture`),
    double-click reset on the row, `accessibilityLabel`/`accessibilityValue` plus
    `accessibilityAdjustableAction` for VoiceOver.
  - Pipeline coefficients tuned: `LightPipeline` contrast multiplier `0.6 → 0.5`; brilliance
    composite + Cast scales reconfirmed against the research files. Vignette ramp documented
    as intentionally linear.
  - Histogram refresh already debounced to 100 ms via Combine (verified, no change needed).
  - Localization backfill for the 7 non-CJK locales (de, es, fr, it, pt-BR, ar, he) on the
    tab bar, every section title, the 7 Light section slider labels, and the common
    button verbs (Done / Revert / Undo / Redo / Auto / Reset / Enhance).
  - Stale `editor_coming_in_pr_2` and `editor_coming_in_pr_3` keys dropped from all 12
    locales.
  - PR #14 audit nits cleared: `OverlayListRow` help-text now describes the action
    (Lock/Unlock, Hide/Show) using new `annotate_overlay_{lock,unlock,show,hide}` keys;
    `displayTitle` + `defaultTitle` extracted to `OverlayItem` and the duplicated copies in
    `OverlayListRow` and `OverlayInspectorView` are gone; "Select an image to print"
    replaced with the dedicated `annotate_select_image_overlay` key; film-frame Q4
    decision documented in `EditorPreview.swift` (the editor canvas is pixel-accurate and
    intentionally does not render the Instax border).
  - Crate versions bumped to **0.1.45** for `instantlink-core` / `instantlink-ffi` /
    `instantlink-cli` to match the App.

---

## 4. Open / partially done

These are the loose threads. None are blockers.

- **Reconnect timing** (plan 045 finding F9) — `attemptConnection`'s 3-second deadline may be
  too short for cold BLE adverts on real hardware. Not measured. Out of scope for 048.

- **`PrinterPickerSheet` redesign** (plan 045 finding F3) — "Switch Printer" opens a sheet that
  is unhelpful when only the dead saved printer is around. Out of scope; would couple with a
  broader Printers panel rethink.

- **Bridge venv on the Pi has no `pytest`** — when running the bridge test suite live on the
  Pi during the LCD work, the deployed venv didn't have pytest installed (it's a runtime venv,
  not dev). Tests pass logically; not run end-to-end on hardware.

- **App-side test coverage** — there is no Swift test harness in this repo. UI changes are
  verified by build + run + manual test. Document any new behaviour with a steps-to-reproduce
  comment if it's non-obvious.

- **Editor v2 follow-ups out of plan 048** — HDR / wide-gamut preview (P3 + extended-range),
  RAW pipeline integration with Apple's neural-engine NR, per-slider numeric input boxes,
  Lightroom-import preset format, real-time camera-capture editing (Phase 4 of 041). See
  plan 048 §5 for the full out-of-scope list.

---

## 5. How to do common things

### Build + install the App
```bash
bash scripts/build-app.sh 0.1.46   # bump version per CLAUDE.md
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
- `docs/plans/048-photos-style-editor-implementation.md` (PR Status table is the source of
  truth for what landed in each PR of the editor rebuild).

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
- Plan archive (audits + implementations): `docs/plans/001–048`. The Photos-style editor
  rebuild is documented end-to-end in 047 (audit) + 048 (implementation).
- FFI reference: `docs/reference/ffi.md` (canonical export list; 24 Rust exports, 20 wired by
  Swift).
- BLE protocol notes: `docs/reference/protocol.md` and `bridge/docs/printer-protocol-notes.md`.

---

## 8. Open the next session with

Paste the following as your first message in a new Claude Code session to bring the assistant
up to speed cold:

> I'm continuing work on InstantLink at `/Users/hongjunwu/Repositories/Git/InstantLink`. Read
> `docs/handover.md` first — it's the self-contained briefing. App + crates at 0.1.45. The
> Photos-style editor rebuild scoped in plans 047/048 is complete (all 17 PRs landed); the
> legacy `EditorViews.swift` is deleted and the `useNewEditor` flag is gone. Bridge HEAD on
> the test Pi is still `ad638be` (`riverps-rpi-zero-2w`, reachable at `192.168.7.1` over
> `en10`). Open threads listed in §4 of the handover. For LCD/Bridge work, the
> `bridge/docs/current-context.md` doc is the freshest picture of what's deployed.
