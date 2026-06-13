# 049 — Editor UI Photos parity + canvas preview fix

## Why

User smoke-tested v0.1.45 and reported two showstoppers:

1. **Canvas preview blank** — opening an image in the editor showed no image
   on the left canvas at all.
2. **Editor UI structurally wrong vs. macOS Photos.app** — the top bar, tab
   strip, sidebar, and section rows didn't match the real Photos.app Edit
   window. User attached a Photos screenshot for reference.

This plan is the focused polish round that ships the rebuild + the audit
fixes from `.omc/research/049-editor-polish-audit.md`.

## Canvas preview blank — root cause

`EditorViewState.init()` subscribed to `$previewImage` with `.dropFirst()`:

```swift
$previewImage
    .dropFirst()                              // bug
    .sink { [weak self] _ in self?.scheduleRender() }
    .store(in: &cancellables)
```

When `loadSource` ran, it set `previewImage = downsampledPreview(from: image)`.
That first emission was swallowed by `dropFirst()`. `loadSource` also called
`scheduleRender()` explicitly at its tail, BUT immediately afterwards the
`CombineLatest4($adjustments, $crop, $overlays, $filterID)` sink fired
because `loadSource` reassigned all four (`isRestoring = true; adjustments =
…`). That CombineLatest4 sink is debounced 16 ms and calls
`scheduleRender()` too — which cancels the in-flight Task started by the
explicit call.

In practice the first explicit render task was racing the CombineLatest4
debounced render and getting cancelled before it could write
`renderedPreview`. On v0.1.45 the race surfaced as a permanently blank
canvas.

**Fix:** remove `.dropFirst()` from the `$previewImage` sink so the natural
"preview source changed" signal flows through immediately. The contract
becomes: any change to `previewImage` schedules a render — no explicit
`scheduleRender()` call needed inside `loadSource`. We kept the explicit
call as a belt-and-braces safety net.

Defense-in-depth additions in `EditorPreview.swift`:

- The `EditorMetalView` clear color is now near-black opaque
  (`MTLClearColor(0.07, 0.07, 0.07, 1)`) instead of transparent. Even on a
  missed first draw the canvas reads as a dark Photos-style background.
- `layout()` triggers a redraw when the view receives its first non-zero
  size, so the initial `setNeedsDisplay(.zero)` call issued before SwiftUI
  laid the view out doesn't strand a blank texture.
- `image.didSet` re-issues `setNeedsDisplay` when transitioning from `nil`
  to a value.

## UI rebuild

### Top bar — `EditorShellTopBar.swift` (new file)

Three-third layout matching Photos:

- Left: zoom slider (`-` button, `Slider(-1…+1)`, `+` button). Slider drives
  `EditorViewState.zoomLevel`, a new published Double. `EditorMetalView`
  reads it and applies a `2^zoom` multiplier on top of aspect-fit.
- Centre: `EditorPillTabs` — pill-shaped segmented control for Adjust /
  Filters / Crop / Annotate, sized to content (NOT full-width).
- Right: icon row (info / more (`ellipsis.circle`) / favorite / rotate
  (CCW; cycles `crop.rotate90Quarter`) / wand (global Enhance)) followed by
  a yellow capsule **Done** button.

The undo / redo / revert controls that used to sit in the v0.1.45 toolbar
are folded into the More menu so the top row reads dense like Photos.

### Layout — `EditorShell.swift` (rewrite)

`HSplitView` is replaced by `HStack` with a fixed-width (320 pt) sidebar.
The canvas zone (`ZStack { Color(0.07); EditorPreview; CropFrameView?;
EyedropperOverlay? }`) takes `maxWidth/maxHeight = .infinity` so it fills
the remaining space. The explicit dark `Color(white: 0.07)` background is a
secondary defense against the blank-canvas bug — even if MTKView fails to
render, the canvas region still reads as a dark Photos-style backdrop.

### Section header — `AdjustmentSectionHeader.swift` (redesign)

Single horizontal row:

```
[chevron] [icon] [Section name] ………… [↶ reset (if non-neutral)] [AUTO pill] [○ enable]
```

`Auto` is rendered as a small capsule badge instead of a borderless text
button. `Reset` is a curved-arrow glyph. The on/off toggle uses an outlined
circle (off) vs. inset-filled accent circle (on). Header gets
`.accessibilityTraits(.isHeader)`.

Every section now passes a `systemImage` per the plan icon mapping (see
prompt §section icons).

### Sidebar — `AdjustSidebar.swift` (rewrite)

- Caps-locked `ADJUST` header row at top.
- Section order matches plan 047 §2.2 / Photos:
  Light → Color → Black & White → Red Eye → White Balance → Curves →
  Levels → Definition → Selective Color → Noise Reduction → Sharpen →
  Vignette.
- Footer `Reset Adjustments` button that invokes `state.revert()` (disabled
  when `state.snapshot() == .neutral`).

### Section template — Light / Color / Black & White

Three sections adopt the new Photos pattern:

```
[Header row]
[SectionThumbnailStrip — 5 tiles at dominant-slider intensities]
[DisclosureGroup "Options"
    [HistogramView / sliders / etc.]
]
```

`SectionThumbnailStrip` is a new component (`SectionThumbnailStrip.swift`)
that renders 5 tiles by running each through `state.pipeline.compose` with
the dominant slider set to one of `[-1, -0.5, 0, +0.5, +1]`. Tiles are
cached by `(sourceHash, sectionID, intensity)` and invalidated when the
preview source changes. The current selection gets an accent-color ring.

Dominant sliders:

- Light → `brilliance`
- Color → `saturation`
- Black & White → `intensity` (with `on = true` forced in the thumbnail
  snapshot so the strip actually previews the B&W mode)

### Other 9 sections — collapsed by default

Red Eye, White Balance, Curves, Levels, Definition, Selective Color,
Noise Reduction, Sharpen, Vignette all flipped to `@State private var
isExpanded: Bool = false`. Each also gets a `systemImage` in its header.

## Polish audit fixes bundled in

(References `.omc/research/049-editor-polish-audit.md`.)

- **H1**: Curves eyedropper buttons now call
  `state.eyedropperManager.start(.curves{Black,Mid,White})` with a sample
  callback that writes the sampled luminance into the matching curves
  master point (point0 / point2 / point4).
- **H2**: `BlackAndWhitePipeline.apply` guards on `s.sectionEnabled` before
  `s.on`, matching the contract every other section pipeline observes.
- **L1**: `FilterThumbnailCache.hash(for:)` now samples 4 corner pixels +
  the center and concatenates them into the cache key, so two
  same-dimension images don't collide.
- **L2**: `AdjustSidebar` section order matches plan / Photos (see above).
- **M2/M3**: Stale `// TODO: wire Apple analyzer in PR #16` comments in
  Sharpen / NR / Vignette are reworded as "preset-based Auto is the
  shipped behavior — `CIImage.autoAdjustmentFilters` does not surface a
  matching analyzer recommendation". The `// TODO: PR #17` comment in
  `RedEyePipeline.swift` is reworded.
- **M4**: `SelectiveColorSection.swift` and `WhiteBalanceSection.swift`
  gain brief comments explaining the intentional absence of Auto.

## Localization

Eight new keys (`editor_adjust_header`, `editor_zoom`,
`editor_reset_adjustments`, `editor_info`, `editor_favorite`,
`editor_rotate`, `editor_enhance`, `editor_more`) plus one more
(`adjust_options`) added across all 12 `.lproj/Localizable.strings`.
Real translations in en / zh-Hans / zh-Hant / ja / ko; English fallback in
de / es / fr / it / pt-BR / ar / he per the brief.

## Versioning

App + all 3 Rust crates bumped to **0.1.46**.

## What is NOT in scope

- Crop / Annotate tab content.
- Filters tab rail.
- Rust crates (only the version bump).
- Bridge files.
- Pipeline files except `BlackAndWhitePipeline.swift` (H2 fix) and
  `RedEyePipeline.swift` (M3 comment reword).
- `AdjustmentState` shape.

## Verification

Build with `bash scripts/build-app.sh 0.1.46` then reinstall per CLAUDE.md
workflow. Smoke test:

1. Open the editor with an image — canvas shows the image. **This is the
   acceptance test for the canvas-preview bug.**
2. Sidebar shows `ADJUST` header at top.
3. Light, Color, Black & White expanded by default, with thumbnail strips
   visible.
4. All other sections collapsed by default.
5. Click a thumbnail in Light → preview updates.
6. Click chevron on a collapsed section → it expands.
7. `Reset Adjustments` footer button enabled only when state is non-neutral.
