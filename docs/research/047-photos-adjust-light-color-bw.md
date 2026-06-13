# Photos Adjust — Light / Color / Black & White

Reference for SwiftUI/Core Image reimplementation of the macOS Photos "Edit -> Adjust" panel.
Apple does not publish the exact mathematical formulas or numerical defaults for any slider in the
Photos Adjust panel; their User Guide only gives prose. Where Apple's docs are silent, this doc
states our inference and the closest Core Image filter that reproduces the behavior.

Sources used:
- Apple Support — Adjust light, exposure, and color in a photo or video on Mac:
  https://support.apple.com/guide/photos/adjust-light-exposure-and-color-pht806aea6a6/mac
- Apple Support — Adjust white balance in Photos on Mac:
  https://support.apple.com/guide/photos/adjust-white-balance-pht9b1d4a744/mac
- Apple Support — Adjust specific colors in a photo or video on Mac:
  https://support.apple.com/guide/photos/adjust-specific-colors-phtcafe645b6/mac
- Apple Support — Change and enhance a video in Photos on Mac:
  https://support.apple.com/guide/photos/change-a-video-phte8a1fcd79/mac
- Apple Developer — CIHighlightShadowAdjust:
  https://developer.apple.com/documentation/coreimage/cihighlightshadowadjust
- Apple Developer — CIToneCurve / auto-adjustment notes:
  https://developer.apple.com/documentation/coreimage/citonecurve
  https://developer.apple.com/library/ios/documentation/GraphicsImaging/Conceptual/CoreImaging/ci_autoadjustment/ci_autoadjustmentSAVE.html
- openradar mirror — CIExposureAdjust default change in 10.11:
  https://github.com/lionheart/openradar-mirror/issues/8811
- Pocket Shutterbug — Using the Brilliance Adjustment in Apple Photos:
  https://pocketshutterbug.com/articles/using-the-brilliance-adjustment-in-apple-photos-on-iphone-and-ipad/
- TapSmart — Photo Adjustments 101:
  https://www.tapsmart.com/tips-and-tricks/photo-adjustments-101/
- MakeUseOf — Detailed Guide to Adjust Tools for Photos on Mac:
  https://www.makeuseof.com/explaining-adjust-tools-in-photos-mac/
- Kirkville — Convert Color Photos to Black and White in Apple's Photos:
  https://kirkville.com/how-to-convert-color-photos-to-black-and-white-in-apples-photos-app/

## Global UI behavior (applies to every slider in every section)

- **Slider range (user-visible)**: every slider in Light, Color, and B&W is presented as a
  symmetric track centered at 0 with negative on the left, positive on the right. Apple's UI
  shows no numbers, but Photos' internal scale (and the value shown in the "Compare" tooltip)
  is **-1.0 to +1.0**, often spoken of by third parties as **-100 to +100** (same thing, x100).
  Use **−1.0…+1.0** as the canonical model; expose **−100…+100** integer to the UI.
- **Default / identity**: every slider is **0** at neutral. Auto sets non-zero values; double-click
  on the slider resets that single slider to 0.
- **Option-key extended range**: hold Option while hovering to extend the track to roughly
  **2x** the normal travel (so −2.0…+2.0 internally / −200…+200 UI). Use the same calculation,
  just allow values outside the clamp.
- **Auto (per-section)**: clicking "Auto" runs Apple's analyzer (the same engine that powers the
  Enhance magic-wand) and assigns non-zero values to multiple sliders in that section. It is
  per-section: clicking Auto under Light only affects Light sliders; under Color only Color; under
  B&W only B&W. The Auto magic-wand button at the top runs all sections at once. Clicking Auto
  again toggles it off (back to all-zero). Photos also exposes a checkbox by each Auto label so
  the user can manually disable that section's auto adjustments.
- **Histogram**: a luma + RGB histogram is shown above the Light group; it is informational only,
  not interactive.

## 1. Light

Photos' Light group is a stacked pipeline applied in this order (inferred from observed
interactions when moving multiple sliders): tone-curve shaping (Brilliance / Highlights /
Shadows / Black Point) -> linear scale (Exposure) -> point ops (Brightness, Contrast).

### Brilliance

- **Effect**: "Adjusts a photo or video to make it look richer and more vibrant, brightening
  dark areas, pulling in highlights, and adding contrast to reveal hidden detail." It is
  explicitly described as **color-neutral** (no saturation change), although the perceived image
  often looks more colorful because contrast goes up.
- **Range**: −1.0…+1.0 (UI −100…+100). Symmetric.
- **Default**: 0.
- **Composite**: **YES**. This is the one slider in Light that is *not* a single CI filter call.
  Empirically, at positive values it (a) lifts shadows, (b) recovers / pulls down highlights,
  (c) raises midtone contrast — similar to "Clarity" in Lightroom but tonal rather than local.
  At negative values it does the inverse (darkens shadows, mutes highlights, flattens contrast).
- **CI mapping**: chain `CIHighlightShadowAdjust` (shadowAmount and highlightAmount tied to the
  Brilliance value with opposite signs) followed by a midtone-S `CIToneCurve` whose curvature
  scales with |brilliance|. Apply in **linear light** (use `CIColorClamp`/working-space gamma
  removal) to preserve neutrality. Do *not* touch `CIColorControls.saturation`.
- **Notes**: Apple does not publish a formula; the safest implementation runs the three sub-ops
  with damped coefficients (e.g. shadow lift `~ 0.5 * b`, highlight pull `~ -0.3 * b`, S-curve
  contrast `~ 0.15 * b`). Treat Brilliance as a single user-visible value but persist it as that
  single scalar — do not expand it into the other sliders.

### Exposure

- **Effect**: "Adjusts the lightness or darkness of the entire image." Linear multiplier
  in scene-referred light — i.e. classic EV stops.
- **Range**: UI −1.0…+1.0 maps to roughly **−2 EV…+2 EV** (Photos' slider is gentler than
  Lightroom's −5…+5).
- **Default**: 0 (identity).
- **Composite**: No.
- **CI mapping**: `CIExposureAdjust` with `inputEV = userValue * 2.0`. Note: on macOS 10.10 the
  filter default was 0.5, changed to 0.0 in 10.11+ — always set it explicitly.
- **Notes**: Operate in linear light (Core Image already does for this filter). This is the only
  Light slider that multiplies in scene-linear space; all the others act perceptually.

### Highlights

- **Effect**: "Adjusts the highlight detail." Recovers detail in the upper end of the tone range.
  Positive values lift highlights (brighten them); negative values pull highlights down to recover
  blown-out detail. (Note: this is opposite to Lightroom's Highlights, which is "pull down to
  recover" at positive. In Photos the slider is signed-direction; +1 brightens.)
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **Composite**: No.
- **CI mapping**: `CIHighlightShadowAdjust` with `inputHighlightAmount = 1.0 + userValue` (the
  filter's identity is 1.0, and it accepts roughly 0.0…1.0; for negative travel apply a custom
  tone curve targeted at luma > ~0.7).
- **Notes**: `CIHighlightShadowAdjust` is the canonical filter; its `inputRadius` defaults to 0
  and you should leave it at 0 for global behavior (set radius > 0 only if you want local-tone
  behavior; Photos appears global). Keep this and Shadows in a single filter call when both are
  non-zero so they share the same internal tone map.

### Shadows

- **Effect**: "Adjusts the detail that appears in shadows." Positive values open up shadow
  detail (lifts dark tones); negative values deepen shadows.
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **Composite**: No.
- **CI mapping**: `CIHighlightShadowAdjust` `inputShadowAmount = userValue` (filter accepts
  roughly −1.0…+1.0; identity is 0.0). Set both Highlights and Shadows in the same filter
  invocation to keep them consistent.

### Brightness

- **Effect**: "Adjusts the brightness of the photo." Unlike Exposure, this is a perceptual
  midtone shift — it lifts the whole image but compresses (rather than scales) toward white,
  so highlights do not blow out as quickly as with Exposure.
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **Composite**: No.
- **CI mapping**: `CIColorControls.inputBrightness = userValue * 0.5` (filter identity is 0.0;
  the filter is additive on the per-pixel channel, so a ±0.5 swing already moves the image
  noticeably). For a closer match to Photos' midtone-weighted feel, prefer a small `CIToneCurve`
  whose midpoint lifts but whose endpoints are pinned at 0 and 1.
- **Notes**: Photos applies Brightness in display-referred space (after gamma), so values
  saturate gently rather than clipping. Mirror this by applying after Exposure.

### Contrast

- **Effect**: "Adjusts the contrast of the photo." Classical S-curve around mid-gray.
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **Composite**: No.
- **CI mapping**: `CIColorControls.inputContrast = 1.0 + userValue` (filter identity is 1.0;
  acceptable range roughly 0.25…4.0). For a softer/Photos-like rolloff, a custom `CIToneCurve`
  with shoulders is closer than the straight-multiply that `CIColorControls` performs.

### Black Point

- **Effect**: "Sets the point at which the darkest parts of the image become completely black
  without any detail. Setting the black point can improve the contrast in a washed-out image."
  Only one direction is useful in practice (positive crushes the toe); negative travel raises
  the floor to a lifted/film-look dark gray.
- **Range**: −1.0…+1.0. Symmetric, but only positive values are commonly used.
- **Default**: 0.
- **Composite**: No.
- **CI mapping**: `CIToneCurve` with the bottom anchor x moved from 0 toward
  `0.25 * max(0, userValue)`; or `CIColorMatrix` that maps `out = (in - bp) / (1 - bp)` clamped
  to [0,1] in linear-light. Negative travel raises the bottom anchor's y from 0 to
  `0.1 * |userValue|`.
- **Notes**: Apply after Exposure but before Brightness/Contrast for behavior consistent with
  Photos.

### Light "Auto"

Clicking Auto under Light asks Apple's analyzer to compute non-zero values for Exposure,
Highlights, Shadows, Contrast, and Black Point (Brilliance and Brightness are typically left at
0 by Auto). The values reflect the histogram (Auto tends to expand the dynamic range: positive
Black Point and Shadows lift, modest Highlights pull). It does **not** touch the Color or
B&W sections. Auto is a toggle — click again to zero them.

Re-implementation: under the hood, Photos uses `CIImage.autoAdjustmentFilters(options:)` from
Core Image, which returns an ordered array containing `CIRedEyeCorrection`, `CIFaceBalance`,
`CIVibrance`, `CIToneCurve`, and `CIHighlightShadowAdjust`. For per-section Auto in your re-impl,
drop the Vibrance result into Color and the Tone Curve + Highlight/Shadow into Light.

## 2. Color

### Saturation

- **Effect**: "Adjusts the overall color intensity." Uniform multiplier on chroma — every pixel's
  chroma is scaled by the same factor regardless of starting saturation.
- **Range**: −1.0…+1.0. Symmetric. −1.0 = full grayscale; +1.0 = roughly 2x original chroma.
- **Default**: 0.
- **Composite**: No.
- **CI mapping**: `CIColorControls.inputSaturation = 1.0 + userValue`. Filter identity is 1.0,
  range 0.0 (gray) and up. Apply in display-referred sRGB space — Apple's `CIColorControls` does
  exactly this and matches Photos directly.

### Vibrance

- **Effect**: "Adjusts the color contrast and separation between similar colors in the photo
  or video." Selective saturation: low-saturation pixels get boosted more than already-saturated
  ones. Skin tones are usually protected. Also slightly increases hue separation between adjacent
  hues (e.g. teal/green/yellow).
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **Composite**: No (single filter), but the filter itself is non-linear.
- **CI mapping**: `CIVibrance.inputAmount = userValue`. Filter identity is 0.0; positive boosts
  low-saturation pixels, negative desaturates them. CIVibrance has skin-tone protection built in.
- **Notes**: Use Vibrance, not Saturation, when re-implementing the Color Auto recovery, because
  CIVibrance is the filter Apple's own auto-adjust pipeline picks.

### Cast

- **Effect**: "Adjusts and corrects for color casts." Slides the image between a
  blue/yellow axis (color temperature) and implicitly also through magenta/green (tint), to
  remove a cast caused by incorrect white balance.
- **Range**: −1.0…+1.0. Symmetric. Negative pushes the image cooler (more blue);
  positive pushes it warmer (more yellow). Apple's single Cast slider is a 1-D ride along a
  curved path through temperature+tint space (the "White Balance" panel under Adjust is the
  fuller 2-D version with Temperature and Tint independently, plus Neutral Gray and Skin Tone
  eyedroppers).
- **Default**: 0.
- **Composite**: No (single filter), but it is effectively a parameterised
  `CITemperatureAndTint` call.
- **CI mapping**: `CITemperatureAndTint` with `inputNeutral = CIVector(x: 6500, y: 0)` (assumed
  source white-point) and
  `inputTargetNeutral = CIVector(x: 6500 + 3000 * userValue, y: 50 * userValue)`. The exact
  scale factors should be tuned by eye against Photos; ±3000K on temperature and ±50 on tint
  give a similar travel.
- **Notes**: Persist Cast as a single scalar (−1…+1) in your model; expand to the
  Temperature/Tint vector only at render time. If/when you add a White Balance panel,
  expose Temperature (≈ 2000K…10000K) and Tint (≈ −150…+150) as the 2-D version.

### Color "Auto"

Auto under Color sets non-zero Saturation, Vibrance, and Cast. In practice it leans on Vibrance
(Apple's analyzer returns a `CIVibrance` filter) and a temperature/tint correction derived from
the image's gray-point estimate. Skin-tone-aware. Toggle with a second click.

## 3. Black & White

### Conversion model (how Photos enters B&W)

The B&W section is **not** the same as the Filters tab's Mono / Silvertone / Noir presets.
Those Filters are LUT-based one-shots (`CIPhotoEffectMono`, `CIPhotoEffectTonal`,
`CIPhotoEffectNoir`). The B&W *Adjust* section is a parametric engine: when you enable B&W
(by touching any B&W slider, or by clicking the section's Auto), Photos:

1. Applies a weighted grayscale conversion (luma + per-channel mix biased toward a warm-neutral
   panchromatic mix). Inferred from observation; the closest CI primitive is `CIColorControls`
   with `inputSaturation = 0` followed by a tone-shaping pass.
2. Saturation is forced to 0 internally; the Color section's sliders are ignored as long as B&W
   is active.
3. The four B&W sliders below then operate on the grayscale image.

In your re-implementation, treat B&W as a mode flag, not as Saturation = -1. While the flag is
on, render: `desaturate -> CIToneCurve (Intensity + Tone) -> mid-tone bias (Neutrals) -> grain
overlay (Grain)`.

### Intensity

- **Effect**: "Increases or decreases the intensity of the tones of the image." A global tone
  multiplier on the grayscale image — positive deepens both darks and lights (more contrast +
  more black), negative compresses them (lifted, foggy look).
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **CI mapping**: combine `CIToneCurve` whose endpoints are pulled toward the corners on positive
  travel (steeper response), plus a small `CIExposureAdjust` of about `0.3 * userValue` to keep
  midtones balanced.
- **Notes**: Think of this as the headline B&W contrast slider.

### Neutrals

- **Effect**: "Lightens or darkens the gray areas of the image." This is a **mid-tone luminance
  shift**, not a tint and not a desaturation control. Positive values brighten the middle gray
  values (~ luma 0.4–0.6); negative values darken them. Highlights and shadows are largely
  preserved.
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **CI mapping**: `CIToneCurve` with anchor at (0.5, 0.5 + 0.3 * userValue), endpoints pinned
  at (0,0) and (1,1) and intermediate anchors at (0.25, 0.25) and (0.75, 0.75).
- **Notes**: Despite the name, this is **not** a tint/hue control. The B&W Adjust panel has no
  hue-tint slider — to get a sepia/cyanotype look the user has to use the Filters tab instead.

### Tone

- **Effect**: "Adjusts the image for a more high-contrast or low-contrast look." Acts on the
  *shape* of the curve — positive values steepen the toe and shoulder (deep blacks, bright
  whites, compressed midtones), negative values flatten the curve (filmic mid-key look).
- **Range**: −1.0…+1.0. Symmetric.
- **Default**: 0.
- **CI mapping**: `CIToneCurve` shaped as an S-curve whose slope scales with `userValue`. Distinct
  from Intensity (which scales the *whole* curve) and from Neutrals (which shifts only the mid
  anchor) — Tone is the curvature.
- **Notes**: In practice Intensity and Tone interact tightly; the implementer should treat them
  as two parameters of a single CIToneCurve call, not two stacked filters.

### Grain

- **Effect**: "Adjusts the amount of film grain that appears." Adds a luminance-only stochastic
  texture overlay to imitate film grain. Higher = more grain.
- **Range**: 0…+1.0 (the slider may be displayed as 0-centered, but only positive travel does
  anything; negative travel is a no-op).
- **Default**: 0 (no grain).
- **CI mapping**: there is no first-party grain filter in Core Image, so compose:
  `CIRandomGenerator` -> `CIColorMatrix` (extract luminance, scale alpha by `userValue`) ->
  `CIGaussianBlur` (radius ≈ 0.3–1.0 px, scales with `userValue` for grain coarseness) ->
  `CISourceOverCompositing` onto the image. Apple does not document the grain size; observation
  suggests grain size grows slightly with intensity, but the spread is mostly intensity-driven.
- **Notes**: Apply grain **last**, after all tone shaping. Pre-multiply the grain by a luminance
  mask that protects pure black and pure white if you want the closest match to Photos.

### B&W "Auto"

Auto under B&W enables the B&W mode, sets Intensity to a small positive value, Neutrals to
near 0, Tone to a small positive value chosen to compress the image's dynamic range into a
"clean" B&W histogram, and leaves Grain at 0. A second click disables B&W (returns to color).

## Pipeline order summary (recommended render graph)

1. Decode + tag to working color space (Display P3 or sRGB Linear — Core Image works in linear).
2. Apply Light group:
   a. `CIHighlightShadowAdjust` (Highlights + Shadows, plus Brilliance's shadow/highlight legs).
   b. `CIToneCurve` (Brilliance's curve leg + Black Point).
   c. `CIExposureAdjust` (Exposure).
   d. `CIColorControls` (Brightness + Contrast).
3. Apply Color group:
   a. `CITemperatureAndTint` (Cast / White Balance).
   b. `CIColorControls` (Saturation — leave at 1.0 if B&W mode is on).
   c. `CIVibrance`.
4. If B&W mode on: force saturation to 0, then apply Intensity + Neutrals + Tone via a single
   `CIToneCurve`, then composite Grain.
5. Gamma-encode to output space; clamp via `CIColorClamp` if persisting to 8-bit.

## Open uncertainties

- Exact internal scale (−1…+1 vs −100…+100): inferred from the Photos compare-tooltip; not in
  Apple's published docs. Implementing as −1.0…+1.0 floats is safe.
- The "Option-extends-range" multiplier (2x) is observed but not documented; could be 1.5–3x.
- Brilliance's exact mix of highlight/shadow/contrast coefficients: Apple does not publish
  these. The damped values above (0.5 / 0.3 / 0.15) are a starting point.
- Cast's mapping from a single −1…+1 slider to (temperature, tint): Apple uses a curved path
  through white-balance space; the linear approximation (±3000K, ±50 tint) is a stand-in.
- Whether B&W is a separate engine state or just `saturation = 0` under the hood: behavior in
  Photos strongly suggests a separate state (re-enabling B&W remembers the slider values; the
  color sliders grey out). Modeling it as a mode flag is correct.
- Grain texture generator: Apple's specific algorithm (size distribution, color/mono balance)
  is undocumented. `CIRandomGenerator` + small Gaussian blur is the standard re-implementation.
- Auto's exact analyzer: Apple ships `CIImage.autoAdjustmentFilters(options:)` which returns
  Red-Eye, Face, Vibrance, ToneCurve, and HighlightShadow filter instances. This is the
  recommended primitive to back per-section Auto and the magic-wand Enhance button.
