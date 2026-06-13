# 048 — Photos-Style Editor Implementation

Concrete build plan for the editor rebuild scoped in `047-photos-style-editor-audit.md`. Each major section below is one **shippable PR** — small enough to land in a sitting, large enough to be a meaningful step forward. The PRs are ordered so each lands on green main and the editor stays usable throughout the rebuild.

Locked decisions (full text in `047 §6`):

| # | Question | Decision |
|---|---|---|
| 1 | Overlay placement | 4th tab **Annotate** |
| 2 | Filter rail | Tab-gated to Filters |
| 3 | Persistence | Per-image, survives app relaunch |
| 4 | Film frame in canvas | Hide during Adjust + Crop |
| 5 | Defaults For New Photos | Demote to Settings sub-screen |
| 6 | Selective Color | 6 user-defined wells + Range slider |
| 7 | Definition | Single slider + Auto |
| 8 | Print-aware aspects | Add Mini (4:3 landscape) / Square (1:1) / Wide (3:2) |
| 9 | B&W ↔ Filters interop | Filters tab can override Adjust B&W stack |

Pipeline order, color-space rules, and slider mappings are in `047 §3` and `docs/research/047-implementation-coreimage-mapping.md` §1. Re-read those when implementing — this file references them by anchor rather than restating ranges.

### PR Status

| PR | State | Commits |
|---|---|---|
| #1 Editor shell rebuild | ✅ landed | `7880148` (foundation) + `14507cc` (review fix-ups) |
| #2 Crop tab | ✅ landed | `3de6be4` (feat) + `8ebb512` (Mini ratio) + `cb72b61` (aspect lock + affine order + grid timer) |
| #3 Light section + AdjustmentSlider primitives | ✅ landed | `d9e2516` (single commit, audit verdict APPROVED-with-nits; M-level nits deferred to PR #17 fidelity pass) |
| #4 Color section | ✅ landed | `47a58ae` (Saturation, Vibrance, Cast + B&W override + L_key hoist to LocalizedKey.swift) |
| #6 Vignette section | ✅ landed | `d873484` (bipolar Strength + Radius + Softness via CIRadialGradient mask) |
| #7 Sharpen section | ✅ landed | `9626bc3` (Intensity/Edges/Falloff via CISharpenLuminance + edge mask) |
| #8 Noise Reduction section | ✅ landed | `7d7fbb6` (master + Luma/Color/Detail via CINoiseReduction + CIMedianFilter passes) |
| #9 Definition section | ✅ landed | `6a61c9e` (single slider + Auto, high-radius unsharp + midtone mask) |
| #5 Curves + Levels | in flight (Wave 2) | |
| #12 White Balance + Eyedropper | in flight (Wave 2) | |
| #13 Black & White mode | in flight (Wave 2) | |
| #10 Selective Color, #11 Red Eye, #14 Annotate+retire, #16 Auto, #17 Polish | pending | |
| #15 Filter rail | deferred | Needs filter model that doesn't yet exist in new editor — wait until after PR #14 ports the legacy filter set or earlier if scope clarifies |

---

## 0. New file layout

The existing editor (`macos/InstantLink/Features/Editor/EditorViews.swift`, 1364 lines) is retired piecewise. PR #1 introduces the new shell **alongside** the legacy view behind a settings flag; PRs #2–#14 add tabs and sections; PR #14 ports overlays and deletes `EditorViews.swift`.

```
macos/InstantLink/Features/Editor/
├─ EditorShell.swift                  // PR #1 — top tab bar + HSplitView + active-tab routing
├─ EditorViewState.swift              // PR #1 — observable state, history wiring
├─ EditorPreview.swift                // PR #1 — MTKView + CIRenderDestination + eyedropper hit-test
├─ State/
│  ├─ AdjustmentState.swift           // PR #1 — full model from 047 §3
│  ├─ CropState.swift                 // PR #2 — aspect / straighten / V/H / flip / frame
│  ├─ EditorTab.swift                 // PR #1 — enum + tab descriptor
│  └─ AdjustmentHistory.swift         // PR #1 — undo/redo with 200 ms debounce
├─ Pipeline/
│  ├─ AdjustmentPipeline.swift        // PR #1 — top-level compose(_:state:) → CIImage
│  ├─ ColorSpaces.swift               // PR #1 — linear sRGB ↔ sRGB matched-from helpers
│  └─ Sections/                       // one Swift file per section, each owns its sub-pipeline
│     ├─ LightPipeline.swift          // PR #3
│     ├─ ColorPipeline.swift          // PR #4
│     ├─ CurvesLevelsPipeline.swift   // PR #5
│     ├─ VignettePipeline.swift       // PR #6
│     ├─ SharpenPipeline.swift        // PR #7
│     ├─ NoiseReductionPipeline.swift // PR #8
│     ├─ DefinitionPipeline.swift     // PR #9
│     ├─ SelectiveColorKernel.swift   // PR #10 — custom CIColorKernel
│     ├─ RedEyePipeline.swift         // PR #11
│     ├─ WhiteBalancePipeline.swift   // PR #12
│     ├─ BlackAndWhitePipeline.swift  // PR #13
│     └─ CropPipeline.swift           // PR #2
├─ Tabs/
│  ├─ AdjustSidebar.swift             // PR #3 — host for all Adjust sections
│  ├─ FiltersSidebar.swift            // PR #15
│  ├─ CropSidebar.swift               // PR #2
│  └─ AnnotateSidebar.swift           // PR #14 — ported overlay UI
├─ Adjust/                            // SwiftUI Section views, one per slider group
│  ├─ AdjustmentSlider.swift          // PR #3 — Photos-style slider with double-click reset, option-drag
│  ├─ AdjustmentSectionHeader.swift   // PR #3 — chevron + Auto + Reset + on/off toggle
│  ├─ LightSection.swift              // PR #3
│  ├─ ColorSection.swift              // PR #4
│  ├─ CurvesSection.swift             // PR #5
│  ├─ LevelsSection.swift             // PR #5
│  ├─ VignetteSection.swift           // PR #6
│  ├─ SharpenSection.swift            // PR #7
│  ├─ NoiseReductionSection.swift     // PR #8
│  ├─ DefinitionSection.swift         // PR #9
│  ├─ SelectiveColorSection.swift     // PR #10
│  ├─ RedEyeSection.swift             // PR #11
│  ├─ WhiteBalanceSection.swift       // PR #12
│  └─ BlackAndWhiteSection.swift      // PR #13
├─ Crop/
│  ├─ CropFrameView.swift             // PR #2 — 8-handle drag + 3×3 grid + dim overlay
│  ├─ StraightenSlider.swift          // PR #2 — Photos-style horizontal slider with 0° detent
│  ├─ AspectRatioPicker.swift         // PR #2 — pop-up + V/H toggle + printer-aware presets
│  └─ FlipRotateControls.swift        // PR #2 — single Flip button + Rotate 90°
├─ Filters/
│  └─ FilterRail.swift                // PR #15 — vertical thumbnail strip with cached previews
├─ Histogram/
│  └─ HistogramView.swift             // PR #5 — CIAreaHistogram backdrop
└─ Eyedropper/
   └─ EyedropperOverlay.swift         // PR #12 — view-coord ↔ image-coord mapping
```

Three callsites change:

- `macos/InstantLink/Core/ViewModel.swift` — opens the editor; switch from `ImageEditorView` to `EditorShell` behind a feature flag in PR #1, unconditionally in PR #14.
- `macos/InstantLink/Core/PrintRenderService.swift` — the final-render path. Today this composes (transform + `applyExposure` + overlays). Gets a new code path that consumes `AdjustmentState` via `AdjustmentPipeline`. Old path retained until PR #14.
- `macos/InstantLink/Core/ImageAdjustmentService.swift` — the existing 32-line single-exposure shim. Deleted in PR #14; `AdjustmentPipeline` replaces it.

---

## 1. Shared types and signatures

These are the contracts every PR builds against. PR #1 introduces them; later PRs only add new sub-types under each section.

### 1.1 `EditorTab.swift`
```swift
enum EditorTab: String, CaseIterable, Codable {
    case adjust, filters, crop, annotate
    var localizedTitle: LocalizedStringKey { LocalizedStringKey(rawValue.capitalized) }
}
```

### 1.2 `EditorViewState.swift`
```swift
@MainActor
final class EditorViewState: ObservableObject {
    @Published var activeTab: EditorTab = .adjust
    @Published var adjustments: AdjustmentState = .neutral
    @Published var crop: CropState = .neutral
    @Published var filter: AppliedFilter? = nil
    @Published var overlays: [Overlay] = []                 // ported from existing model in PR #14
    @Published var sourceImage: CIImage? = nil
    @Published var previewImage: CIImage? = nil             // downsampled, ~2048 px long side
    @Published var renderedPreview: CIImage? = nil          // post-pipeline, fed to MTKView

    let history = AdjustmentHistory(limit: 64)
    let pipeline = AdjustmentPipeline()

    func loadSource(_ url: URL) { /* CIImage(contentsOf:), Lanczos to ~2048 px */ }
    func renderPreview() { /* pipeline.compose(previewImage!, state: snapshot()) → renderedPreview */ }
    func snapshot() -> EditorSnapshot { … }                 // used by history + persistence
    func apply(_ snap: EditorSnapshot) { … }                // undo/redo restore
}

struct EditorSnapshot: Equatable, Codable {
    var adjustments: AdjustmentState
    var crop: CropState
    var filter: AppliedFilter?
    var overlays: [Overlay]
}
```

### 1.3 `AdjustmentState.swift`
Full struct sketch lives in `docs/research/047-implementation-coreimage-mapping.md` §4. Copy verbatim into Swift; every slider is `Double` (−1…+1 unless noted), every section has a `sectionEnabled: Bool` flag, every nested struct is `Equatable + Codable`.

Key delta from the research sketch:
- `SelectiveColor` keeps 6 wells (decision Q6), each: `seed: CGColor?`, `range: Double`, `hue/saturation/luminance: Double`. Add a `static let maxWells = 6`.
- `Definition` collapses to a single field `amount: Double` (decision Q7). Drop the `radius` field.
- `Vignette` fields rename: `strength` (bipolar), `radius`, `softness`.

### 1.4 `AdjustmentPipeline.swift`
```swift
struct AdjustmentPipeline {
    func compose(_ source: CIImage, state: EditorSnapshot) -> CIImage {
        var img = source
        // 1. White balance (linear)
        img = WhiteBalancePipeline.apply(img, state.adjustments.whiteBalance)
        // 2. Light section (linear): exposure → highlights/shadows → brilliance → black point → brightness/contrast
        img = LightPipeline.apply(img, state.adjustments.light)
        // 3. Curves + Levels (perceptual)
        img = CurvesLevelsPipeline.apply(img, state.adjustments.curves, state.adjustments.levels)
        // 4. Color (linear)
        img = ColorPipeline.apply(img, state.adjustments.color)
        // 5. Selective color (custom kernel, HSL)
        img = SelectiveColorKernel.apply(img, state.adjustments.selective)
        // 6. B&W (sRGB) — only if state.adjustments.bw.on
        if state.adjustments.bw.on { img = BlackAndWhitePipeline.apply(img, state.adjustments.bw) }
        // 7. Definition (luma)
        img = DefinitionPipeline.apply(img, state.adjustments.definition)
        // 8. Noise reduction (linear)
        img = NoiseReductionPipeline.apply(img, state.adjustments.nr)
        // 9. Sharpen (sRGB) — after NR
        img = SharpenPipeline.apply(img, state.adjustments.sharpen)
        // 10. Red eye (sRGB)
        img = RedEyePipeline.apply(img, state.adjustments.redEye)
        // 11. Geometry: rotate + flip + straighten + perspective + crop
        img = CropPipeline.apply(img, state.crop)
        // 12. Vignette (sRGB) — after crop
        img = VignettePipeline.apply(img, state.adjustments.vignette)
        // 13. Filter LUT (sRGB) — if state.filter != nil. Can override B&W if filter is B&W-tagged.
        if let f = state.filter { img = f.apply(img) }
        return img
    }
}
```

Each `*Pipeline.apply` is a pure function returning a `CIImage`. Empty implementations in PR #1 — they get filled in by their respective PRs.

### 1.5 `EditorPreview.swift` (MTKView wrapper)
Full code stub in `docs/research/047-implementation-coreimage-mapping.md` §3. Key points:
- `framebufferOnly = false`, `isPaused = true`, `enableSetNeedsDisplay = true`.
- `CIContext(mtlCommandQueue:options: [.workingColorSpace: extendedLinearSRGB, .cacheIntermediates: true])`.
- Driven by `EditorViewState.renderedPreview` via `Combine` sink → `setNeedsDisplay`.
- Eyedropper sample path: when `EditorViewState.eyedropperActive == true`, intercept click, convert view-coord → image-coord, sample 3×3 px via `CIContext.render(toBitmap:)` from the **pre-WB** `previewImage` (not `renderedPreview`), call back to the active section.

### 1.6 Persistence

`EditorSnapshot` becomes a field on the queue-item model (`PrintQueueItem` or whatever holds a pending print). Add `editorState: EditorSnapshot?` to that struct, default `nil`. The queue's existing on-disk serialization (JSON / property list — verify in PR #1) gains the field automatically via `Codable`. No migration needed: missing field = `nil` = `EditorSnapshot.neutral`.

---

## 2. PR-by-PR breakdown

Each PR is **independently shippable**: green clippy/tests, no regressions, no dangling feature flags except the explicit `useNewEditor` flag which lives from PR #1 through PR #14.

For each PR below:
- **Goal**: one-line scope.
- **Files**: created (new) and modified (mod). Paths from `macos/InstantLink/`.
- **Surface**: key signatures and SwiftUI structure.
- **Acceptance**: how we know it's shippable.
- **Depends on**: prior PR numbers.

### PR #1 — Editor shell rebuild
**Goal**: New `EditorShell` view with top tab bar (Adjust / Filters / Crop / Annotate stub), `AdjustmentState` model, undo/redo, MTKView preview, behind a `useNewEditor` flag in Settings.

**Files (new)**:
- `Features/Editor/EditorShell.swift`
- `Features/Editor/EditorViewState.swift`
- `Features/Editor/EditorPreview.swift`
- `Features/Editor/State/EditorTab.swift`
- `Features/Editor/State/AdjustmentState.swift`
- `Features/Editor/State/CropState.swift` (stub; full impl in PR #2)
- `Features/Editor/State/AdjustmentHistory.swift`
- `Features/Editor/Pipeline/AdjustmentPipeline.swift` (stubs returning input image)
- `Features/Editor/Pipeline/ColorSpaces.swift`

**Files (modified)**:
- `Core/ViewModel.swift` — route to new shell when `useNewEditor` flag on.
- `Core/Settings*` — add `useNewEditor: Bool = false` developer flag.
- Localization keys: `editor_tab_adjust`, `editor_tab_filters`, `editor_tab_crop`, `editor_tab_annotate`, `editor_done`, `editor_revert`.

**Surface**:
```swift
struct EditorShell: View {
    @StateObject var state: EditorViewState
    var body: some View {
        VStack(spacing: 0) {
            EditorTabBar(active: $state.activeTab)            // top tab bar
            HSplitView {
                EditorPreviewContainer(state: state)
                    .frame(minWidth: 620)
                Group {
                    switch state.activeTab {
                    case .adjust:   AdjustSidebar(state: state)
                    case .filters:  FiltersSidebar(state: state)
                    case .crop:     CropSidebar(state: state)
                    case .annotate: AnnotateSidebar(state: state)
                    }
                }
                .frame(minWidth: 320, idealWidth: 400, maxWidth: 460)
            }
        }
        .toolbar { /* Done, Revert, Undo/Redo */ }
    }
}
```

All four sidebar views are stubs returning `Text("…coming in PR #N")` until their PRs land.

**Acceptance**:
- With `useNewEditor` on, opening an image lands in the new shell with the canvas rendering through MTKView at parity with today's view.
- Tab bar switches between four empty panes; canvas state preserved across switches.
- Undo/redo wired (no operations to undo yet, but stack increments on filter-tab placeholder).
- All existing print-from-editor flows still work via the legacy `ImageEditorView` when the flag is off.

**Depends on**: nothing.

---

### PR #2 — Crop tab
**Goal**: Full Crop pane with aspect-ratio chips (Photos list + printer-aware presets), V/H orientation toggle, straighten slider with 0° detent, vertical + horizontal perspective sliders, single Flip button (Option-click = vertical), Rotate 90°, 8-handle crop frame with 3×3 grid + dim overlay. `CropPipeline` outputs the transformed CIImage.

**Files (new)**:
- `Features/Editor/Tabs/CropSidebar.swift`
- `Features/Editor/Crop/CropFrameView.swift`
- `Features/Editor/Crop/StraightenSlider.swift`
- `Features/Editor/Crop/AspectRatioPicker.swift`
- `Features/Editor/Crop/FlipRotateControls.swift`
- `Features/Editor/Pipeline/Sections/CropPipeline.swift`

**Files (modified)**:
- `State/CropState.swift` — full impl.
- `Pipeline/AdjustmentPipeline.swift` — wire `CropPipeline.apply`.

**Surface**:
```swift
struct CropState: Equatable, Codable {
    enum Aspect: String, CaseIterable, Codable {
        case original, freeform, square
        case ratio16x9, ratio10x8, ratio7x5, ratio4x3, ratio5x3, ratio3x2
        case custom(width: Double, height: Double)
        case printerMini, printerSquare, printerWide  // printer-aware
    }
    enum Orientation: String, Codable { case landscape, portrait }
    var aspect: Aspect = .freeform
    var orientation: Orientation = .landscape
    var straightenDegrees: Double = 0     // −45…+45
    var verticalSkew: Double = 0          // −1…+1
    var horizontalSkew: Double = 0        // −1…+1
    var flipHorizontal: Bool = false
    var flipVertical: Bool = false
    var rotate90Quarter: Int = 0          // 0–3, lossless
    var frame: CGRect = .init(x: 0, y: 0, width: 1, height: 1)   // normalized in post-transform coords
    static let neutral = CropState()
}

enum CropPipeline {
    static func apply(_ image: CIImage, _ state: CropState) -> CIImage {
        // 1. Compose CGAffineTransform: rotate90 + flip + straighten around center
        // 2. If skew ≠ 0: CIPerspectiveTransform with 4 corner CIVectors computed from skew angles
        // 3. cropped(to: denormalize(state.frame, against: post-transform extent))
    }
}
```

`CropFrameView` overlays the MTKView canvas; on drag updates `state.crop.frame` clamped to the inscribed rectangle (formula in `docs/research/047-photos-crop-straighten-perspective.md` §"Math + Core Image mapping"). 3×3 grid renders only during drag (timer fades on release).

`AspectRatioPicker` is the Photos pop-up: Original / Freeform / Square / 16:9 / 10:8 / 7:5 / 4:3 / 5:3 / 3:2 / Custom… plus a separator and printer-aware rows shown only when `ViewModel.activePrinter != nil` (Mini = 4:3 landscape, Square = 1:1, Wide = 3:2 — hardware per CLAUDE.md: Mini 600×800, Square 800×800, Wide 1260×840). Adjacent V/H orientation toggle swaps any ratio.

**Acceptance**:
- Aspect chips constrain the frame; V/H toggle flips ratios.
- Straighten slider rotates the canvas in real time; 0° detent snaps. Double-click resets.
- V/H perspective sliders apply CIPerspectiveTransform; canvas shows warped image with dimmed crop overlay.
- Flip button — plain click flips H, Option-click flips V. Rotate 90° works lossless.
- Outside-crop area dims (not hidden). 3×3 grid appears during drag.
- Printer-aware presets appear only when a printer is paired.

**Depends on**: PR #1.

---

### PR #3 — Light section + slider primitives
**Goal**: `AdjustmentSlider` and `AdjustmentSectionHeader` SwiftUI components (Photos-style: bipolar slider, double-click resets, Option-drag extends to 2×, section header with Auto / Reset / on-off). Light section with all 7 sliders (Brilliance is composite; rest are direct CI). `LightPipeline.apply` wired.

**Files (new)**:
- `Features/Editor/Adjust/AdjustmentSlider.swift`
- `Features/Editor/Adjust/AdjustmentSectionHeader.swift`
- `Features/Editor/Adjust/LightSection.swift`
- `Features/Editor/Tabs/AdjustSidebar.swift`
- `Features/Editor/Pipeline/Sections/LightPipeline.swift`

**Surface**:
```swift
struct AdjustmentSlider: View {
    @Binding var value: Double
    let range: ClosedRange<Double>            // typically -1...1
    let neutral: Double                       // typically 0
    let label: LocalizedStringKey
    var asymmetric: Bool = false              // true for B&W Grain (0..+1 only)
    var body: some View { /* HStack(label, slider, numericReadout); double-click → reset; option-drag → extend range */ }
}

enum LightPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Light) -> CIImage {
        var img = ColorSpaces.toLinear(image)
        // Exposure
        if s.exposure != 0 {
            img = img.applyingFilter("CIExposureAdjust", parameters: ["inputEV": 2.0 * s.exposure])
        }
        // Highlights + Shadows (share one filter)
        if s.highlights != 0 || s.shadows != 0 {
            img = img.applyingFilter("CIHighlightShadowAdjust", parameters: [
                "inputHighlightAmount": 1.0 - 0.5 * max(s.highlights, 0),     // see research §Light
                "inputShadowAmount":    s.shadows,
                "inputRadius":          0,
            ])
        }
        // Brilliance composite (highlight pull + shadow lift + midtone S)
        if s.brilliance != 0 { img = applyBrilliance(img, s.brilliance) }
        // Black Point via CIToneCurve point0 shift
        if s.blackPoint != 0 { img = applyBlackPoint(img, s.blackPoint) }
        img = ColorSpaces.toSRGB(img)
        // Brightness + Contrast via CIColorControls in sRGB
        if s.brightness != 0 || s.contrast != 0 {
            img = img.applyingFilter("CIColorControls", parameters: [
                "inputBrightness": 0.3 * s.brightness,
                "inputContrast":   1.0 + 0.6 * s.contrast,
                "inputSaturation": 1.0,            // Color section owns saturation
            ])
        }
        return img
    }
    private static func applyBrilliance(_ image: CIImage, _ b: Double) -> CIImage { … }
    private static func applyBlackPoint(_ image: CIImage, _ bp: Double) -> CIImage { … }
}
```

`LightSection` view: collapsible section with header + 7 sliders + histogram strip (placeholder until PR #5 fills it in).

**Acceptance**:
- Each of the 7 sliders changes the canvas in real time.
- Double-click resets one slider; section Reset resets all 7.
- Option-drag extends range to ±2.0 internally.
- Auto button calls `CIImage.autoAdjustmentFilters` and folds the returned CIToneCurve + CIHighlightShadowAdjust values into Light section state.
- Pipeline runs in linear sRGB for the Light section per §3.

**Depends on**: PR #1.

---

### PR #4 — Color section
**Goal**: Saturation, Vibrance, Cast sliders. `ColorPipeline.apply` wired.

**Files (new)**:
- `Features/Editor/Adjust/ColorSection.swift`
- `Features/Editor/Pipeline/Sections/ColorPipeline.swift`

**Surface**:
```swift
enum ColorPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Color) -> CIImage {
        var img = image
        if s.saturation != 0 {
            img = img.applyingFilter("CIColorControls", parameters: [
                "inputSaturation": 1.0 + s.saturation,
                "inputBrightness": 0.0, "inputContrast": 1.0,
            ])
        }
        if s.vibrance != 0 {
            img = img.applyingFilter("CIVibrance", parameters: ["inputAmount": s.vibrance])
        }
        if s.cast != 0 {
            img = img.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral":       CIVector(x: 6500, y: 0),
                "inputTargetNeutral": CIVector(x: 6500 + 3000 * s.cast, y: 50 * s.cast),
            ])
        }
        return img
    }
}
```

**Acceptance**: 3 sliders + Auto button. Auto uses CIVibrance from autoAdjustmentFilters.

**Depends on**: PR #1, PR #3 (for `AdjustmentSlider` primitive).

---

### PR #5 — Curves + Levels (share CIToneCurve / CIColorCurves) + Histogram
**Goal**: Curves panel (channel pop-up RGB / R / G / B, 5-point smooth spline editor, up to 16 points), Levels panel (channel pop-up Luminance / RGB / R / G / B, 5 bottom handles + 2 top handles, Option-drag pairing). Histogram backdrop shared by Curves + Levels + Light section (PR #3 placeholder).

**Files (new)**:
- `Features/Editor/Adjust/CurvesSection.swift`
- `Features/Editor/Adjust/LevelsSection.swift`
- `Features/Editor/Histogram/HistogramView.swift`
- `Features/Editor/Pipeline/Sections/CurvesLevelsPipeline.swift`

**Surface**:
- Curves editor renders a SwiftUI `Canvas` with monotone cubic Hermite spline through the points; drag adds/moves points; drag off-curve deletes (endpoint handles cannot be deleted, only repositioned along their edges). Smooth-only.
- Levels editor renders the histogram with 7 handle indicators (5 bottom + 2 top) over a SwiftUI `Slider`-equivalent. Option-drag a bottom handle moves its top counterpart in unison.
- `HistogramView` calls `CIAreaHistogram → CIHistogramDisplayFilter` on `previewImage` (pre-pipeline) at 100 ms throttle.
- `CurvesLevelsPipeline.apply` bakes Curves into a `CIColorCurves` LUT and Levels into a `CIColorMatrix + CIGammaAdjust` chain per the mapping in `docs/research/047-implementation-coreimage-mapping.md` §1 rows 21–24.

**Acceptance**:
- Curves: drag point on diagonal, image updates. Channel pop-up switches per-channel. Up to 16 points. Drag off-curve to delete. Three eyedroppers (Black / Midtone / White point).
- Levels: 7 handles draggable. Option-drag pairs bottom + top. Histogram backdrop updates after slider commit. Auto-Levels picks 0.5 / 99.5 percentile cuts.
- Histogram shows on Light section too (R/G/B + luma overlay).

**Depends on**: PR #1, PR #3.

---

### PR #6 — Vignette section
**Goal**: Vignette section with Strength (bipolar — white when +, black when −), Radius, Softness sliders.

**Files (new)**:
- `Features/Editor/Adjust/VignetteSection.swift`
- `Features/Editor/Pipeline/Sections/VignettePipeline.swift`

**Surface**:
```swift
enum VignettePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Vignette) -> CIImage {
        guard s.strength != 0 else { return image }
        // Build a normalized radial mask via CIRadialGradient (or custom kernel) with smoothstep falloff
        let mask = radialMask(extent: image.extent, radius: s.radius, softness: s.softness)
        let target = s.strength < 0 ? CIImage.black : CIImage.white
        let amount = abs(s.strength)
        return image.applyingFilter("CIBlendWithMask", parameters: [
            "inputBackgroundImage": image,
            kCIInputImageKey:       target,
            "inputMaskImage":       mask.multiplying(scalar: amount),
        ])
    }
}
```

Custom kernel — CIVignette doesn't support a white vignette and clamps `inputIntensity` at 0. See `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §5.

**Acceptance**: Bipolar Strength flips black/white. Radius normalized to image diagonal. Softness controls the smoothstep band width. Runs LAST in the pipeline (after crop).

**Depends on**: PR #1, PR #2 (Vignette must come after crop).

---

### PR #7 — Sharpen section
**Goal**: Sharpen section with Intensity / Edges / Falloff sliders. Default 0.00 / 0.22 / 0.69. Luminance-only via `CISharpenLuminance` + threshold mask for the Edges control.

**Files (new)**:
- `Features/Editor/Adjust/SharpenSection.swift`
- `Features/Editor/Pipeline/Sections/SharpenPipeline.swift`

**Surface**:
```swift
enum SharpenPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Sharpen) -> CIImage {
        guard s.intensity > 0 else { return image }
        // 1. Extract Y; compute local variance via 3×3 box filter
        // 2. Build threshold mask m = smoothstep(edges*0.02, edges*0.05, V)
        // 3. CISharpenLuminance(inputSharpness: intensity, inputRadius: 1 + 3*falloff)
        // 4. Blend sharpened Y back via mask; recombine with Cb/Cr
    }
}
```

**Acceptance**: Three sliders work; defaults match Photos (0.00 / 0.22 / 0.69). Flat areas (skin, sky) protected by Edges threshold. Falloff softens midrange.

**Depends on**: PR #1.

---

### PR #8 — Noise Reduction section
**Goal**: NR section with master slider. RAW v6+ sub-sliders (Luminance / Color / Detail) behind a `nrAdvancedDisclosure` feature flag (always on for now; gated later when RAW detection lands).

**Files (new)**:
- `Features/Editor/Adjust/NoiseReductionSection.swift`
- `Features/Editor/Pipeline/Sections/NoiseReductionPipeline.swift`

**Surface**:
```swift
enum NoiseReductionPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.NoiseReduction) -> CIImage {
        guard s.luma > 0 || s.color > 0 else { return image }
        // 1. Convert RGB → YCbCr via CIColorMatrix
        // 2. Luma: CINoiseReduction(inputNoiseLevel: 0.02 + 0.06*luma, inputSharpness: 0.4 + 1.6*detail)
        // 3. Chroma: CIGaussianBlur on Cb/Cr with sigma = 4*color
        // 4. Recombine; restore detail mask via edge-detected luma blended with input
    }
}
```

**Acceptance**: Master slider denoises. Luma / Color / Detail sub-sliders independently controllable. Off-by-default at 0.

**Depends on**: PR #1.

---

### PR #9 — Definition section
**Goal**: Single Definition slider + Auto button. Internal radius fixed at ~2 % of short edge. Midtone-masked high-radius unsharp.

**Files (new)**:
- `Features/Editor/Adjust/DefinitionSection.swift`
- `Features/Editor/Pipeline/Sections/DefinitionPipeline.swift`

**Surface**:
```swift
enum DefinitionPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Definition) -> CIImage {
        guard s.amount > 0 else { return image }
        let radius = 0.02 * min(image.extent.width, image.extent.height)
        let boosted = image.applyingFilter("CIUnsharpMask", parameters: [
            "inputRadius":    radius,
            "inputIntensity": 0.15 * s.amount,
        ])
        let mask = midtoneMask(image)               // 1 − |2L − 1|
        return image.applyingFilter("CIBlendWithMask", parameters: [
            "inputBackgroundImage": image,
            kCIInputImageKey:       boosted,
            "inputMaskImage":       mask,
        ])
    }
}
```

**Acceptance**: Single slider 0..+1 visibly adds midtone local contrast without halos. Auto picks scene-dependent value in 0.1–0.4 range.

**Depends on**: PR #1.

---

### PR #10 — Selective Color (6 wells + Range)
**Goal**: 6 user-defined wells with eyedropper + color picker, H/S/L + Range slider per active well. Custom CIColorKernel for the per-band HSL shift.

**Files (new)**:
- `Features/Editor/Adjust/SelectiveColorSection.swift`
- `Features/Editor/Pipeline/Sections/SelectiveColorKernel.swift` — Metal-backed CIColorKernel
- `Features/Editor/Pipeline/Sections/SelectiveColorKernel.metal` — the kernel source

**Surface**:
```swift
// SelectiveColorSection.swift
struct SelectiveColorSection: View {
    @ObservedObject var state: EditorViewState
    @State private var activeWell: Int = 0      // 0..5
    var body: some View {
        VStack {
            HStack {                                                // 6 well swatches
                ForEach(0..<6) { idx in WellSwatch(index: idx, …) }
            }
            if let well = state.adjustments.selective.wells[activeWell].seed {
                AdjustmentSlider(value: bindingFor(.hue),        range: -1...1, label: "Hue")
                AdjustmentSlider(value: bindingFor(.saturation), range: -1...1, label: "Saturation")
                AdjustmentSlider(value: bindingFor(.luminance),  range: -1...1, label: "Luminance")
                AdjustmentSlider(value: bindingFor(.range),      range: 0...1,  label: "Range")
            } else {
                EyedropperButton { startEyedropper(forWell: activeWell) }
                ColorPickerButton { presentColorPicker(forWell: activeWell) }
            }
        }
    }
}
```

The kernel takes `wells: vec4[6]` (rgb seed + range) and `shifts: vec3[6]` (Δh / Δs / Δl). Per-pixel HSL conversion, raised-cosine weight per well, weighted sum of shifts, recombine. Source pattern in `docs/research/047-implementation-coreimage-mapping.md` §1 row 27 and `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §2 "Path A".

**Acceptance**:
- 6 wells, click an empty one to either eyedrop from canvas or pick a color.
- Active well shows H/S/L/Range sliders that affect only that band.
- Adjacent wells overlap by ~30° with raised-cosine weighting — no posterization at boundary hues.
- Clear-well button per swatch.

**Depends on**: PR #1, PR #3 (slider primitive), PR #12 (eyedropper overlay — can land in parallel if both PRs build the overlay against the same `EyedropperManager` shared in PR #1).

---

### PR #11 — Red Eye section
**Goal**: Size slider + click-to-fix manual mode first; Vision-driven Auto button second (in same PR — Vision integration is small).

**Files (new)**:
- `Features/Editor/Adjust/RedEyeSection.swift`
- `Features/Editor/Pipeline/Sections/RedEyePipeline.swift`

**Surface**:
```swift
enum RedEyePipeline {
    static func apply(_ image: CIImage, _ corrections: [AdjustmentState.RedEyeCorrection]) -> CIImage {
        guard !corrections.isEmpty else { return image }
        let centers = corrections.map { CIVector(x: $0.point.x, y: $0.point.y) }
        return image.applyingFilter("CIRedEyeCorrection", parameters: ["inputCenters": centers])
    }
}

struct AdjustmentState.RedEyeCorrection: Equatable, Codable {
    var point: CGPoint    // image-space
    var radius: Double
}
```

UI: Size slider 4–96 px (default 24). Auto button → `VNDetectFaceLandmarksRequest` for eye centers. Manual clicks add `RedEyeCorrection` records to `state.adjustments.redEye`.

**Acceptance**: Cursor over canvas becomes a ring of the chosen size. Each click corrects one eye. Auto detects + applies. Each correction is its own undo step.

**Depends on**: PR #1, PR #12 (canvas-click handler).

---

### PR #12 — White Balance section + Eyedropper infrastructure
**Goal**: WB section with mode picker (Neutral Gray / Skin Tone / Temperature & Tint), Temperature + Tint sliders (Temp & Tint mode), eyedropper for Neutral Gray + Skin Tone. Eyedropper infrastructure (`EyedropperOverlay`, image-coord sampling) is shared with PR #10 + PR #11.

**Files (new)**:
- `Features/Editor/Adjust/WhiteBalanceSection.swift`
- `Features/Editor/Eyedropper/EyedropperOverlay.swift`
- `Features/Editor/Pipeline/Sections/WhiteBalancePipeline.swift`

**Surface**:
```swift
@MainActor
final class EyedropperManager: ObservableObject {
    @Published var active: ActiveMode?
    enum ActiveMode { case wbNeutral, wbSkin, curvesBlack, curvesMid, curvesWhite, selectiveColor(wellIndex: Int) }
    func consume(_ pixelRGBA: SIMD4<Float>) { /* dispatch to active section */ }
}

enum WhiteBalancePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.WhiteBalance) -> CIImage {
        switch s.mode {
        case .temperatureTint:
            return image.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral":       CIVector(x: 6500 + 4000 * s.temperature, y: 150 * s.tint),
                "inputTargetNeutral": CIVector(x: 6500, y: 0),
            ])
        case .neutralGray:
            guard let p = s.eyedropPoint, let rgb = s.eyedropSample else { return image }
            let cct = McCamy.estimateCCT(from: rgb)
            return image.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral":       CIVector(x: cct.temp, y: cct.tint),
                "inputTargetNeutral": CIVector(x: 6500, y: 0),
            ])
        case .skinTone:
            // same as neutralGray but targetNeutral = canonical skin chromaticity
            ...
        }
    }
}
```

Eyedropper UX: when `EyedropperManager.active != nil`, `EditorPreview` shows a magnifier loupe under the cursor (Digital Color Meter style); first click samples 3×3 px from the **pre-WB** preview image via `CIContext.render(toBitmap:)` and calls `EyedropperManager.consume`.

**Acceptance**: Three WB modes. Eyedropper magnifies + samples. T&T sliders independently controllable. McCamy CCT estimate produces neutral gray on white reference.

**Depends on**: PR #1, PR #3.

---

### PR #13 — Black & White mode
**Goal**: B&W section with on/off toggle, Intensity / Neutrals (luminance shift, not tint) / Tone / Grain (0..+1 asymmetric). Color section grays out while B&W on.

**Files (new)**:
- `Features/Editor/Adjust/BlackAndWhiteSection.swift`
- `Features/Editor/Pipeline/Sections/BlackAndWhitePipeline.swift`

**Surface**:
```swift
enum BlackAndWhitePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.BlackAndWhite) -> CIImage {
        guard s.on else { return image }
        var img = image.applyingFilter("CIColorControls", parameters: ["inputSaturation": 0.0])
        img = applyTonalCurve(img, intensity: s.intensity, tone: s.tone, neutrals: s.neutrals)
        if s.grain > 0 { img = composeGrain(over: img, amount: s.grain) }
        return img
    }
}
```

UI: ColorSection sliders disabled with explanatory tooltip when B&W on.

**Acceptance**: Toggle on → image goes mono. Intensity, Neutrals, Tone, Grain work as documented. Neutrals slider only shifts mid-tone luminance (no hue shift). Grain disabled below 0.

**Depends on**: PR #1, PR #3, PR #4.

---

### PR #14 — Annotate tab + retire legacy editor
**Goal**: Port overlay subsystem (text / qr / timestamp / image / location) from `EditorViews.swift` into the Annotate sidebar. Delete `EditorViews.swift` and `ImageAdjustmentService.swift`. Remove `useNewEditor` flag — new editor is default and only.

**Files (new)**:
- `Features/Editor/Tabs/AnnotateSidebar.swift`
- `Features/Editor/Annotate/OverlayListView.swift`
- `Features/Editor/Annotate/OverlayInspectorView.swift`
- (Subsidiary kind-specific inspectors split from the existing 650-line `SelectedOverlayInspectorView` for maintainability)

**Files (modified)**:
- `Features/Editor/Pipeline/AdjustmentPipeline.swift` — Insert overlay composition after Vignette, before final encode. (Overlays are part of the final exported image, not the live-preview MTKView path? Or both? Decision: both — overlays render as CIImages composited on top of the adjusted-cropped-vignetted image; live preview shows them in canvas too. Re-use existing overlay-to-CIImage rendering from `PrintRenderService`.)
- `Core/PrintRenderService.swift` — final-render path consumes `EditorSnapshot` via `AdjustmentPipeline.compose`. Old `applyExposure` shim removed.
- `Core/ViewModel.swift` — `useNewEditor` flag removed; unconditionally use `EditorShell`.

**Files (deleted)**:
- `Features/Editor/EditorViews.swift` (1364 lines)
- `Core/ImageAdjustmentService.swift` (32 lines)

**Acceptance**:
- All overlay kinds work identically to today in the Annotate tab.
- Existing prints with overlay data continue to print correctly (no migration needed — `Overlay` model unchanged).
- `useNewEditor` flag removed from Settings.
- `EditorViews.swift` deleted; no references remain.

**Depends on**: PRs #2–#13 (so the editor is fully functional before retiring the old one).

---

### PR #15 — Filter rail
**Goal**: Filters tab gains a right-side vertical filter thumbnail strip with cached previews (256-px thumbnails, one per installed filter, computed once per source change). Selected filter highlights. When a B&W filter is selected, it overrides the Adjust B&W stack while active.

**Files (new)**:
- `Features/Editor/Tabs/FiltersSidebar.swift`
- `Features/Editor/Filters/FilterRail.swift`
- `Features/Editor/Filters/FilterThumbnailCache.swift`

**Surface**:
```swift
@MainActor
final class FilterThumbnailCache {
    private var cache: [String: NSImage] = [:]      // keyed by "\(sourceHash)/\(filterID)"
    func thumbnail(for filter: AppliedFilter, source: CIImage, sourceHash: String) async -> NSImage { … }
    func invalidate(sourceHash: String) { /* drop entries matching hash */ }
}
```

`FiltersSidebar` shows the existing filter set as a vertical strip of 88-pt-tall thumbnails. Selected filter has a highlight ring. Click applies; click again removes.

**Acceptance**:
- Thumbnails generated once per source change, cached.
- Selected filter applies to preview + export.
- B&W filter overrides Adjust B&W stack while active (decision Q9).

**Depends on**: PR #1.

---

### PR #16 — Auto buttons
**Goal**: Per-section Auto buttons (Light / Color / B&W / Levels / Curves / Definition / Red Eye) and a global Enhance (magic-wand) button. All wired to `CIImage.autoAdjustmentFilters` with section-appropriate filter family extraction.

**Files (new)**:
- `Features/Editor/Adjust/AutoEnhance.swift` — central helper.

**Files (modified)**:
- All `*Section.swift` files — wire Auto buttons in section headers to call `AutoEnhance.apply(section:state:)`.

**Surface**:
```swift
enum AutoEnhance {
    static func apply(section: AutoEnhanceSection, image: CIImage, state: inout AdjustmentState) {
        let filters = image.autoAdjustmentFilters(options: [.enhance: section.includeEnhance, .redEye: section == .redEye])
        // walk filters; extract parameters from CIToneCurve / CIVibrance / CIHighlightShadowAdjust / CIRedEyeCorrection;
        // fold into state.light / state.color / state.redEye / etc.
    }
    enum AutoEnhanceSection { case light, color, blackWhite, levels, curves, definition, redEye, global }
}
```

**Acceptance**: Each Auto button affects only its section. Global Enhance affects all relevant sections at once. Clicking Auto a second time toggles values back to neutral.

**Depends on**: PRs #3 / #4 / #5 / #9 / #11 / #13.

---

### PR #17 — Polish + fidelity pass
**Goal**: Final polish, fidelity comparison against Photos itself, accessibility, localization.

**Scope**:
- Option-drag extended range on all sliders.
- Double-click reset on all sliders.
- Curves smoothing toggle is removed (Photos has only smooth) — confirm no leftover UI.
- Histogram refresh debounced to 100 ms during drags, immediate on commit.
- Side-by-side A/B test against Photos: load 3–5 reference images in both editors; verify each slider at +0.5 / −0.5 produces matching look. Tune the empirical coefficients in `LightPipeline`, `ColorPipeline`, etc., to taste.
- All new strings added to `Localizable.strings` for 12 languages (use English fallback for languages with no translator).
- VoiceOver labels on every slider.
- Performance pass: confirm ≥ 30 fps on a 10-MP source on M-series; downsample to 1080 px if needed.
- Update `bridge/docs/current-context.md` — nothing changes on bridge, but record the App version bump.
- Bump `crates/instantlink-{core,ffi,cli}/Cargo.toml` to whatever App version this lands as.

**Acceptance**: Editor feels indistinguishable from Photos at typical slider positions. 12 languages localized. App-side test suite (such as it is) green. Ready to ship.

**Depends on**: all prior PRs.

---

## 3. Risks and contingencies

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **`CIRedEyeCorrection` is undocumented and may break** across macOS versions | Medium | Low | Fall back to custom CIKernel implementing the red-eye formula (see research §Red Eye). Manual click-to-fix can ship without `CIRedEyeCorrection` if needed. |
| **`CIHighlightShadowAdjust` halos at extreme settings** | Medium | Medium | Clamp slider ranges; consider replacing with a luma-only bilateral version in v2. |
| **MTKView dropped frames on 10-MP source** | Medium | Medium | Always downsample to 2048-px long side for preview; only re-render on slider commit (debounce dragging). PR #17 includes a perf pass. |
| **Custom `SelectiveColorKernel` color-space bugs** | High | Medium | Write a unit test that round-trips RGB → HSL → RGB at a few known colors; tune the kernel against side-by-side Photos comparison. |
| **Levels has more handles than Photoshop, less than Photos** | Low | Low | Ship with 5 bottom + 2 top per Photos research; revisit if user feedback diverges. |
| **Pipeline composition order interactions** | Medium | High | The compose function is deterministic — if a slider in section N changes a downstream section's apparent baseline, that's a feature, not a bug. Document any surprising interactions in the polish PR. |
| **Brilliance composite coefficients (0.5 / 0.3 / 0.15) wrong** | Medium | Low | Confirmed as empirical defaults in research. PR #17 fidelity pass tunes them. |
| **`useNewEditor` flag forgotten in shipped build** | Low | High | PR #14 explicitly removes the flag. CI check or grep gate before merge: `grep -rn useNewEditor` must return empty after PR #14. |
| **Queue-item model lacks `editorState`, breaks Codable** | Low | Low | Field default `= nil` with `Codable` synthesis; missing key = nil = neutral. PR #1 includes a unit test for the round-trip. |
| **Annotation overlays render twice (preview + final)** | Medium | Low | Single overlay-to-CIImage pass shared by `EditorPreview` (live) and `PrintRenderService` (export). PR #14 wires it once. |

---

## 4. Build order summary (TL;DR)

```
PR #1  Editor shell + AdjustmentState + history + MTKView preview      (foundation; behind useNewEditor flag)
PR #2  Crop tab                                                         (geometry pipeline; printer-aware presets)
PR #3  Light section + AdjustmentSlider primitives + AdjustSidebar
PR #4  Color section
PR #5  Curves + Levels + Histogram
PR #6  Vignette
PR #7  Sharpen
PR #8  Noise Reduction
PR #9  Definition
PR #10 Selective Color (6 wells + custom kernel)                        (depends on PR #12 eyedropper infra; can parallelize)
PR #11 Red Eye
PR #12 White Balance + Eyedropper infrastructure                        (shares EyedropperManager with PR #10 / #11)
PR #13 Black & White mode
PR #14 Annotate tab + retire legacy editor                              (removes useNewEditor flag; deletes EditorViews.swift)
PR #15 Filter rail
PR #16 Auto buttons
PR #17 Polish + Photos fidelity pass + localization + version bump
```

Each PR ends with `cargo fmt --all && cargo clippy --workspace -- -D warnings` (no-op for Swift-only PRs but cheap insurance). Each PR bumps the App build version per the project convention; crates only bump when PR #17 lands (no Rust changes in any earlier PR).

---

## 5. Out of scope (for v1 — track as follow-ups)

- HDR / wide-gamut preview path (P3 + extended-range). Ship sRGB preview first; WWDC22 EDR talk is the reference for v2.
- RAW pipeline integration with Apple's neural-engine NR. v1 uses `CINoiseReduction`; v2 explores ML.
- Per-slider numeric input boxes (Photos has slider-only). Add if user demand emerges.
- Lightroom-import preset format. The `AdjustmentState` Codable shape is a possible interop target but not pursued in v1.
- Real-time camera capture editing (Phase 4 of 041). Phase 3 = editor, Phase 4 = capture; not bundled.
- BridgeAdjustmentsPreviewView changes. The Bridge LCD's own adjustment screen is separate from the App editor and stays as-is.

---

## 6. Decisions surfaced during implementation that may need user input

Track these as you build; surface to the user when they come up rather than guessing.

- **Curves point cap** — research says ~16 (Photoshop convention). Photos does not document a cap. If the spline becomes wobbly past N, drop the cap, log a warning.
- **Levels handle visual style** — Photos shows 5 + 2 handles on the histogram strip. Compact or roomy? Defer to the SwiftUI implementation feel.
- **Eyedropper magnifier zoom factor** — Digital Color Meter uses 4×. Photos uses ~5×. Pick something between; ask if visual feedback feels wrong.
- **Filter rail thumbnail size** — 88 pt suggested above; Photos uses ~110 pt. Tune in PR #15 visual review.
- **Photos' "Auto" exact behavior** — `autoAdjustmentFilters` returns a fixed list; per-section Auto needs us to assign the right filter family to each section. Use the research's mapping (Vibrance → Color, ToneCurve+HighlightShadow → Light, RedEye → Red Eye); revisit if section-Auto produces non-intuitive results.

---

## 7. References

- `docs/plans/047-photos-style-editor-audit.md` — the audit + decisions this plan executes on.
- `docs/research/047-photos-adjust-light-color-bw.md` — Light / Color / B&W ranges + Auto behavior.
- `docs/research/047-photos-adjust-redeye-wb-curves-levels.md` — Red Eye, WB, Curves, Levels.
- `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` — Definition, Selective Color, NR, Sharpen, Vignette.
- `docs/research/047-photos-crop-straighten-perspective.md` — Crop, straighten, perspective, flip.
- `docs/research/047-implementation-coreimage-mapping.md` — full slider → CIFilter mapping table, MTKView pattern, undo model, eyedropper math.

When a PR's implementation hits a question the spec doesn't answer, consult the research files first (they cite Apple docs and third-party tutorials); update this plan with the answer; keep going.
