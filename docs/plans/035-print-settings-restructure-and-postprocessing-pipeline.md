# Plan 035 — Print settings restructure + postprocessing pipeline

## Context

Today the Print settings page is a flat 11-row list:

```
Serial · Pair/Re-pair · Reconnect · Forget · Printer type · Auto print ·
Image fit · JPEG quality · No-film test · Advanced separator ·
Keepalive · Search rate
```

After the plan 034 polish pass this list is functional but conceptually
mixed: pairing actions, printer model selection, behaviour toggles,
output transform parameters, and BLE polling knobs all sit at the same
level. Adding image-quality controls (saturation, exposure, sharpness,
hue, watermark, datestamp) to this flat list would push it past the
visible card and bury the destructive recovery actions in the middle of
a long scroll.

The user wants:

1. **A grouped Print settings hub** with sub-pages — Printer / Adjustments
   / Transform / Auto Print — so each surface holds the rows that
   actually go together.
2. **A real postprocessing pipeline** where image-quality adjustments
   (saturation, exposure, sharpness, hue, optional watermark + datestamp)
   are applied to the source image at full fidelity BEFORE the model-
   specific transform (crop/zoom/fit/JPEG encode). This way a RAW or HIF
   source benefits from the high-fidelity space; we only quantise into the
   model's print-size JPEG at the very end.
3. **Custom postprocessing presets** so a user who likes
   "+brightness +saturation +sharpness" can save the combination and
   apply it with one click rather than re-adjusting every print.

The current pipeline (`bridge/src/instantlink_bridge/imaging/pipeline.py:
_prepare_for_model`) does: decode → `Image.draft` (JPEG only) →
`exif_transpose` → `convert("RGB")` → `_apply_print_edit` (rotate / zoom /
offset only) → `_fit_image` → `_encode_jpeg_with_size_limit`. The
`PrintEdit` dataclass carries `rotate_degrees`, `zoom`, `offset_x`,
`offset_y` — no colour / brightness controls today.

## Scope of work

Phased delivery so each phase ships behind a clean test boundary and a
deployable bridge. Each phase ends with: all gates green, deployed to Pi,
`NRestarts=0`, no Traceback in journal.

### Phase 1 — Settings IA: Print becomes a hub

- New `SettingsPage` enum values: `PRINTER` (pairing + model),
  `ADJUSTMENTS`, `TRANSFORM`, `AUTO_PRINT`.
- `SETTINGS_BY_PAGE[SettingsPage.PRINT]` becomes a 4-row hub:
  ```
  Printer ›
  Adjustments ›
  Transform ›
  Auto print ›
  ```
- `SETTINGS_PARENT_PAGE` wires each new sub-page back to `PRINT`.
- New `SettingKey.OPEN_PRINTER`, `OPEN_ADJUSTMENTS`, `OPEN_TRANSFORM`,
  `OPEN_AUTO_PRINT` (mirroring `OPEN_NETWORK` / `OPEN_SYSTEM` / etc.).
- Move rows into the right sub-pages:
  - **Printer**: `Serial`, `Pair/Re-pair`, `Reconnect`, `Forget`,
    `Printer type`. Keep the unpaired/paired filtering already done
    in `_visible_keys_for_page`.
  - **Adjustments**: placeholder until phases 3-4 land. For now, a
    single info row `"Coming soon"` so the page exists but doesn't
    pretend to do anything.
  - **Transform**: `Image fit`, `JPEG quality`. (Crop / zoom UI lives
    in the live preview screen — those don't need settings rows.)
  - **Auto print**: `Auto print` (delay), `No-film test`, then the
    `Advanced` divider, then `Keepalive`, `Search rate`.

Tests / commits:
- Update navigation-step tests for the new hub structure.
- Preview-render the hub and each sub-page.
- Single commit: `refactor(bridge/ui): split Print settings into
  Printer/Adjustments/Transform/Auto print sub-pages`.

### Phase 2 — Postprocessing pipeline scaffolding

Build the *order* before building the *content*.

- New module `bridge/src/instantlink_bridge/imaging/postprocess.py`:
  ```
  apply_adjustments(image: Image.Image, profile: AdjustmentProfile) -> Image.Image
  ```
- `AdjustmentProfile` is a frozen dataclass of all controllable values
  (saturation, exposure, sharpness, hue, watermark, datestamp). All
  defaults are pass-through (saturation=1.0, exposure=0.0, etc.) — an
  empty/default profile is a no-op.
- Reorder `_prepare_for_model` so the call order is:
  1. decode (existing)
  2. `Image.draft` (JPEG only — existing)
  3. `exif_transpose` (existing)
  4. `convert("RGB")` (existing)
  5. **`apply_adjustments(image, profile)` — NEW, in full source resolution**
  6. `_apply_print_edit` (existing — rotate / zoom / offset; this is the
     interactive edit, not an adjustment)
  7. `_fit_image` (existing — model-aware crop/contain/stretch)
  8. `_encode_jpeg_with_size_limit` (existing)
- Tests: empty profile must produce byte-identical output to the
  pre-refactor `_prepare_for_model` for the existing fixture images.
- No new user-visible behaviour in this phase; the profile is hard-coded
  to defaults.

Single commit: `feat(bridge/imaging): introduce postprocess.apply_adjustments
ahead of model transform`.

### Phase 3 — Wire the four colour adjustments

- `AdjustmentProfile`:
  - `saturation: float = 1.0` — PIL `ImageEnhance.Color.enhance(factor)`.
    Range UI: -100…+100 → factor 0.0…2.0 (linear; 0 = greyscale, 1 =
    unchanged, 2 = double saturation).
  - `exposure: float = 0.0` — implemented via `ImageEnhance.Brightness`
    with `factor = 2 ** (exposure / 2.0)` to give EV-stop semantics.
    UI range -100…+100 → ±2 EV.
  - `sharpness: float = 1.0` — `ImageEnhance.Sharpness.enhance(factor)`.
    UI range -100…+100 → 0…2.
  - `hue: int = 0` — degrees of hue rotation (-180…+180). Implement via
    HSV channel rotation: `rgb_to_hsv → roll H → hsv_to_rgb`. Use the
    pre-allocated NumPy path for speed since rawpy is already a dep.
- New `SettingKey` values: `ADJUST_SATURATION`, `ADJUST_EXPOSURE`,
  `ADJUST_SHARPNESS`, `ADJUST_HUE`. Each is an adjustable picker with
  a 5- or 9-position range (e.g. `−100, −50, 0, +50, +100`).
- Adjustments sub-page rows:
  ```
  Saturation: 0  ›
  Exposure: 0    ›
  Sharpness: 0   ›
  Hue: 0         ›
  ```
- Config additions: `[adjustments]` section with all four fields plus a
  `preset: str = "default"` field (presets land in phase 5).
- Render the Adjustments sub-page with the new rows; gated on the
  `current preset == "custom"` so built-in presets don't surface
  individual knobs (only the preset name).

Tests:
- `apply_adjustments` parametric: identity profile → unchanged image
  (hash check), default profile → unchanged, each axis in isolation →
  expected pixel-level shift on a synthetic test image.
- Pipeline integration: end-to-end with a known JPEG, assert the
  applied profile changes the bytes from the identity output.
- Performance smoke: 12 MP source × full profile must complete under
  X seconds on the Pi (set the target after first measurement on
  device).

Commit: `feat(bridge/imaging): saturation/exposure/sharpness/hue
adjustments in the Print pipeline`.

### Phase 4 — Watermark + datestamp overlays

Both are end-of-adjustment overlays (still before the model transform —
they live in the high-fidelity space so the watermark gets resampled
cleanly by `_fit_image`).

- **Datestamp**: read EXIF `DateTimeOriginal` via `Image.getexif()`,
  format per the user's locale (English: `MMM d, yyyy`, Chinese:
  `yyyy年M月d日`), render in bottom-right with a 4 px stroke shadow for
  legibility on busy photos. Font: same DejaVu/CJK fallback ladder
  render.py uses.
- **Watermark**: text overlay, configurable string (default empty) +
  position (top-left / top-right / bottom-left / bottom-right /
  center).
- Settings rows in Adjustments sub-page:
  ```
  Datestamp: Off / On   ›
  Watermark: Off / On   ›
  ```
- Two new SettingKey enum values: `ADJUST_DATESTAMP`,
  `ADJUST_WATERMARK`. Both bool toggles for now; configurable text +
  position can land in a future plan.
- Help text: explain the order — "Stamp the date the photo was taken
  in the bottom-right corner" / "Stamp a short label on every print".

Commit: `feat(bridge/imaging): datestamp + watermark overlays in the
post-adjustment stage`.

### Phase 5 — Postprocessing presets

A preset is a named `AdjustmentProfile`. Built-in presets ship with the
bridge; custom presets are saved by the user from the current values.

- Module `bridge/src/instantlink_bridge/imaging/presets.py`:
  - Built-ins: `Default` (all identities), `Vivid` (sat +30, sharp +20,
    exposure 0, hue 0), `Soft` (sat -10, sharp -20), `B&W` (sat -100).
  - User custom presets stored as TOML maps in
    `/etc/InstantLinkBridge/presets.toml`. Cap at 4 user presets to
    keep the picker short.
- Settings flow:
  1. Open Adjustments sub-page.
  2. Top row: `Preset: Default ›` (picker of all built-ins + user
     presets + `"Custom"`).
  3. When `Custom` is selected, the four colour rows + datestamp /
     watermark become editable. Otherwise they're displayed read-only
     and reflect the active preset's values.
  4. New action row: `Save current as preset ›` — opens a tiny LCD
     keyboard for naming. Defer the keyboard UI to a later plan if it's
     too much surface; phase 5 can land with built-ins only and a
     `"Save"` button that auto-names presets `Custom1` / `Custom2` /
     `Custom3` / `Custom4`.
- Config: `[adjustments].preset = "Default"` is the active preset;
  loader resolves the name to an `AdjustmentProfile`.

Commit: `feat(bridge/imaging): postprocessing presets with built-in
Default/Vivid/Soft/B&W`.

### Phase 6 — Vignette + "Instax Film" preset

Real Instax film has darker corners — partly the small-format lens, partly
the chemistry. Today the bridge's prints look optically *flat* compared to
photos that came out of an actual Instax body. A radial corner-darkening
overlay simulates that look, and a new built-in preset bundles it with the
matching colour tweaks so users can opt in with one row.

- New `AdjustmentProfile` field:
  - `vignette: int = 0` — strength 0 (off) to 100 (heavy). Range is
    one-sided (no "bright corners" mode) because the simulation only
    makes sense as a darkening; "no vignette" is the identity.
- Settings row: new `ADJUST_VIGNETTE` SettingKey with a 5-position
  discrete picker `{0, 25, 50, 75, 100}` — not the symmetric ±100
  shape the four colour rows use, since negative vignette has no
  real-world equivalent.
- Implementation in `apply_adjustments`:
  - Runs AFTER sharpness, BEFORE the overlay stage (datestamp +
    watermark are drawn on top of the vignette so corner stamps stay
    legible).
  - NumPy radial falloff: build a normalised radius map per-pixel
    `r = sqrt((x/w - 0.5)^2 + (y/h - 0.5)^2)`, raise to a power that
    determines how aggressive the rolloff is (`gamma ≈ 2.0` looks
    closest to real Instax), then multiply RGB by `1 - r^gamma * (v/100)`.
    Clamped at the original colour space so we don't crush blacks below
    0.
  - Lazy NumPy import (same pattern as Phase 3's hue rotation).
  - Identity fast-path: `vignette == 0` skips the calculation entirely.
- New built-in preset `Instax Film`:
  - `saturation = -10` (slight desat for the vintage feel)
  - `sharpness = -10` (Instax prints aren't tack-sharp)
  - `vignette = 50` (the headline effect — visible but not heavy)
  - `hue = 0`, `exposure = 0`, `datestamp = False`, `watermark = False`
- Tests:
  - `test_vignette_darkens_corners_more_than_centre`: small solid-
    colour fixture, profile with `vignette=100`; assert corner pixels
    are darker than the centre pixel by a measurable delta.
  - `test_vignette_identity_at_zero`: byte-identical output for
    `vignette=0`.
  - `test_instax_film_preset_applies_vignette_and_desat`: preset
    selection from settings picks up vignette + saturation deltas.

Commit: `feat(bridge/imaging): radial vignette + Instax Film built-in
preset`.

Phase 6 sits AFTER Phase 5 because the preset system is the right
surface for "Instax Film" to live on. Phase 5 ships with five built-in
presets (Default / Vivid / Soft / B&W + the new Instax Film slot stubbed
out); Phase 6 fills it in once the vignette implementation lands.

## Cross-cutting constraints

- After each phase: `pytest -q --timeout=10 --timeout-method=thread`,
  `mypy src`, `ruff check src tests` must be clean.
- Deploy after each phase. Bridge must come back active with `NRestarts=0`.
- Conventional commits. Reference plan 035 + phase number in body.
- No `SKIP_HOOK=1` — memory file `skip-hook-not-needed` documents that
  both lint gates are currently clean.
- Apple iOS 26 voice + sentence-case rules for any new copy. zh-Hans
  entries added at the same time as their EN source.

## Open design questions to resolve early

1. **Where do the *interactive* edits (rotate / zoom / pan) live now?**
   The current `_apply_print_edit` runs on the source. Keep it as
   "interactive edit" between `apply_adjustments` and `_fit_image`, or
   move it into the Transform sub-page semantics? Probably keep as-is
   — interactive edits are per-photo, adjustments are persistent
   defaults. Resolve in phase 1.

2. **Pi Zero 2 W has 512 MB RAM and a slow SD card.** Applying 4 colour
   enhances + 2 overlays to a 24 MP source then resampling to
   Mini/Square/Wide is non-trivial. Benchmark phase 3 on a real Sony
   .ARW fixture before phase 4 ships; if we're > 2 s per print at full
   defaults, consider downsampling to print resolution first and
   accepting the fidelity hit. Phase 2's identity-profile fast-path
   makes this only a "user actually changed something" cost.

3. **JPEG re-encode cost.** Today the source is decoded once and
   re-encoded once. The adjustment pipeline keeps this — we don't
   round-trip to JPEG between adjustment and transform stages.

4. **Watermark text length cap.** ST7789 max-resolution font won't help
   here — the watermark is on the printed image not the LCD. Cap at
   ~24 chars and ellipsise; let the user know if they exceed.

## Out of scope

- Custom watermark images (file upload over FTP from the camera or via
  USB) — phase 5+.
- Custom datestamp formats — phase 5+.
- Multi-preset slideshow / time-based preset switching — never.
- Auto Adjustment ("auto white balance", "auto exposure") — not
  meaningful on a 2-MP Instax print; user-set defaults are clearer.
- ja / ko i18n expansion — separate plan.
