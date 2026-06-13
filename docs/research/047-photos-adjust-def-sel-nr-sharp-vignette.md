# Photos.app Adjust — Definition / Selective Color / Noise Reduction / Sharpen / Vignette

Research for a SwiftUI + Core Image reimplementation of these five Photos for Mac Adjust sections. Every concrete UI fact is cited from Apple Support or third-party tutorials that screenshot the panel; algorithm/Core Image facts are cited from Apple's filter docs and image-processing references.

## Sources used

- Apple Support — Adjust definition on Mac: https://support.apple.com/guide/photos/adjust-definition-phtb151c05a0/mac
- Apple Support — Adjust specific colors on Mac: https://support.apple.com/guide/photos/adjust-specific-colors-phtcafe645b6/mac
- Apple Support — Reduce noise on Mac: https://support.apple.com/guide/photos/reduce-noise-phta85f0d224/mac
- Apple Support — Sharpen a photo on Mac: https://support.apple.com/guide/photos/sharpen-a-photo-phtba5e3cf7d/mac
- Apple Support — Apply a vignette on Mac: https://support.apple.com/guide/photos/apply-a-vignette-phtafbdcae9d/mac
- MakeUseOf, "A Detailed Guide to All the Adjust Tools for Photos on Mac": https://www.makeuseof.com/explaining-adjust-tools-in-photos-mac/
- Kirkville, "How to Use Selective Color Editing in Apple Photos": https://kirkville.com/how-to-use-selective-color-editing-in-apple-photos/
- The Digital Story, "The Powerful Selective Color Tool in Photos for macOS": https://thedigitalstory.com/2018/01/using-selective-color-in-Photos-for-macOS.html
- MacMost, "Photos Selective Color Tool": https://macmost.com/photos-selective-color-tool.html
- MacMost, "Mac Photos Editing Shortcuts" (comments): https://macmost.com/mac-photos-editing-shortcuts.html
- Apple Developer — CINoiseReduction: https://developer.apple.com/documentation/coreimage/cinoisereduction
- Apple Developer — CIHighlightShadowAdjust: https://developer.apple.com/documentation/coreimage/cihighlightshadowadjust
- Apple Developer — CIVignetteEffect: https://developer.apple.com/documentation/coreimage/civignetteeffect
- cifilter.io — CIUnsharpMask: https://cifilter.io/CIUnsharpMask/
- emcconville/cif — CINoiseReduction: https://github.com/emcconville/cif/wiki/CINoiseReduction
- emcconville/cif — CIVignette: https://github.com/emcconville/cif/wiki/CIVignette
- emcconville/cif — CIVignetteEffect: https://github.com/emcconville/cif/wiki/CIVignetteEffect
- nst/iOS-Runtime-Headers — CISharpenLuminance.h: https://github.com/nst/iOS-Runtime-Headers/blob/master/Frameworks/CoreImage.framework/CISharpenLuminance.h
- Cambridge in Colour — Local Contrast Enhancement: https://www.cambridgeincolour.com/tutorials/local-contrast-enhancement.htm
- The Grey Blog — Clarity Adjustment (Local Contrast) in Photoshop: http://thegreyblog.blogspot.com/2011/11/clarity-adjustment-local-contrast-in.html
- Adobe Community — "What *exactly* is Clarity?": https://community.adobe.com/t5/photoshop-ecosystem/what-exactly-is-clarity/m-p/8957968
- Adobe — Make color/tonal adjustments in Camera Raw: https://helpx.adobe.com/camera-raw/using/make-color-tonal-adjustments-camera.html
- Digital Photography School — Lightroom HSL panel: https://digital-photography-school.com/understanding-the-hsl-panel-in-lightroom-for-beginners/
- Russell Cottrell — Very High Radius Unsharp Mask Plugin: https://www.russellcottrell.com/RCFilters/VHRUnsharpMask.php

---

## 1. Definition

### What the control does
Apple describes Definition as adding "contour and shape as well as midtone definition and local contrast" — i.e. it is Apple's "Clarity" analogue: a midtone-biased local-contrast operator, not a global contrast curve and not an edge sharpener (https://support.apple.com/guide/photos/adjust-definition-phtb151c05a0/mac, https://www.makeuseof.com/explaining-adjust-tools-in-photos-mac/). MakeUseOf summarizes the same: "adds contrast, allows midtones to pop, and adds more contour and shape."

Signal model: Definition is implemented in every shipping editor (Lightroom/ACR Clarity, Photoshop, darktable Local Contrast) as a **high-radius / low-amount unsharp mask**, often masked to midtones to avoid blowing out highlights/shadows (Cambridge in Colour, https://www.cambridgeincolour.com/tutorials/local-contrast-enhancement.htm; The Grey Blog, http://thegreyblog.blogspot.com/2011/11/clarity-adjustment-local-contrast-in.html; Adobe Community thread on Clarity, https://community.adobe.com/t5/photoshop-ecosystem/what-exactly-is-clarity/m-p/8957968). Typical numbers: blur radius 30–100 px, amount 5–20% — versus classic capture-sharpening which uses radius ≤ 2 px and amount 50–150% (Russell Cottrell, https://www.russellcottrell.com/RCFilters/VHRUnsharpMask.php).

### Photos UI
Photos exposes Definition as **a single primary slider plus an Auto button**, not as separate Radius and Intensity controls. Apple's page only mentions "the slider" (https://support.apple.com/guide/photos/adjust-definition-phtb151c05a0/mac); MakeUseOf and beart-presets both confirm a single slider with an Auto. The disclosure triangle reveals nothing extra for Definition — unlike Sharpen and Vignette, this section is monolithic.

> Implementation note for our app: the user's brief asks for "Radius + Intensity" — that is Lightroom Clarity, not Photos. We can either (a) match Photos and ship one slider, or (b) expose Radius + Intensity as a power-user disclosure. Recommend (b) with Radius hidden by default and a fixed perceptual default.

### Slider range and default
- Normalized range **0–1** with neutral default **0.0** (no effect at zero). Negative values are not exposed in Photos for Definition. Option-key on Photos sliders is documented as "extend the slider's range of values" (https://support.apple.com/guide/photos/sharpen-a-photo-phtba5e3cf7d/mac) but Definition only extends in the positive direction in observation.
- Auto computes a scene-dependent value, typically in the 0.1–0.4 region.

### Core Image mapping
There is no CIFilter literally named "Clarity." Build it as a high-radius unsharp mask, masked to midtones:

1. **Local-contrast core**: `CIUnsharpMask` with `inputRadius ≈ 0.02 × min(imageWidth, imageHeight)` (i.e. ~2% of the short edge → 40 px for a 2000 px image), `inputIntensity = 0.15 × userAmount` where `userAmount ∈ [0, 1]`. `CIUnsharpMask` defaults are `inputRadius = 2.5`, `inputIntensity = 0.5` per cifilter.io (https://cifilter.io/CIUnsharpMask/) — both must be overridden for a clarity-style result.
2. **Midtone mask**: derive a luminance mask `m(L) = 1 − |2L − 1|` (peaks at L = 0.5, zero at 0 and 1). Implement with `CIColorMatrix` to extract luma, then `CIToneCurve` or a custom `CIKernel` to apply the tent function. Blend the unsharp-masked output over the original via `CIBlendWithMask` using `m` as the mask.
3. **Edge guard (optional, matches Adobe Clarity behavior)**: clip post-blend in the highlights/shadows with `CIHighlightShadowAdjust` (`inputHighlightAmount = 1, inputShadowAmount = 0`) so the local-contrast boost doesn't crush blacks (https://developer.apple.com/documentation/coreimage/cihighlightshadowadjust).

`CIHighlightShadowAdjust` alone is **not** Clarity — it is a tone-redistribution filter with `inputRadius` for the local-tone estimation kernel; useful as the edge-guard step, not the core effect.

### Pipeline position
After exposure/contrast and before color grading. Definition is a tone operator on luminance; running it after Selective Color invites color shifts since CIUnsharpMask operates in RGB. If kept in RGB, convert to a luminance-only channel for the unsharp step (`CIColorMatrix` → grayscale → unsharp → recombine as Y-only delta into Y'CbCr).

---

## 2. Selective Color

### Critical correction to the brief
**Photos shows six color wells, not eight.** Apple is explicit: "select and change the hue, saturation, and luminance of up to six different colors" (https://support.apple.com/guide/photos/adjust-specific-colors-phtcafe645b6/mac). Kirkville, MacMost, and The Digital Story all confirm "six color buttons" / "six slots" (https://kirkville.com/how-to-use-selective-color-editing-in-apple-photos/, https://macmost.com/photos-selective-color-tool.html, https://thedigitalstory.com/2018/01/using-selective-color-in-Photos-for-macOS.html).

The 8-swatch HSL panel (Red/Orange/Yellow/Green/Aqua/Blue/Purple/Magenta) the brief describes is **Lightroom/ACR's Color Mixer / HSL panel**, not Photos. Lightroom's eight color sliders are confirmed by Adobe and DPS (https://helpx.adobe.com/camera-raw/using/make-color-tonal-adjustments-camera.html, https://digital-photography-school.com/understanding-the-hsl-panel-in-lightroom-for-beginners/).

> Decision needed from product: replicate Photos (6 wells, user-defined seeds + Range slider, eyedropper-driven) or replicate Lightroom (8 fixed-hue chips). The brief mixes both. The rest of this section covers both options.

### What the control does
A masked H/S/L shift in HSL (or HSV) space:
1. Identify a target hue region around a seed color.
2. Build a soft mask over pixels whose hue is within ±bandwidth of the seed (mask falls off smoothly at the band edges).
3. Apply hue shift, saturation gain, and luminance gain to those pixels only.

### Photos UI behavior
- **Six color wells** start empty; user clicks a well, then either picks a Photos preset color or clicks in the image with an eyedropper to seed it (https://kirkville.com/how-to-use-selective-color-editing-in-apple-photos/, https://macmost.com/photos-selective-color-tool.html).
- Sliders per selected well: **Hue, Saturation, Luminance, Range** (https://support.apple.com/guide/photos/adjust-specific-colors-phtcafe645b6/mac, https://www.makeuseof.com/explaining-adjust-tools-in-photos-mac/). The **Range** slider widens or narrows the hue bandwidth around the seed — Photos' answer to Lightroom's hidden "smoothness" parameter.
- All four sliders are symmetric ±, default 0. Hue range is a hue-degree offset; Saturation/Luminance are multiplicative deltas.

### Lightroom-style chip layout (if we adopt 8 fixed swatches)
Per Adobe and HSL-panel writeups, the eight chips are centered at canonical HSL wheel hues. Adobe does not publish exact band edges, but the de facto centers used by Lightroom/ACR and most HSL implementations are:

| Chip    | Hue center | Approximate band edges |
|---------|-----------:|------------------------|
| Red     |   0° / 360° | 345°–15° |
| Orange  |   30°       | 15°–45°  |
| Yellow  |   60°       | 45°–75°  |
| Green   |  120°       | 75°–165° |
| Aqua    |  180°       | 165°–210° |
| Blue    |  240°       | 210°–270° |
| Purple  |  285°       | 270°–315° |
| Magenta |  330°       | 315°–345° |

Sources for the eight-color list and approximate centers: https://digital-photography-school.com/understanding-the-hsl-panel-in-lightroom-for-beginners/ and https://helpx.adobe.com/camera-raw/using/make-color-tonal-adjustments-camera.html. The exact band edges above are conventional values used by open-source HSL clones (e.g., darktable's color zones), not Adobe-published — flag as approximate.

Adjacent swatches **overlap** by ~30° on each side and use a raised-cosine / Hann window weighting so a pixel at e.g. 45° contributes ~equally to Orange and Yellow. This avoids posterization at boundary hues.

### Core Image mapping
There is no first-party HSL/Selective-Color CIFilter that exposes per-hue H/S/L deltas. Two viable paths:

**Path A — Custom CIKernel (recommended)**
Write a Metal-backed `CIColorKernel` that:
1. Converts RGB → HSL per pixel.
2. For each of the N color chips, computes a hue-distance weight `w_i = max(0, cos(π × (h − h_i) / band_i))²` (raised-cosine), gated by saturation > epsilon so neutrals are excluded.
3. Sums weighted deltas: `Δh = Σ w_i × hue_i`, `Δs = Σ w_i × sat_i`, `Δl = Σ w_i × lum_i`.
4. Applies, converts back to RGB.

This is ~60 lines of CI Kernel Language and runs on the GPU.

**Path B — Stacked CIFilter graph**
For each chip:
1. `CIHueAdjust` for global hue rotation. Build a mask with `CIColorCubeWithColorSpace` whose table is 1.0 inside the target hue band and 0 elsewhere — `CIColorCube` is the standard CI way to do hue-selective masks.
2. `CIColorMatrix` for sat/luminance per channel.
3. `CIBlendWithMask` to composite back over original.

Path B is portable but slow (one cube + blend per chip). For 6–8 chips, prefer Path A.

`CIColorPolynomial` is **not** workable for HSL selectivity — it is a per-channel R/G/B polynomial; it cannot express "shift hue only where hue ≈ orange." Don't go down that path.

### Symmetry and ranges
- Hue: ±100 in Photos UI mapping to roughly ±30° in real hue shift, ±90° if option-extended.
- Saturation: ±100 maps to multiplier in `[0, 2]`.
- Luminance: ±100 maps to ΔL in `[−0.5, +0.5]`.
- Range: 0 (very tight, ~15° band) to 100 (wide, ~60° band). Default 50, ~30° band.
- All sliders are symmetric and default to 0 except Range.

---

## 3. Noise Reduction

### What the control does
Two distinct noise components:
- **Luminance noise** — grain-like brightness fluctuations.
- **Chroma (color) noise** — colored blotches, typically lower frequency than luma noise and more visually offensive.

Photographic NR algorithms separate the two by working in a luma/chroma color space (YCbCr or Lab), then apply different kernels: edge-preserving smoothing (bilateral, non-local means, wavelet shrinkage) on luma, heavier low-pass on chroma. A "Detail" slider re-introduces fine luma structure after smoothing, typically by un-blurring or by attenuating the NR strength on detected edges.

### Photos UI
- **Top-level slider**: Noise Reduction (single value).
- **Disclosure (RAW only, RAW version 6+)**: Luminance Noise, Color Noise, Detail (https://support.apple.com/guide/photos/reduce-noise-phta85f0d224/mac).
- Apple does not publish defaults. Observation: **off-by-default** (the slider is at zero on a freshly opened image), and the RAW sub-sliders only appear once you nudge the master.

### What "Detail" gates
Detail is best modeled as an **edge-preservation / detail-restoration knob**: at Detail = 0 the NR pass blurs through everything below the noise threshold; at Detail = 100 the NR pass is heavily masked by an edge-detector so high-frequency structure (eyelashes, hair, fabric weave) survives. Apple's docs are unhelpful here; this matches Lightroom's Detail slider, which is the closest cousin.

### Core Image mapping
- `CINoiseReduction` exists and is the obvious starting point. Per Apple Developer docs and cif/wiki, parameters are: `inputNoiseLevel` (default 0.02) and `inputSharpness` (default 0.4) (https://developer.apple.com/documentation/coreimage/cinoisereduction, https://github.com/emcconville/cif/wiki/CINoiseReduction). It applies a bilateral-style local blur where luminance variations below `inputNoiseLevel` are smoothed and variations above are sharpened by `inputSharpness`.
- **`CINoiseReduction` does NOT expose separate luma vs. chroma reduction.** It operates on a single threshold against luminance variation; chroma is denoised as a side effect of RGB smoothing but cannot be tuned independently.

To get Photos-style three-slider NR we need a hybrid:

1. **Color noise**: convert to YCbCr (via `CIColorMatrix`), apply `CIGaussianBlur` to Cb/Cr only with `inputRadius = colorAmount × 4` px, recombine. Chroma blur up to ~3–6 px is invisible because the eye has low chroma resolution.
2. **Luma noise**: feed Y into `CINoiseReduction` with `inputNoiseLevel = lumaAmount × 0.04`, `inputSharpness = 0.4 × (1 − lumaAmount × 0.5)` so heavy NR doesn't crank sharpness alongside.
3. **Detail**: compute an edge mask from Y via `CIEdges` or a Sobel kernel, threshold, dilate; use as a mask in `CIBlendWithMask(input: original_Y, background: denoised_Y, mask: edgeMask × detailAmount)`. At Detail = 1 the edges retain ~100% of original Y; at 0 the denoised Y wins everywhere.

For RAW-quality NR, `CINoiseReduction` is borderline acceptable. If the app needs to compete with Photos on RAW NR, plan a custom CI Metal kernel implementing **wavelet-shrinkage NR** (à trous discrete wavelet, soft-threshold high-frequency bands), or use BM3D-style non-local means via a Metal Performance Shaders compute pass outside Core Image. Wavelet shrinkage gives the cleanest luma/chroma/detail decomposition because each wavelet level *is* a frequency band that maps naturally to those three sliders.

### Pipeline position
**Before sharpening** and before local-contrast (Definition), because NR is a low-pass operation and any sharpening or clarity applied beforehand would amplify exactly what we're about to blur away. Order: exposure → white balance → NR → Definition → Selective Color → Sharpen → Vignette.

---

## 4. Sharpen

### What the controls do
Apple's verbatim definitions (https://support.apple.com/guide/photos/sharpen-a-photo-phtba5e3cf7d/mac):
- **Intensity**: "Adjusts the strength of the sharpened edges."
- **Edges**: "Sets the threshold for which groups of pixels are edges and which ones aren't."
- **Falloff**: "Makes the sharpening effect more or less prominent. Increasing the falloff value makes the sharpening more severe; decreasing it softens the effect."

Mapping to canonical unsharp-mask terminology:
- **Intensity** = amount (the gain on the high-pass residual).
- **Edges** = threshold (minimum local variance below which sharpening is suppressed — protects flat areas like skin and sky).
- **Falloff** = radius / blend exponent. Apple's "more or less prominent / more severe" wording matches a blend curve power, not a Gaussian radius — likely a gamma-style remap of the unsharp residual before adding back.

### Defaults and range
- Per MacMost community reporting, Photos defaults are **Intensity = 0.00, Edges = 0.22, Falloff = 0.69** (https://macmost.com/mac-photos-editing-shortcuts.html). Intensity = 0 means **no sharpening applied at default**; Edges and Falloff are shape parameters that only matter once Intensity moves off zero.
- Slider range is **0 to 1** for each; Option-drag extends the range (Apple docs).

### Core Image mapping
Two candidate filters:

| | `CIUnsharpMask` | `CISharpenLuminance` |
|---|---|---|
| Parameters | `inputRadius` (default 2.5), `inputIntensity` (default 0.5) | `inputRadius` (default ~1.69), `inputSharpness` (default ~0.4) |
| Color space | Operates in full RGB | Operates on luminance only — no chroma fringing on sharpened edges |
| Threshold | None — sharpens everything | None — sharpens everything |
| Source | https://cifilter.io/CIUnsharpMask/ | https://github.com/nst/iOS-Runtime-Headers/blob/master/Frameworks/CoreImage.framework/CISharpenLuminance.h |

**Recommendation**: use `CISharpenLuminance` as the base (it's what every modern editor does — sharpen on Y, not RGB), and add the missing Edges threshold via a custom CI Kernel or via a masked blend:

1. Compute Y from the input.
2. Compute local variance via a 3×3 box filter on (Y − Ȳ)² → variance map V.
3. Build threshold mask `m = smoothstep(edges × 0.02, edges × 0.05, V)` so flat areas (V below threshold) get no sharpening.
4. Run `CISharpenLuminance` with `inputSharpness = intensity` and `inputRadius` scaled by `(0.5 + falloff × 2)` — bigger radius for "more prominent."
5. Apply Falloff as an output gamma: `sharpened_Y = Y + sign × |Δ|^(1 + (1 − falloff) × 2)` so low Falloff softens midrange enhancement and keeps strong edges.
6. Blend sharpened Y back over original Y via mask `m`, recombine Y with Cb/Cr.

This three-stage interpretation reconciles Apple's three knobs with the two-parameter Core Image filters.

### Falloff vs Radius vs Edges
The brief asks for disambiguation. Best reading of the wording:
- **Edges** = pre-threshold (where to sharpen).
- **Intensity** = how much to add at edges.
- **Falloff** = post-shape — the curve that controls how the sharpened signal blends back across the dynamic range. Higher Falloff = harder/steeper blend = visually more "severe."

Falloff is **not** a Gaussian sigma — Photos exposes no Radius control as such. The kernel radius is fixed (or derived implicitly from Falloff).

### Pipeline position
**After NR and after Selective Color, before Vignette.** Sharpening after color so we sharpen the final color edges, not pre-grade edges; before vignette so the corner darkening doesn't get sharpened (which would re-introduce edge artifacts at the vignette boundary).

---

## 5. Vignette

### What the controls do
Apple's verbatim definitions (https://support.apple.com/guide/photos/apply-a-vignette-phtafbdcae9d/mac):
- **Strength**: "Darkens or lightens the vignette."
- **Radius**: "Changes the size of the vignette."
- **Softness**: "Changes the opacity of the vignette, making it more or less pronounced."

> The brief calls the controls "Radius / Intensity / Falloff" — that's Apple's naming for **Sharpen**, not Vignette. Photos' Vignette is **Strength / Radius / Softness**.

### Does Photos support a white vignette?
**Yes.** Apple's official wording — Strength "darkens or lightens the vignette" — explicitly covers both directions. MakeUseOf confirms: "Adjust Strength to modify the darkness or lightness of your vignette" (https://www.makeuseof.com/explaining-adjust-tools-in-photos-mac/). Strength is a bipolar slider: negative darkens (black vignette, the classic look), positive lightens (white vignette / halo).

### Slider semantics
- **Strength**: bipolar, default 0, range −1 to +1 (extends with Option). Sign flips vignette color (black ↔ white). Magnitude controls how strongly the corner color is mixed with the original at full vignette weight.
- **Radius**: 0 to 1. Photos does not document units; observation suggests **fraction of the image diagonal from center** — Radius near 0 puts the vignette right against the center (almost the whole image darkened); Radius near 1 pushes it to the corners (only extreme corners affected). This matches `CIVignette`'s `inputRadius` semantics where the vignette starts at `inputRadius` from center.
- **Softness**: 0 to 1, default mid. Controls the width of the falloff band between "fully unaffected" inside and "fully vignetted" outside. Curve shape is **smoothstep / Hermite**, not linear — vignettes that read as "natural" use S-curve falloffs because the human eye is sensitive to linear gradients in flat areas.

### Core Image mapping
Two CI filters are available:

| | `CIVignette` | `CIVignetteEffect` |
|---|---|---|
| Parameters | `inputRadius` (default 1.0), `inputIntensity` (default 0.0) | `inputCenter`, `inputRadius` (default 150), `inputIntensity` (default 1.0), `inputFalloff` (default 0.5) |
| Center | Image center, not configurable | Configurable `inputCenter` |
| Falloff | Implicit | Explicit `inputFalloff` parameter |
| Color | Black only (multiplicative darken) | Black only |
| Sign | `inputIntensity` documented as ≥ 0 — negative is **not documented** | Same |
| Source | https://github.com/emcconville/cif/wiki/CIVignette | https://developer.apple.com/documentation/coreimage/civignetteeffect, https://github.com/emcconville/cif/wiki/CIVignetteEffect |

Neither filter supports a **white vignette** directly. To get Photos' bipolar Strength:

1. Generate a vignette mask `M ∈ [0, 1]` using `CIVignetteEffect` with `inputIntensity = 1.0`, capturing the falloff curve and softness control. Use `CIColorMatrix` to invert and isolate the darkness amount.
2. Compute a **soft radial mask** independently via a custom `CIColorKernel`: `M(x, y) = smoothstep(r_in, r_out, distance / halfDiagonal)` where `r_in = radius × (1 − softness × 0.5)`, `r_out = radius + softness × 0.5`. This is portable and gives us a clean float mask.
3. Mix toward black or white based on sign of Strength:
   ```
   target = (strength < 0) ? black : white
   out = mix(original, target, |strength| × M)
   ```
   Implement as `CIBlendWithMask` with `backgroundImage = original`, `inputImage = CIConstantColorGenerator(color: target)`, `inputMaskImage = |strength| × M`.

Going the custom-kernel route is preferable because it gives a single bipolar Strength slider with consistent feel across signs, controls the falloff curve precisely (smoothstep), and supports any tint color if we later want sepia vignettes etc.

### Radius unit
`CIVignetteEffect` documents `inputRadius` in **pixels** (default 150). Photos clearly uses a **normalized** unit (a Radius of 1 isn't 1 px). In our implementation, normalize: `radius_px = radius_normalized × 0.5 × imageDiagonal`. This matches user expectation that Radius is resolution-independent.

### Falloff curve shape
Use **smoothstep** (Hermite, `3t² − 2t³`) for the falloff band — visually matches Photos and avoids the hard banding you see with linear ramps in skies. Exponential falloff is too aggressive at the inner edge.

### Pipeline position
**Last** — vignette is the final cosmetic step. Sharpening before vignette keeps the corner darken from re-introducing sharpening artifacts at its boundary, and any tint/grade should already be baked in before vignette so the vignette color is computed against the final image.

---

## Pipeline summary (recommended order)

```
input
  → exposure/white-balance/contrast       (out of scope here)
  → Noise Reduction                       (luma + chroma + detail)
  → Definition                            (clarity / local contrast)
  → Selective Color                       (HSL-masked grading)
  → Sharpen                               (luminance-only, threshold-gated)
  → Vignette                              (bipolar, smoothstep falloff)
output
```

Rationale: low-pass operations (NR) before high-pass (Definition, Sharpen) so we don't denoise away detail we just enhanced. Color grading after tone operators because Selective Color is sensitive to luminance distribution. Sharpen after grading so we sharpen the final edges. Vignette last because it's a cosmetic tone overlay.

---

## Open uncertainties

1. **Definition slider count** — Photos UI shows one slider; the brief asks for Radius + Intensity. Confirm whether we want fidelity to Photos (single slider, auto-radius) or to Lightroom Clarity (Radius + Intensity disclosure). No public docs give the Radius value Photos uses internally; the 2% of-short-edge rule comes from Adobe-style HiRaLoAm convention (https://www.russellcottrell.com/RCFilters/VHRUnsharpMask.php), not Apple.
2. **Selective Color chip count** — Apple's docs and three third-party tutorials all say **six** Photos wells, not eight. The brief's 8-chip list is Lightroom HSL. Product decision needed before UI is locked.
3. **Exact Photos slider numeric ranges** — Apple does not publish them. Defaults of Sharpen (0.00 / 0.22 / 0.69) come from MacMost comments (https://macmost.com/mac-photos-editing-shortcuts.html) and are believable but not Apple-authoritative. Definition, Selective Color, NR, Vignette defaults are inferred from Photos UI behavior (sliders sit at zero on a fresh image).
4. **Photos NR algorithm** — confirmed three sliders (Luminance / Color / Detail) appear for RAW v6+, but the underlying algorithm (bilateral? wavelet? non-local means? Apple's own neural NR?) is undocumented. Recent Photos versions likely use the neural-engine RAW pipeline shared with the Camera app, which we cannot match without ML — flag as a fidelity gap for RAW.
5. **CIVignette negative intensity** — Apple does not document support for `inputIntensity < 0` in either `CIVignette` or `CIVignetteEffect`. Empirically these clamp at zero. Custom kernel is the only safe path to a Photos-style bipolar Strength.
6. **Lightroom HSL hue band edges** — Adobe does not publish exact band edges, only the eight color names. Centers at 0/30/60/120/180/240/285/330° are conventional values used by darktable's color zones and most open-source HSL clones; flag as derived, not Adobe-authoritative.
7. **Sharpen Falloff exact curve** — Apple's wording ("more or less prominent / more severe") is ambiguous between (a) post-blend gamma, (b) radius scaler, (c) edge-mask softness. The recommendation above treats it as a gamma; revisit after side-by-side comparison with Photos at extreme Falloff values.
