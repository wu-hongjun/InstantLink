# 047 — Photos-Style Editor Rebuild (Audit + Research)

Goal: replace the InstantLink App's image editor with a 1:1 macOS Photos Edit UI parity surface — a richer adjustment engine, a top tab bar (Adjust / Filters / Crop), and a real crop tool. This plan documents the audit and queues research; concrete diffs land in `048-photos-style-editor-implementation.md` once the open questions are decided.

This plan **supersedes** the Pass B direction of `044-image-editor-audit.md`. Pass A (visual quieting) becomes moot because the entire sidebar is being replaced. The overlay subsystem from 044 is preserved, but its placement is an open question (§ Open Questions).

---

## 1. What exists today

| Layer | File | What it does | Lines |
|---|---|---|---|
| App editor shell | `macos/InstantLink/Features/Editor/EditorViews.swift` | `ImageEditorView` HSplit canvas/sidebar; sections: Fit Mode, Exposure, Rotate, Overlays, Defaults | 1364 |
| App adjust engine | `macos/InstantLink/Core/ImageAdjustmentService.swift` | **One** static helper: `applyExposure(to:ev:)` over `CIExposureAdjust` | 32 |
| App print render | `macos/InstantLink/Core/PrintRenderService.swift` | Composes the printable bitmap (transform + exposure + overlays). | 771 |
| Drop pipeline | `macos/InstantLink/Support/ImageDropHandler.swift` | Shared drop handling, Photos.app data path. | (new) |
| Rust core | `crates/instantlink-core/src/image.rs` | **Print-prep only** (resize, model-specific dithering). No pixel adjustments. | — |

**Implication**: the entire adjustment engine the user is asking for is green-field on the Swift/Core Image side. Rust core does not enter this work.

---

## 2. Target UI — 1:1 with macOS Photos.app Edit

### 2.1 Top tab bar
```
[ Adjust ]   [ Filters ]   [ Crop ]
```
One mode at a time. Tab affects the right-side sidebar contents only; canvas stays put.

### 2.2 Adjust panel — sections, top to bottom

Each section is collapsible, has its own Auto / Reset / On-Off + chevron header (Photos pattern). Sliders within a section snap to neutral (0) and double-click resets a single slider. Option-drag extends the slider range to ~2× normal travel. All sliders are **−1.0 … +1.0** internally (UI may show −100…+100 integer).

| # | Section | Sliders / controls | Photos-truth notes (from research) |
|---|---|---|---|
| 1 | **Light** | Brilliance, Exposure, Highlights, Shadows, Brightness, Contrast, Black Point | All ±1.0; Auto sets non-zero values across the group. Histogram backdrop above the section. **Brilliance is a composite** (HighlightShadow + tone curve + midtone S) — persist as one scalar. |
| 2 | **Color** | Saturation, Vibrance, Cast | Cast is a 1-D bipolar ride through temperature+tint space; the fuller 2-D version lives in White Balance below. |
| 3 | **Black & White** | Intensity, Neutrals, Tone, Grain | **B&W is a mode flag**, not Saturation = −1. While on, the Color sliders are inert. **Neutrals is a mid-tone luminance shift, NOT a tint** (B&W has no hue-tint slider — sepia goes through Filters). **Grain is 0..+1 only** (asymmetric — negative is a no-op). |
| 4 | **Red Eye** | Auto button + Size slider + click-to-fix | Each manual click is its own undoable edit. Size slider sets the corrective circle diameter; cursor becomes a ring of that size. |
| 5 | **White Balance** | Mode pop-up: *Neutral Gray / Skin Tone / Temperature & Tint* + eyedropper + per-mode controls | Eyedropper available in all three modes (samples ~3×3 px). Temp & Tint mode shows two sliders. Each mode keeps its own parameter set; switching modes does not silently re-apply the previous mode. |
| 6 | **Curves** | Channel pop-up: **RGB / Red / Green / Blue** (NO Luminance — Luma lives in Levels). Smooth-spline editor. | Up to ~16 points (cap matches Photoshop); drag point off-curve to delete; endpoint handles draggable along edges (input black/white shift). **Smooth spline only — Photos has no polyline mode.** Three eyedroppers: Black-point / Midtone / White-point. |
| 7 | **Levels** | Channel pop-up: **Luminance / RGB / Red / Green / Blue** (HAS Luminance — extra channel vs Curves). 5 bottom handles + 2 top handles on histogram. | Bottom: Black point / Shadows / Midtones (gamma) / Highlights / White point. Top: output Black / output White. **Option-drag a bottom handle moves the matching top handle in unison.** Histogram backdrop refreshes ~100 ms throttle. Auto picks 0.5%/99.5% percentile cuts. |
| 8 | **Definition** | **One slider** + Auto button (no Radius). | Photos exposes a single slider. Internally it's a high-radius / low-amount unsharp mask, midtone-masked. The brief's "Radius + Intensity" is Lightroom Clarity, not Photos — see Open Q6. |
| 9 | **Selective Color** | **Six user-defined color wells** (NOT 8 fixed swatches), each with Hue / Saturation / Luminance / **Range** sliders. Click a well → either pick a preset color or eyedrop from the canvas. | The 8-swatch fixed-hue layout (Red/Orange/.../Magenta) is Lightroom HSL, not Photos. **Range** controls the hue bandwidth around the seed — Photos' tunable smoothness. See Open Q7 for product decision. |
| 10 | **Noise Reduction** | Master slider (always visible) + Luminance / Color / Detail disclosure (**RAW v6+ only**). | Off-by-default (0). RAW sub-sliders only appear once master moves. Detail is an edge-preservation / detail-restoration knob (high = protect fine structure from being blurred away). |
| 11 | **Sharpen** | Intensity, Edges, Falloff. Defaults observed at 0.00 / 0.22 / 0.69. | Intensity = amount; Edges = threshold mask (flat-area protection); Falloff = post-blend gamma. **Not** a Gaussian-radius control. Intensity = 0 at default means no sharpening applied out of the box. |
| 12 | **Vignette** | **Strength / Radius / Softness** (the brief's "Radius / Intensity / Falloff" labels are Sharpen's, not Vignette's). | **Strength is bipolar**: negative = black vignette, positive = white vignette / halo. Radius is normalized to image diagonal. Falloff curve is smoothstep (Hermite). Apply LAST in the pipeline, after crop. |

### 2.3 Filters panel
- **Preserve current InstantLink filter set.** No new filters in this plan.
- **Add a right-rail filter strip**: vertical thumbnails of each filter applied to a low-res copy of the current image. Click to apply; selected filter highlights. This is a new component.

### 2.4 Crop panel

Panel layout (top → bottom in the right sidebar): three sliders (**Straighten**, **Vertical**, **Horizontal**), then the **Aspect** pop-up with **Flip** + **Rotate 90°** icons inline, then **Auto** (conditional), with **Reset** + global Done/Revert in the toolbar.

- **Aspect pop-up presets** (confirmed Photos macOS list — no named print-size labels like "4×6"):
  - Original (constrains to source image's native aspect)
  - Freeform (default; handles independent)
  - Square (1:1)
  - 16:9, 10:8, 7:5, 4:3, 5:3, 3:2
  - **Custom…** (two-field W × H numeric entry; accepts decimals)
  - Adjacent **Vertical / Horizontal orientation toggle** flips any ratio (10:8 ↔ 8:10, 16:9 ↔ 9:16, etc.) — so 9:16 portrait is reached via the toggle, not a named chip.
  - **Print-aware presets** matched to the user's paired Instax model (Mini = 2:3, Square = 1:1, Wide = 3:2) — InstantLink addition; see Open Q6.
- **Straighten slider**: −45° → +45°, horizontal slider (Ventura+ replaced the old vertical wheel). Snaps to 0 with soft detent. Double-click thumb resets. **Direct drag-on-image** outside the crop rect also rotates (cursor changes to rotation glyph). No two-point spirit-level tool.
- **Vertical slider**: vertical keystone correction (top-tilts-toward / away). Photos exposes no numeric range — model internally as −1.0…+1.0 and map to a trapezoid offset. Double-click resets.
- **Horizontal slider**: horizontal keystone (left/right tilt). Same UI shape and range.
- **Flip**: **single button**, plain click = horizontal, **Option-click = vertical**. (Not two paired buttons.) Adjacent **Rotate 90°** button: click = CCW, Option-click = CW.
- **Auto button**: combines auto-straighten + auto-crop. **Conditional — only visible when Photos detects horizontal/vertical edges**; suppressed otherwise.
- **Crop frame**: 8 handles (4 corners + 4 edge midpoints). Aspect-locked drags maintain the ratio; Freeform drags edges independently. Outside-crop area is **dimmed, not hidden** (the warped image stays visible behind a dark overlay).
- **Grid overlay**: **3×3 rule-of-thirds only**. Transient — appears while dragging a handle, fades on release. **No** Golden Ratio / Diagonal / Triangle / persistent grid (Photos has only thirds).
- **Order of operations** (Photos): Rotate 90° → Flip → Straighten → Vertical → Horizontal → Crop. Collapse Straighten + perspective into a single `CIPerspectiveTransform` (one resample) when perspective is non-zero; otherwise compose Rotate + Flip + Straighten + Crop into one `CIAffineTransform`.

---

## 3. Architecture sketch

```
EditorViewState
├─ activeTab: .adjust | .filters | .crop
├─ adjustments: AdjustmentState          // §2.2 values, all neutral by default
├─ filter: AppliedFilter?                // §2.3 (existing model)
├─ crop: CropState                       // §2.4 frame + rotation + perspective + flip
└─ overlays: [Overlay]                   // existing model — placement TBD (Open Q1)

ImageAdjustmentService → AdjustmentPipeline
├─ Build CIImage chain from AdjustmentState (deferred — CI fuses ops)
├─ CIContext.workingColorSpace = extendedLinearSRGB; cacheIntermediates = true
└─ MTKView + CIRenderDestination for live preview; CIContext for export
```

**Recommended pipeline order** (consolidated from research). Each step is a CIFilter or composite; bracketed labels = color space at that step.

```
1.  Decode (CIImage with orientation applied)
2.  White Balance              [linear]   CITemperatureAndTint
3.  Exposure                   [linear]   CIExposureAdjust  ← MUST be linear (stop multiply)
4.  Highlights + Shadows       [linear]   CIHighlightShadowAdjust  ← share one filter
5.  Brilliance (composite)     [linear]   CIHighlightShadowAdjust + CIToneCurve
6.  Black Point                [perc.]    CIToneCurve (point0 shift)
7.  Brightness, Contrast       [sRGB]     CIColorControls
8.  Curves (master + per-ch)   [perc.]    CIToneCurve per channel
9.  Levels                     [sRGB]     CIColorMatrix + CIGammaAdjust
10. Saturation, Vibrance, Cast [linear]   CIColorControls + CIVibrance + CITemperatureAndTint
11. Selective Color            [HSL]      custom CIColorKernel (6 wells or 8 chips)
12. B&W stack (if on)          [sRGB]     desaturate → CIToneCurve (Intensity+Tone+Neutrals) → grain composite
13. Definition                 [luma]     CIUnsharpMask large radius + midtone-masked
14. Noise Reduction            [linear]   CINoiseReduction + chroma blur on Cb/Cr
15. Sharpen                    [sRGB]     CIUnsharpMask  ← AFTER NR (not before)
16. Red Eye                    [sRGB]     CIRedEyeCorrection (inputCenters array)
17. Geometry: rotate → flip → straighten → perspective → crop  (single CIAffineTransform; +CIPerspectiveTransform only when perspective ≠ 0)
18. Vignette                   [sRGB]     CIVignette / custom radial mask  ← AFTER crop
19. Encode to outputColorSpace
```

Corrections vs. typical "photo-editor textbook" order:
- **Sharpen runs AFTER NR** (denoising sharpened pixels is destructive).
- **Vignette runs AFTER crop** (cropped corners would otherwise be darkened unpredictably pre-crop).
- **Curves uses CIToneCurve's built-in perceptual gamma 2** — no manual gamma decode needed.

Implementation primitives:
- **Live preview**: `MTKView(framebufferOnly = false, isPaused = true, enableSetNeedsDisplay = true)` + `CIRenderDestination(mtlTexture: drawable.texture, commandBuffer:)`. Redraw only when state changes — keeps GPU idle between drags.
- **Preview downsample**: source → `CILanczosScaleTransform` to ~2048 px long side, cached as `previewCIImage`. Pipeline runs on the downsample; export re-runs against full-res source.
- **Undo / redo**: stack of full `AdjustmentState` snapshots (few hundred bytes each). Debounce 200 ms during a slider drag; commit on drag-end.
- **Filter rail thumbnails**: pre-rendered once per source change against a 256-px copy. Keyed `(sourceHash, filterID)`. Do not re-render per adjustment change.
- **Histogram backdrop** (for Levels): `CIAreaHistogram → CIHistogramDisplayFilter`, or CPU readback of a 128-px downsample rendered into a SwiftUI `Canvas`. Refresh on slider commit (not per-frame).
- **WB eyedropper**: sample 1×1 (or 3×3 average) from the **un-white-balanced** `previewCIImage` via `CIContext.render(_:toBitmap:rowBytes:bounds:format:)`. McCamy's polynomial → CCT estimate → feed `inputNeutral` to CITemperatureAndTint.

---

## 4. Out of scope (this plan)

- Rust pixel ops — adjustment pipeline is Swift/Core Image, not Rust.
- Replacing the overlay subsystem.
- New filters in the Filters panel.
- Camera capture (Phase 4 from `041-app-ux-optimization`).

---

## 5. Research deliverables (landed)

Five parallel research passes; each landed its findings under `.omc/research/`. The corrections above (§2.2, §2.4, §3) already fold these in. Re-read the files when reaching for ranges, defaults, citations, or implementation stubs.

| File | Topic | Key takeaways folded into this plan |
|---|---|---|
| `docs/research/047-photos-adjust-light-color-bw.md` | Light / Color / B&W semantics, ranges, Auto behavior | Sliders are −1.0…+1.0; Brilliance is a composite; B&W is a mode flag (not Sat=−1); Neutrals is mid-tone *luminance*, not tint; Grain is asymmetric 0..+1 |
| `docs/research/047-photos-adjust-redeye-wb-curves-levels.md` | Red Eye flow, White Balance modes, Curves point model, Levels triplet + histogram | Curves channels: RGB / R / G / B (no Luma); Levels channels: Luma / RGB / R / G / B (extra Luma); Levels has 5 bottom + 2 top handles; Option-drag pairs bottom+top; Photos uses CITemperatureAndTint for Neutral Gray; 3×3 eyedropper sample is industry-standard |
| `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` | Definition / Selective Color / NR / Sharpen / Vignette internals | **Definition is ONE slider in Photos** (Radius is Lightroom); **Selective Color has 6 user-defined wells** (Range slider); NR sub-sliders are RAW-v6+ only; Sharpen defaults 0.00 / 0.22 / 0.69; Vignette labels are **Strength / Radius / Softness**; Strength is bipolar (white vignette via positive) |
| `docs/research/047-photos-crop-straighten-perspective.md` | Crop frame, aspect ratios, straighten dial, perspective sliders, flip semantics | Aspect list: Original/Freeform/Square/16:9/10:8/7:5/4:3/5:3/3:2/Custom + V/H toggle; no named "4×6"/"5×7" labels; Flip is one button (Option = vertical); Auto-straighten is conditional on edge detection; 3×3 grid only, transient |
| `docs/research/047-implementation-coreimage-mapping.md` | Slider → CIFilter mapping table; pipeline order; MTKView pattern; undo model; eyedropper math | Working space = extendedLinearSRGB; Sharpen AFTER NR; Vignette AFTER crop; MTKView with isPaused + setNeedsDisplay-on-change; full `AdjustmentState` Swift struct sketch; undo stack with 200 ms debounce |

Every research file lists sources used and open uncertainties at the bottom — consult those when in doubt.

---

## 6. Open questions — DECIDED

User decisions taken 2026-06-12. Implementation in `048` proceeds with these as fixed.

1. **Overlays** → **4th top-tab "Annotate"**. Tab bar becomes `Adjust / Filters / Crop / Annotate`. Existing overlay subsystem (text / qr / timestamp / image / location) moves here unchanged. — *user choice*
2. **Filter rail** → **tab-gated** (visible only in Filters tab; Photos parity). — *default, user did not override*
3. **Persistence** → **per-image, survives app relaunch** (adjustments live on queue-item model; non-destructive Photos-style editing). — *default*
4. **Simulated film frame** → **hide during Adjust + Crop**; show in Filters tab and after Done. — *default*
5. **Defaults For New Photos** → **demote to Settings sub-screen**; remove from per-image editor flow. — *default*
6. **Selective Color** → **6 user-defined wells + Range slider** (Photos parity). Each well is seeded by eyedropper or color picker; sliders are Hue / Saturation / Luminance / Range. — *user choice*
7. **Definition** → **single slider + Auto** (Photos parity); internal radius fixed at ~2 % of the image's short edge. Disclosure for a Radius control is a v2 follow-up. — *user choice*
8. **Print-aware aspect ratios** → **add Mini (2:3) / Square (1:1) / Wide (3:2) presets** when a Printer profile is selected. — *default*
9. **B&W ↔ Filters interop** → **Filters tab can override Adjust B&W stack** while a B&W LUT filter is active; switching tabs is the user signal. — *default*

---

## 7. Next step

§6 decisions are locked. Write `048-photos-style-editor-implementation.md` with concrete diffs, per-pass scope, and a build order. Suggested sequence (each row is one shippable PR):

1. **Editor shell rebuild** — top tab bar (Adjust / Filters / Crop / Annotate), `AdjustmentState` model, undo/redo, MTKView preview, working color space wired.
2. **Crop tab** — aspect chips + V/H toggle + printer-aware presets, straighten slider, Vertical + Horizontal perspective sliders, single Flip button (Option = vertical), 8-handle frame, 3×3 grid overlay.
3. **Light section** — Exposure first (smallest blast radius), then Brightness / Contrast / Black Point, then Highlights / Shadows, finally the Brilliance composite.
4. **Color section** — Saturation, Vibrance, Cast.
5. **Curves + Levels** — share the CIToneCurve / CIColorCurves machinery; histogram backdrop.
6. **Vignette** — bipolar Strength (white/black), Radius + Softness, smoothstep falloff.
7. **Sharpen** — Intensity / Edges / Falloff, luminance-only via CISharpenLuminance + threshold mask.
8. **Noise Reduction** — master slider first, RAW Luminance / Color / Detail sub-sliders behind RAW-v6+ gate.
9. **Definition** — single slider + Auto, high-radius midtone-masked unsharp at internal radius ≈ 2 % of short edge.
10. **Selective Color** — 6 user-defined wells with eyedropper + color picker, custom CIColorKernel with H/S/L/Range per well.
11. **Red Eye** — Size slider + click-to-fix first; Vision-driven Auto second.
12. **White Balance** — Temperature & Tint sliders first; Neutral Gray / Skin Tone eyedroppers second.
13. **B&W mode** — flag-driven; Intensity / Neutrals (luminance) / Tone / Grain (0..+1 asymmetric).
14. **Annotate tab** — port overlays subsystem from existing `EditorViews.swift` into the 4th tab.
15. **Filter rail** — right-side vertical strip with cached thumbnails, tab-gated to Filters; can override Adjust B&W stack while active.
16. **Auto buttons** — wire `CIImage.autoAdjustmentFilters` into per-section + global Enhance.
17. **Polish** — Option-drag extended range, double-click reset, smoothing toggles, debounced histogram, A/B fidelity pass against Photos itself.
