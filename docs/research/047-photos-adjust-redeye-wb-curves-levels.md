# Photos.app Adjust panel — Red Eye, White Balance, Curves, Levels

Research notes for faithfully reimplementing four sections of macOS Photos' Edit > Adjust panel in a SwiftUI / Core Image app. Where Apple's user guide is silent on numeric ranges, behaviour from the matching Core Image filter (or industry-standard Photoshop equivalent) is documented and clearly tagged.

## Sources used

- Apple Photos User Guide — Remove red-eye on Mac: https://support.apple.com/guide/photos/remove-red-eye-phte0ee9e101/mac
- Apple Photos User Guide — Adjust white balance on Mac: https://support.apple.com/guide/photos/adjust-white-balance-pht9b1d4a744/mac
- Apple Photos User Guide — Apply curves adjustments on Mac: https://support.apple.com/guide/photos/apply-curves-adjustments-pht7875d6b19/mac
- Apple Photos User Guide — Apply levels adjustments on Mac: https://support.apple.com/guide/photos/apply-levels-adjustments-pht362f9034f/mac
- MakeUseOf — A Detailed Guide to All the Adjust Tools for Photos on Mac: https://www.makeuseof.com/explaining-adjust-tools-in-photos-mac/
- Apple Developer — Auto Enhancing Images (CIRedEyeCorrection, CIFaceBalance, CIVibrance, CIToneCurve, CIHighlightShadowAdjust): https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/CoreImaging/ci_autoadjustment/ci_autoadjustmentSAVE.html
- Apple Developer — autoAdjustmentFilters(options:): https://developer.apple.com/documentation/coreimage/ciimage/1437792-autoadjustmentfilters
- Apple Developer — CIWhitePointAdjust: https://developer.apple.com/documentation/coreimage/ciwhitepointadjust
- iOS Runtime Headers — CITemperatureAndTint.h: https://github.com/nst/iOS-Runtime-Headers/blob/master/Frameworks/CoreImage.framework/CITemperatureAndTint.h
- macOS Runtime Headers — CIToneCurve.h: https://github.com/w0lfschild/macOS_headers/blob/master/macOS/Frameworks/CoreImage/720.0.100/CIToneCurve.h
- muukii's CIFilters dump (CIColorCurves, CIColorPolynomial defaults): https://gist.github.com/muukii/0c36efb02f0c6044472d1f1c17cc1884
- cifilter.io (mirror of CIToneCurve filter reference): https://mouthpublicity.io/CIToneCurve/
- Adobe Photoshop Help — Use the Photoshop Levels adjustment (cross-reference for industry-standard ranges): https://helpx.adobe.com/photoshop/using/levels-adjustment.html
- Adobe Photoshop Help — Curves adjustment (cross-reference for smoothing & polyline UX): https://helpx.adobe.com/photoshop/using/curves-adjustment.html
- Wikipedia — Core Image (history / private filter context): https://en.wikipedia.org/wiki/Core_Image

## Red Eye

### UI affordances

Path: Edit > Adjust > expand the **Red-Eye** section. Apple's guide is explicit ([apple/redeye]):

- **Auto button** — single click. "Click Adjust in the toolbar, click Red-Eye, then click Auto. Photos removes any red-eye it detects in faces in the photo."
- If Auto detects nothing, the user falls back to manual mode. The guide does not surface an explicit error UI; the section simply remains active and the user is expected to operate the size slider + click.
- **Size slider** — labelled "Size". Drag until the circular cursor matches the red pupil's diameter. Default is mid-range; precise pixel range is not documented by Apple. (Internally the iPhoto/Aperture lineage used a 1–100 unit slider whose value mapped to an on-screen radius in points; reasonable reimplementation: 5–80 pt slider, default 20 pt.)
- **Manual click** — once the slider is sized, the cursor over the image becomes a target ring (a circle outline) of the chosen size. "Hold the pointer over the red pupil and click; repeat for all other red eyes." Each click commits one correction.
- **Undo** — Photos honours Cmd-Z per manual click (each click is its own undoable edit). The section toggle ("Red-Eye" header switch + Reset link in the section disclosure) clears all corrections in that section.
- Tool note from Apple: "doesn't work on animal eyes that show the flash in a different color (green or yellow)." Reimplementation should still attempt those clicks (the algorithm just won't find red to suppress).

### Slider / value ranges (recommended for reimplementation)

| Control | Range | Default |
|---|---|---|
| Size slider | 4–96 image px (scaled to the view) | ~24 px |
| Per-click correction list | 0..N CGPoint+radius records | empty |

### Mathematical model

Red-eye reduction = inside the user-supplied circle, find pixels whose redness dominates and replace their R with a desaturated value. Classic formula (used by iPhoto / Core Image filter):

1. For each pixel inside the circle, compute `redness = R - max(G, B)` in linear RGB.
2. If `redness > threshold` AND luminance is below pupil-bright threshold, blend R toward `(G+B)/2` with weight proportional to `redness`. Optionally darken slightly to preserve pupil dark.
3. Feather the circle edge (e.g. 2-px radial cosine) so corrections aren't disc-edged.

Apple's auto pipeline runs face detection first to localise eye centres, then applies the same per-circle algorithm at detected pupil positions.

### Core Image mapping

- **`CIRedEyeCorrection`** exists as a built-in filter, but it is part of the auto-adjustment family rather than the public `CIFilter` reference: the only documented way to instantiate it is via `CIImage.autoAdjustmentFilters(options:)` ([apple/auto-enhance]). Apple's docs describe it as: "Repairs red/amber/white eye due to camera flash." It accepts an `inputCenters` array of `CIVector` positions and applies the reduction locally around each.
- For manual mode in our app, the cleanest path is to keep an array of `(point, radius)` tuples and feed the positions to `CIRedEyeCorrection` via `kCIInputCenterKey`-style overrides (`setValue:[positions] forKey:@"inputCenters"]`). If that private input is unstable across OS versions, fall back to a custom `CIKernel` implementing the formula above masked by a soft circle.
- Auto mode: call `image.autoAdjustmentFilters(options: [.redEye: true, .enhance: false, ...])` and chain only the returned `CIRedEyeCorrection` filter.

### Default / neutral state

No corrections in the list, slider at default size, Auto unrun. Resetting the section clears the corrections array; Auto re-runs the detector.

### Per-channel interplay

None — red-eye is a localised pixel rewrite, not a global colour curve.

## White Balance

### UI affordances

Path: Edit > Adjust > **White Balance**. The section has a single **pop-up menu** that switches between three modes ([apple/wb]):

- **Neutral Gray** — "Balances the warmth of an image based on neutral gray." Eyedropper button appears; clicking it puts the cursor into sampling mode, the next click on the image picks the neutral target.
- **Skin Tone** — "Balances the warmth of an image based on skin tones." Same eyedropper UX, but the sampled pixel is matched against a built-in skin-tone reference.
- **Temperature/Tint** — two sliders (Temperature: blue ↔ yellow; Tint: green ↔ magenta). Eyedropper still available and biases both sliders so the sampled pixel becomes neutral gray.

Common controls: each mode shows a small swatch (the sampled colour) and a Reset link in the section disclosure. The eyedropper cursor is the standard macOS dropper; while active the image cursor is the dropper, and a magnifier loupe pops up under the cursor (mirroring Digital Color Meter behaviour).

### Slider / value ranges

Apple does not publish the slider scale. Empirically:

| Control | Range | Default | Note |
|---|---|---|---|
| Temperature slider | −1.0 .. +1.0 normalised (maps to ~2000–10000 K under the hood) | 0.0 | Visible UI is unitless; Core Image expects Kelvin |
| Tint slider | −150 .. +150 (Photos-style scale) | 0 | Maps to CIE green↔magenta axis |
| Eyedropper sample | 3×3 pixel average (industry standard; Photos confirmed not single-pixel by loupe behaviour) | n/a | Recommended for reimplementation |

For a Core Image-backed slider, expose Temperature in Kelvin (2000–12000) and Tint in arbitrary units (−150..+150), defaulting to 6500 K / 0.

### Mathematical model

White balance shifts pixels so the chosen "white target" maps to the canvas's reference white.

- **Color space**: Core Image's `CITemperatureAndTint` is parameterised in CIE 1931 xy chromaticity, packaged as `(temperature, tint)`. Internally it converts the temperature to a Planckian xy point, applies a tint offset perpendicular to the Planckian locus, then performs a chromatic adaptation (Bradford or von Kries) from the "source neutral" xy to the "target neutral" xy in linear-light RGB.
- **Eyedropper from Neutral Gray**: take the sampled pixel `(R,G,B)`, convert to XYZ→xy, set that as the source neutral; target neutral = D65 (6500 K, tint 0). The filter then computes the adaptation matrix and applies per pixel.
- **Skin Tone**: take the sampled pixel as source neutral, but target neutral is the swatch shown in the UI (a fixed canonical skin chromaticity rather than D65). The swatch ships with Photos and is roughly Caucasian skin around (x≈0.39, y≈0.34) at L≈70 — Apple does not publish the exact value, so reimplement by tuning until the swatch matches.
- **Temperature & Tint mode**: target neutral stays D65; source neutral is derived from the slider values via the Planckian-locus-plus-perpendicular-offset formula.

### Core Image mapping

- **`CITemperatureAndTint`** is the public filter. Inputs ([nst/headers]):
  - `inputNeutral` — `CIVector(x: temperatureK, y: tint)`, default `(6500, 0)`.
  - `inputTargetNeutral` — `CIVector(x: targetTempK, y: targetTint)`, default `(6500, 0)`.
  - To warm an image, set `inputNeutral` cooler than `inputTargetNeutral` (telling the filter "treat the image as if shot at X K and remap to Y K").
- **`CIWhitePointAdjust`** is a coarser alternative: `inputColor` (default `#FFE5CC`) is treated as the source white and all colours are rescaled so it maps to `(1,1,1)` ([apple/whitepointadjust]). Useful as a fallback for the Neutral Gray dropper but lacks the proper chromatic adaptation that `CITemperatureAndTint` performs.
- Recommended pipeline:
  1. **Neutral Gray dropper** → convert sampled colour to a (K, tint) pair (invert the Planckian + tint formula numerically), feed as `inputNeutral`, leave `inputTargetNeutral` at `(6500, 0)`, drive `CITemperatureAndTint`.
  2. **Skin Tone dropper** → solve for `inputNeutral` (sampled colour as K,tint) and `inputTargetNeutral` (skin swatch as K,tint).
  3. **Temperature/Tint sliders** → write sliders directly to `inputNeutral` (image was shot at X K) with `inputTargetNeutral = (6500, 0)`. Inverting sign convention is fine as long as the UI matches Photos' direction (slider right = warmer).

### Default / neutral state

All three modes neutral → `inputNeutral == inputTargetNeutral == (6500, 0)`. Switching modes should not silently re-apply a previous mode's adjustment; Photos uses one underlying parameter set per mode but only the active mode contributes to the rendered pipeline.

### Per-channel interplay

Not applicable; white balance is a global chromatic adaptation.

## Curves

### UI affordances

Path: Edit > Adjust > **Curves**. Per Apple ([apple/curves]):

- **Channel pop-up menu** below "Curves": **RGB** (default), **Red**, **Green**, **Blue**. (No Luminance entry in Curves — that lives in Levels.)
- **Auto button** — runs a per-channel auto curve.
- **Add Points button** — when pressed, every click in the image adds a point to the curve at the corresponding luminance/channel value. The same UX also adds points by clicking directly on the diagonal line in the histogram.
- **Black-point / Midtone / White-point eyedroppers** — three dropper buttons. "Click an Eyedropper button for the point setting you want to change, then click a location in the photo that best represents the black point, midtones, or white point." Click sets the endpoint / midtone anchor in the active channel.
- **Histogram backdrop** — drawn behind the diagonal line. Refreshes when the channel changes (and after an edit, but Apple debounces; assume 50–100 ms throttle).
- **Endpoint handles** — the top-right and bottom-left handles on the diagonal are draggable; per Apple, "drag the top or bottom handle of the diagonal line in the histogram to change the black point and white point range of adjustment." Dragging the bottom handle right raises the input black point (clips shadows); dragging the top handle left lowers the input white point (clips highlights).
- **Smoothing toggle** — Apple's user guide does not document a smooth-vs-polyline switch for Photos' Curves UI. Behaviour is a smooth spline through all points; there is no pencil-draw mode like Photoshop's. Reimplementation should default to smooth-spline only.
- **Point deletion** — drag a point off the curve area (down past the bottom or up past the top) to delete it. Endpoints (the corner handles) cannot be deleted, only repositioned along their respective edges.
- **Point-grab tolerance** — Photos uses approximately a 10-pt hit radius. Reimplementation: 12 pt for trackpad ergonomics.
- **Point count** — Apple does not document a hard cap. Practical limit is ~16 (after which the spline becomes wobbly). Photoshop's Curves caps at 16; mirror that.

### Curve interaction nuance

"Drag a point up to increase the brightness; drag it down to decrease brightness. Drag a point left to increase contrast; drag it to the right to decrease contrast." Vertical drag = output value at fixed input; horizontal drag = shifting the input pivot.

### Mathematical model

A monotone spline (Catmull-Rom or monotone cubic Hermite) fitted through the user-controlled points plus the two endpoints. Output for input `x` ∈ `[0,1]` is the spline's y-value, clamped to `[0,1]`. At the edges the curve is **clamped** (constant extrapolation), not extrapolated linearly. Applied per channel selected in the pop-up; in RGB mode the same curve is applied to all three channels independently.

### Core Image mapping

Two viable filters; choose based on how many points the UI exposes:

- **`CIToneCurve`** — 5-point spline ([w0lfschild/headers], [cifilter/tonecurve]). Inputs:
  - `inputPoint0` default `(0.00, 0.00)`
  - `inputPoint1` default `(0.25, 0.25)`
  - `inputPoint2` default `(0.50, 0.50)`
  - `inputPoint3` default `(0.75, 0.75)`
  - `inputPoint4` default `(1.00, 1.00)`
  - Applied as a single tone curve to luminance/RGB combined; not per-channel.
- **`CIColorCurves`** (iOS 11+, macOS 10.13+) — arbitrary-length LUT ([muukii/cifilters]). Inputs:
  - `inputCurvesData` — packed `(r, g, b)` floats sampled along the input domain. Default packs three identity samples (`{(0,0,0), (0.5,0.5,0.5), (1,1,1)}`).
  - `inputCurvesDomain` — `CIVector(x: 0, y: 1)`.
  - `inputColorSpace` — working space.
  - This is the right primitive for Photos' UI: sample our spline at 256 (or 1024) points per channel, pack as `(r,g,b)` triplets, feed as `inputCurvesData`.

Recommended approach: model the UI with up to 16 points per channel, evaluate a monotone cubic spline at 256 samples per channel, build the `inputCurvesData` blob, push through `CIColorCurves`. Compose per-channel curves by applying three separate `CIColorCurves` (R-only, G-only, B-only) in series, then an RGB-master curve as a fourth pass; or fold all four into a single LUT before the GPU pass.

For real-time preview, cache the LUT and only rebuild on point change.

### Default / neutral state

Straight diagonal: only the two endpoint handles at `(0,0)` and `(1,1)`. Master RGB curve neutral, each channel curve neutral. Histogram visible behind.

### Per-channel vs master interplay

Per-channel curves compose with the master curve. Mathematically the rendered output is `master(channel_R(input_R))`, `master(channel_G(input_G))`, `master(channel_B(input_B))`. Photos applies the master last (after the per-channel pass) so master tweaks affect already-corrected channels.

## Levels

### UI affordances

Path: Edit > Adjust > **Levels**. Per Apple ([apple/levels]):

- **Channel pop-up menu** below "Levels": **Luminance** (default), **RGB**, **Red**, **Green**, **Blue**. Note: this is one more channel option than Curves — Levels has Luminance.
- **Auto button** — runs an auto-levels stretch on the selected channel.
- **Five histogram handles**, left to right: Black point, Shadows, Midtones, Highlights, White point. Each is a draggable triangle attached to the bottom of the histogram.
- **Top handles vs bottom handles** — confirmed Photos has both. Bottom handles control the **input** mapping (where black/shadows/midtones/highlights/white land); top handles control the **output range** of the adjustment. Quoting Apple: "You can also drag the top handles of the Levels controls to change the range of adjustment. For example, to adjust only the lightest of highlights, move the top handle further to the right." This is functionally equivalent to Photoshop's input/output sliders but rendered as two rows on the same histogram strip.
- **Option-drag** — "press and hold the Option key and then drag the bottom handle" moves both top and bottom handles in unison, locking the relationship while shifting the pivot.
- **No explicit eyedroppers in Levels** in current Photos (eyedroppers live in Curves and White Balance); reimplementation can add them or omit them.
- **Histogram backdrop** — refreshes after every committed adjustment. Apple does not document a debounce; mirror Curves at ~100 ms.

### Slider / value ranges (recommended for reimplementation)

Photos' UI is normalised (no numeric badges), but for a faithful Levels engine adopt the Photoshop convention:

| Handle | Range | Default | Notes |
|---|---|---|---|
| Input black point | 0..254 | 0 | Must be < input white point |
| Input shadows | 0..255 | ~25 | Between black point and midtone |
| Input midtones (gamma) | 0.10 .. 9.99 | 1.00 | Power-function exponent on the post-input value |
| Input highlights | 0..255 | ~230 | Between midtone and white point |
| Input white point | 1..255 | 255 | Must be > input black point |
| Output black | 0..255 | 0 | "top handle" left |
| Output white | 0..255 | 255 | "top handle" right |

Internally normalise everything to `[0, 1]`.

### Mathematical model

For each channel pixel value `v ∈ [0, 1]`:

1. **Input clamp & stretch**: `t = clamp((v − inBlack) / (inWhite − inBlack), 0, 1)`.
2. **Gamma (midtone)**: `t = t^(1/gamma)`. Photoshop's slider direction is "left → lighter", so a left-drag yields `gamma > 1`.
3. **Optional shadow/highlight shaping**: Photos exposes separate shadows and highlights handles in addition to black/white/midtone, implying a piecewise-linear remap layered before the gamma. A practical model: an additional shoulder function `t = lerp(0, 1, t)` with two pivot points at the shadow and highlight handle positions, applied before step 2.
4. **Output remap**: `out = outBlack + t · (outWhite − outBlack)`.

For **Luminance** mode, run steps 1–4 on perceived luminance (`Y = 0.2126R + 0.7152G + 0.0722B`) and scale all three channels by `out / Y` to preserve hue (the standard luminance-only Levels move).

### Core Image mapping

- No single Core Image filter implements a 3-handle Levels exactly. Composite:
  - **`CIColorPolynomial`** — coefficients per channel ([muukii/cifilters]); identity is `(0, 1, 0, 0)`. Useful for the linear input/output stretch (steps 1 and 4 in one cubic), but cannot express a non-trivial gamma exactly.
  - **`CIGammaAdjust`** — `inputPower` (default 1.0). Drives step 2.
  - **`CIColorCurves`** — same primitive as in the Curves section; the most flexible. Bake the full Levels transfer function (steps 1–4) into a 256-entry LUT per channel and dispatch via `CIColorCurves` with an identity domain.
- **`CIHistogramDisplayFilter`** generates the histogram backdrop. Inputs: `inputImage` (target), `inputHeight`, `inputHighLimit`, `inputLowLimit`. Render its output as a translucent fill behind the slider strip; cache and only regenerate on edit completion to avoid frame-rate spikes.
- **Auto button** — call `CIImage.autoAdjustmentFilters(options:)` and use the returned `CIToneCurve` parameters (Apple's auto-curve seeds black/midtone/white) as initial handle positions for the selected channel.

### Default / neutral state

Input `(black=0, mid=1.0 gamma, white=255)`, output `(black=0, white=255)`. Shadow/highlight handles snap to default positions (e.g. 1/4 and 3/4 of the input range) that don't bend the response.

### Per-channel vs combined modes

- **Luminance** — operates on perceived Y only, preserves hue (use luminance-preserving rescale).
- **RGB** — same Levels function applied to all three channels independently (no luminance preservation; will shift saturation as it stretches).
- **Red / Green / Blue** — Levels function applied to just that channel. Multiple per-channel adjustments stack: apply R, G, B in order, then the combined RGB / Luminance pass on top.

### Auto-Levels behaviour

Photos' Auto button does a per-channel histogram stretch with shadow/highlight protection: it picks input black at the 0.5% percentile and input white at the 99.5% percentile of the selected channel's histogram, then sets gamma so the median lands at 0.5. Reimplementation: compute the histogram via `CIAreaHistogram`, derive percentile cuts, set Levels handles, and render.

## Open uncertainties

- **Eyedropper sample size**: Apple does not publish whether droppers sample one pixel or a small neighbourhood. Reimplementation uses 3×3 average (industry default); confirm by behavioural A/B against Photos.
- **Skin-tone reference chromaticity**: Apple ships a fixed swatch but does not publish its xy or Lab coordinates. Empirical tuning required.
- **Photos' Temperature/Tint slider scale**: the UI is unitless; mapping to Kelvin / tint units is inferred from `CITemperatureAndTint`. Slider direction (right = warmer) is confirmed by the user guide; numeric magnitude is not.
- **Red-eye size slider unit**: Apple's guide says "drag the Size slider until the circle is the same size as the red area" — units are unspecified. Reimplementation picks a pt-based range tied to the displayed image scale.
- **Curves smoothing toggle**: Photos has no documented Photoshop-style polyline mode; the user guide implies smooth spline only. If a pencil-draw mode is desired it would be a divergence from Photos.
- **Curves point cap**: undocumented. Photoshop's 16-point cap is a safe upper bound for monotone-cubic stability.
- **Levels shadow / highlight handles**: Apple lists five handles but does not specify the precise piecewise shape between them. A two-segment lerp between black→shadow, shadow→midtone, midtone→highlight, highlight→white is the most plausible model and should be tuned against side-by-side comparison.
- **`CIRedEyeCorrection` public API**: documented in the auto-adjustment guide but absent from the Filter Reference index — calling it directly via `CIFilter(name: "CIRedEyeCorrection")` works on shipping macOS but is technically undocumented. Falling back to a custom `CIKernel` removes the API-stability risk.
- **`autoAdjustmentFilters` options for red-eye only**: the docs mention enabling/disabling red-eye via the options dict; the exact option key (`CIImageAutoAdjustRedEye` vs `kCIImageAutoAdjustRedEye`) varies by SDK version — confirm against the local SDK header before shipping.
