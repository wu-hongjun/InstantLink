# 047 — Core Image / Metal Implementation Mapping

Practical implementation reference for the Photos-style editor rebuild
(see `docs/plans/047-photos-style-editor-audit.md` §2.2). Pairs every UI
slider to a CIFilter (or custom kernel), names the input parameter,
gives the range mapping from Photos' −1..+1 slider to Core Image
native ranges, and notes color-space caveats. Sections 2–7 cover
pipeline order, live-preview architecture, undo/redo, histograms,
crop/perspective, and the eyedropper.

## Sources used

- Apple Developer Documentation — CIFilter / Core Image reference
  pages: `CIHighlightShadowAdjust`, `CITemperatureAndTint`,
  `CIToneCurve`, `CIPerspectiveCorrection`, `CIContext`
  (`workingColorSpace`).
  <https://developer.apple.com/documentation/coreimage>
- Apple Developer Forums — "Core Image: Gamma curve best practice",
  "Getting wide color with Core Image and MTKView (iOS)",
  "Metal Core Image kernel workingColorSpace".
  <https://developer.apple.com/forums/thread/649425>
  <https://developer.apple.com/forums/thread/66166>
  <https://developer.apple.com/forums/thread/741441>
- WWDC22 — "Display EDR content with Core Image, Metal, and SwiftUI".
  <https://developer.apple.com/videos/play/wwdc2022/10114/>
- Apple Library Archive — "Core Image Filter Reference" /
  "Subclassing CIFilter: Recipes for Custom Effects" /
  "Auto Enhancing Images".
  <https://developer.apple.com/library/archive/documentation/GraphicsImaging/Reference/CoreImageFilterReference/>
- Microsoft Learn — Xamarin CoreImage mirror with parameter defaults
  for `CIVibrance`, `CIHighlightShadowAdjust`, `CITemperatureAndTint`,
  `CIToneCurve`, `CIUnsharpMask`. Useful when Apple's pages omit
  numeric defaults.
  <https://learn.microsoft.com/en-us/dotnet/api/coreimage>
- objc.io — "An Introduction to Core Image" (deferred evaluation,
  context reuse).
  <https://www.objc.io/issues/21-camera-and-photos/core-image-intro/>
- FlexMonkey — "Creating a Selective HSL Adjustment Filter in Core
  Image" (custom CIKernel for 8-swatch HSL).
  <http://flexmonkey.blogspot.com/2016/03/creating-selective-hsl-adjustment.html>
- DZone — "A Look at Perspective Transform and Correction With Core
  Image".
  <https://dzone.com/articles/a-look-at-perspective-transform-correction-with-co>
- FlexMonkey/CoreImageHelpers — `MetalImageView` (reference MTKView
  rendering pattern).
  <https://github.com/FlexMonkey/CoreImageHelpers/blob/master/CoreImageHelpers/coreImageHelpers/ImageView.swift>
- Thomas1956/Histogram — CIAreaHistogram + CIHistogramDisplayFilter
  example.
  <https://github.com/Thomas1956/Histogram>
- IMG.LY — "Build a Simple Real-Time Video Editor with Metal" (live
  preview architecture).
  <https://img.ly/blog/build-a-simple-real-time-video-editor-with-metal-for-ios/>

---

## 1. Slider → CIFilter mapping table

UI slider ranges are the Photos convention (sliders snap to **0** as
neutral; range nominally **−1..+1** unless noted). The "Range mapping"
column shows how to translate slider `s` into the filter's native
input. All filters live in Core Image unless prefixed `custom:`.

| # | Slider                          | Section            | CIFilter / Composite                                                      | Input param                                                  | Range mapping (`s` ∈ −1…+1 unless noted)                                                                                 | Color-space notes                                                                                                                          |
|---|---------------------------------|--------------------|---------------------------------------------------------------------------|--------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | Brilliance                      | Light              | composite: `CIHighlightShadowAdjust` + `CIToneCurve` micro-S              | `inputHighlightAmount`, `inputShadowAmount`, curve points    | `highlight = 1 − 0.5·max(s,0)`; `shadow = 0.5·max(s,0)`; for `s<0` reduce both. Add a +mid lift via toneCurve point2.    | Run in linear sRGB so highlight-roll-off behaves like film.                                                                                |
| 2 | Exposure                        | Light              | `CIExposureAdjust`                                                        | `inputEV`                                                    | `EV = 2·s` (so ±1 slider ≈ ±2 stops, Photos' visible range).                                                            | Must run in **linear** space (it's a stop multiply, `out = in · 2^EV`).                                                                    |
| 3 | Highlights                      | Light              | `CIHighlightShadowAdjust`                                                 | `inputHighlightAmount`                                       | Native is `0.0…1.0`, default `1.0` (no change). Map `s≥0` → `1 − s·0.7`; `s<0` → `1 − s·0.3` (lift). Clamp 0.3…1.0.    | Apple notes the filter "adjusts highlights to reduce shadows"; ship-fix: run in linear, then re-encode.                                    |
| 4 | Shadows                         | Light              | `CIHighlightShadowAdjust`                                                 | `inputShadowAmount`                                          | Native is `−1.0…+1.0`, default `0`. Map directly: `shadowAmount = s`.                                                  | Linear space (same instance as Highlights — share one filter, set both inputs at once).                                                    |
| 5 | Brightness                      | Light              | `CIColorControls`                                                         | `inputBrightness`                                            | Native `−1…+1`, default `0`. `brightness = 0.3·s` (Photos' slider is gentler than CIColorControls raw).                | Runs in working space; safe in linear or sRGB. Use linear.                                                                                  |
| 6 | Contrast                        | Light              | `CIColorControls`                                                         | `inputContrast`                                              | Native default `1.0`, useful range `0.25…4.0`. `contrast = 1 + 0.6·s` (so ±1 ≈ 0.4…1.6).                              | Run in **sRGB-gamma** for "perceptual" contrast — that matches Photos' look. (Linear contrast crushes too aggressively at low end.)         |
| 7 | Black Point                     | Light              | `CIToneCurve`                                                              | `inputPoint0`                                                | Move point0 along x: `point0 = CGPoint(x: max(0, 0.1·s + 0.0), y: 0)` for `s>0` (crush); for `s<0` (lift): `point0.y = 0.1·\|s\|`. | Apple states tone curve uses "a perceptual (gamma 2) version of the working space" — so it's already perceptual.                            |
| 8 | Saturation                      | Color              | `CIColorControls`                                                         | `inputSaturation`                                            | Native `0.0…2.0+`, default `1.0`. `saturation = 1 + s` (clamp 0…2).                                                    | Run in linear space, otherwise greens skew yellow.                                                                                          |
| 9 | Vibrance                        | Color              | `CIVibrance`                                                              | `inputAmount`                                                | Native `−1.0…+1.0`, default `0`. Direct: `amount = s`.                                                                  | Apple's `CIVibrance` boosts less-saturated colors more. No color-space change needed.                                                       |
| 10 | Cast                           | Color              | `CITemperatureAndTint` (or `CIHueAdjust` for pure rotation)                | `inputNeutral` / `inputTargetNeutral` (Vec2 [temp, tint])     | "Cast" in Photos is a hue rotation. Use `CIHueAdjust.inputAngle = s · π/6` (±30°). If using T&T, leave neutral=(6500,0), `targetNeutral=(6500, 50·s)`. | Hue rotation should run in linear; T&T expects raw RGB.                                                                                     |
| 11 | B&W Intensity                  | Black & White       | `CIPhotoEffectMono` + `CIColorControls.inputSaturation = 0` blended       | mix amount via `CIBlendWithMask` or `CIDissolveTransition`    | `mix = (s + 1)/2` (full-color at 0, full-mono at +1; in Photos B&W mode the slider is asymmetric — research file `…-light-color-bw` confirms).            | sRGB.                                                                                                                                       |
| 12 | B&W Neutrals                   | Black & White       | `CIToneCurve` on mid-grey                                                  | `inputPoint2`                                                | Shift point2.y by `0.1·s` around `(0.5, 0.5)`.                                                                          | Perceptual (gamma 2) — built into CIToneCurve.                                                                                              |
| 13 | B&W Tone                       | Black & White       | `CIToneCurve` global S-curve                                              | points 1–3                                                   | `s>0`: deepen S; `s<0`: flatten. Build curve from `(0,0),(0.25, 0.25−0.05·s),(0.5,0.5),(0.75, 0.75+0.05·s),(1,1)`.    | Perceptual.                                                                                                                                  |
| 14 | B&W Grain                      | Black & White       | `CIRandomGenerator` × `CIColorMatrix` (mono) blended `CISourceOverCompositing` | grain opacity                                              | `opacity = max(0, s)`; 0 = off.                                                                                         | Composite after all luma ops, in sRGB.                                                                                                       |
| 15 | Red Eye (Auto)                 | Red Eye            | `CIRedEyeCorrection`                                                      | `inputCenters` (CIVector array)                              | Use `CIDetector(ofType: CIDetectorTypeFace)` and `CIDetectorEyeBlink` to find centers, feed in.                         | sRGB.                                                                                                                                       |
| 16 | Red Eye (manual click)         | Red Eye            | `CIRedEyeCorrection`                                                      | `inputCenters`                                               | Append click point in image coords.                                                                                     | sRGB.                                                                                                                                       |
| 17 | WB Neutral Gray (eyedropper)   | White Balance      | `CITemperatureAndTint`                                                    | `inputNeutral`                                               | Sample pixel `(r,g,b)`, convert to estimated CCT (e.g. McCamy), set `inputNeutral = CIVector(x: cct, y: tintShift)`.    | Sample on the **un-adjusted** linear CIImage so eyedrop is repeatable.                                                                       |
| 18 | WB Skin Tone (eyedropper)      | White Balance      | `CITemperatureAndTint`                                                    | `inputTargetNeutral`                                         | Same as Neutral Gray but solve for skin chromaticity (~(5500, 8)).                                                      | Linear.                                                                                                                                      |
| 19 | WB Temperature                 | White Balance      | `CITemperatureAndTint`                                                    | `inputNeutral.x`                                             | Slider `s∈−1…+1` → `temp = 6500 + 4000·s` (so cool ≈ 2500K, warm ≈ 10500K).                                            | Linear.                                                                                                                                      |
| 20 | WB Tint                        | White Balance      | `CITemperatureAndTint`                                                    | `inputNeutral.y`                                             | `tint = 150·s` (Photos' tint range is roughly ±150).                                                                    | Linear.                                                                                                                                      |
| 21 | Curves (RGB / R / G / B)       | Curves             | `CIToneCurve` per channel; or custom `CIColorCubeWithColorSpace` LUT      | `point0…point4` (Photos' 5-point spline is identical)        | Direct mapping — Photos' tone-curve UI has 5 points. For per-channel: run 3 chained `CIToneCurve`s with `inputBrightness` matrix gating, or a single CIKernel that takes one LUT. | CIToneCurve runs in **perceptual** working space. For wide gamut, set `CIContext(options: [.workingColorSpace: linearSRGB])` and tone curve still operates perceptually. |
| 22 | Levels Input Black/White       | Levels             | `CIColorMatrix` (scale+bias) → `CIGammaAdjust`                            | matrix coefficients; `inputPower`                            | `gain = 1 / (whiteIn − blackIn)`; `bias = −blackIn · gain`. Then `gamma = log(0.5)/log(gammaSlider/255)` (Photoshop math). | Perceptual / sRGB; histogram-aligned.                                                                                                       |
| 23 | Levels Gamma                   | Levels             | `CIGammaAdjust`                                                           | `inputPower`                                                 | `power = 1/(0.1 + 1.9·((s+1)/2))` so slider 0 → 1.0 (no change), +1 → 1/2 = brighter midtones, −1 → ~1/0.1.            | sRGB-gamma space (gamma adjust is inherently a gamma op).                                                                                    |
| 24 | Levels Output Black/White      | Levels             | `CIColorMatrix`                                                           | bias / scale                                                 | `scale = whiteOut − blackOut`; `bias = blackOut`.                                                                       | sRGB.                                                                                                                                       |
| 25 | Definition Radius              | Definition         | custom: `CIUnsharpMask` w/ large radius + low intensity (local contrast)  | `inputRadius`                                                | `radius = 10 + 40·((s+1)/2)` (Photos' radius is hidden but tunable here — say 10…50 px).                                | Run on luma channel only; convert to YCbCr via `CIColorMatrix` then back to avoid color shifts.                                              |
| 26 | Definition Intensity           | Definition         | `CIUnsharpMask`                                                           | `inputIntensity`                                             | `intensity = 0.4·s` (subtle; >0.5 = halos).                                                                              | sRGB.                                                                                                                                       |
| 27 | Selective Color H/S/L (×8)     | Selective Color    | **custom CIColorKernel** (per FlexMonkey)                                  | hueEdge0/1, hueShift/satShift/lumShift vec3 per band         | Each swatch maps to a 45° hue band (`Red 0±22.5°`, `Orange 30°`, `Yellow 60°`, `Green 120°`, `Aqua 180°`, `Blue 240°`, `Purple 270°`, `Magenta 300°`). Each H/S/L slider feeds the kernel as `±0.2·s` shift. | Run in linear HSV; convert RGB→HSV in-kernel then back. Use `CIContext.workingColorSpace = extendedLinearSRGB`.                              |
| 28 | NR Luma                        | Noise Reduction    | `CINoiseReduction`                                                        | `inputNoiseLevel`                                            | `noiseLevel = 0.02 + 0.06·max(0, s)` (default off at slider 0).                                                         | Linear.                                                                                                                                      |
| 29 | NR Color                       | Noise Reduction    | `CIMedianFilter` (chroma) or chained `CIGaussianBlur` on Cb/Cr channels    | (none / σ)                                                   | Convert to YCbCr; blur chroma with σ = `0.0 + 4·max(0, s)`; recombine.                                                  | Linear.                                                                                                                                      |
| 30 | NR Detail                      | Noise Reduction    | `CINoiseReduction`                                                        | `inputSharpness`                                             | `sharpness = 0.4 + 1.6·((s+1)/2)`.                                                                                       | Same instance as NR Luma — single filter, two inputs.                                                                                        |
| 31 | Sharpen Intensity              | Sharpen            | `CIUnsharpMask`                                                           | `inputIntensity`                                             | `intensity = max(0, s)·1.0` (Photos clamps at 0; negative slider does nothing).                                          | sRGB.                                                                                                                                       |
| 32 | Sharpen Edges                  | Sharpen            | `CIUnsharpMask`                                                           | `inputRadius`                                                | `radius = 1.0 + 3·((s+1)/2)` (Photos uses radius ~1–4 px).                                                              | sRGB.                                                                                                                                       |
| 33 | Sharpen Falloff                | Sharpen            | custom kernel: edge-mask attenuation                                       | falloff scalar                                               | Multiply unsharp delta by `Sobel(luma)^falloff`; `falloff = 0.5 + 2·((s+1)/2)`.                                          | sRGB.                                                                                                                                       |
| 34 | Vignette Radius                | Vignette           | `CIVignette`                                                              | `inputRadius`                                                | `radius = 0.5 + 1.5·((s+1)/2)` (Photos range maps ~0.5…2.0).                                                            | Apply last, in sRGB.                                                                                                                         |
| 35 | Vignette Intensity             | Vignette           | `CIVignette`                                                              | `inputIntensity`                                             | `intensity = s` directly. Negative = black vignette, positive = white (requires a sign flip — use `CIVignetteEffect` for white). | sRGB.                                                                                                                                       |
| 36 | Vignette Falloff               | Vignette           | composite: blend `CIVignette` w/ `CIRadialGradient` mask                   | gradient `inputRadius1` width                                | `falloffWidth = 0.1 + 0.5·((s+1)/2)`.                                                                                    | sRGB.                                                                                                                                       |

**Notes on the table**

- `CIHighlightShadowAdjust` defaults: `inputHighlightAmount=1.0`,
  `inputShadowAmount=0.0`; range `0…1` for highlight, `−1…+1` for
  shadow (Apple docs, mirrored on Microsoft Learn). The filter is
  cheap enough to share one instance for both sliders.
- `CIToneCurve` defaults: `point0=(0,0)`, `point1=(0.25,0.25)`,
  `point2=(0.5,0.5)`, `point3=(0.75,0.75)`, `point4=(1,1)`. Apple's
  docs state it interpolates with a spline in a "perceptual (gamma 2)
  version of the working space" — useful: it already does sRGB-feel
  curves regardless of `workingColorSpace`.
- `CITemperatureAndTint` `inputNeutral` is a `CIVector(x:6500, y:0)`
  by default; x is Kelvin, y is tint magnitude (positive = magenta,
  negative = green per Apple's coord convention).
- For Selective Color the "no 1:1 match" route is mandatory. The
  FlexMonkey kernel uses `smoothstep(hueEdge0, hueEdge1, hue)` to
  fade between bands. For 8 swatches × 3 sliders × 24 controls we
  ship one CIColorKernel with 8 vec3 uniforms for hue/sat/lum.

---

## 2. Pipeline composition order

Confirmed order (raw-decode → output) for our pipeline. The classic
order in the prompt is mostly right; below is the corrected /
expanded order based on Apple's "Auto Enhancing Images" guide and
forum guidance about linear vs gamma space.

```
1. Decode (CIImage(contentsOf: …, options: [.applyOrientationProperty: true]))
2. White Balance               (CITemperatureAndTint, linear)
3. Exposure                    (CIExposureAdjust, linear) ← MUST be linear
4. Highlights / Shadows        (CIHighlightShadowAdjust, linear)
5. Brilliance                  (composite, linear)
6. Black Point                 (CIToneCurve, perceptual built-in)
7. Brightness / Contrast       (CIColorControls; contrast in sRGB look)
8. Curves                      (CIToneCurve per channel, perceptual)
9. Levels                      (CIColorMatrix + CIGammaAdjust, sRGB)
10. Color (Sat / Vibrance / Cast)  (CIColorControls + CIVibrance + CIHueAdjust)
11. Selective Color            (custom CIColorKernel, linear-HSV)
12. B&W stack (if on)          (CIPhotoEffectMono + tone curves)
13. Definition                 (luma-only CIUnsharpMask, sRGB)
14. Noise Reduction            (CINoiseReduction + chroma median, linear)
15. Sharpen                    (CIUnsharpMask, sRGB) ← AFTER NR
16. Red Eye                    (CIRedEyeCorrection, sRGB)
17. Geometry: rotate → perspective → straighten → flip → crop  (single CIAffineTransform where possible)
18. Vignette                   (CIVignette, sRGB) ← AFTER crop
19. Output encode (CIContext.outputColorSpace)
```

Corrections vs. the prompt:

- **Sharpen AFTER NR** (not before). Sharpening noise then trying to
  denoise it is destructive. Photos does it this order.
- **Vignette AFTER crop**, not before. Otherwise the vignette darkens
  the cropped corners unpredictably.
- **Geometry as one CIAffineTransform** where possible — Core Image
  concatenates transforms losslessly. Only fall back to discrete
  `CIPerspectiveTransform` when the keystone slider is non-zero.

Pre- vs post-gamma sliders:

- **Linear (pre-gamma)**: Exposure, White Balance, Highlights/Shadows,
  NR (chroma blur).
- **Perceptual / sRGB (post-gamma)**: Contrast, Curves (Apple's
  CIToneCurve is internally perceptual), Levels, Vignette, Sharpen.

Set the context once:

```swift
let ctx = CIContext(mtlDevice: device, options: [
    .workingColorSpace: CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!,
    .outputColorSpace:  CGColorSpace(name: CGColorSpace.sRGB)!,
    .cacheIntermediates: true,
])
```

Where a sub-pipeline needs sRGB space (Contrast, Curves, Sharpen,
Vignette), bracket the chain with `CIFilter(name: "CIColorSpaceConvert")`
or compose `CIImage.matchedFromWorkingSpace(to: CGColorSpace.sRGB!)`
and back. *Sketched, not verified-compiled.*

---

## 3. Live-preview architecture

**Choice**: `MTKView` + `CIRenderDestination`. Not `NSImageView` —
that path goes CIImage → CGImage → NSImage → AppKit composite, which
forces a CPU readback and breaks the 60 fps target on a 10-MP image.

### Render loop pattern (sketched, not verified-compiled)

```swift
final class AdjustmentMetalView: MTKView {
    private let ciContext: CIContext
    private let commandQueue: MTLCommandQueue
    private let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!

    var ciImage: CIImage? {
        didSet { setNeedsDisplay(bounds) }
    }

    init(device: MTLDevice) {
        self.commandQueue = device.makeCommandQueue()!
        self.ciContext = CIContext(mtlCommandQueue: commandQueue, options: [
            .workingColorSpace: CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!,
            .cacheIntermediates: true,
        ])
        super.init(frame: .zero, device: device)
        self.framebufferOnly = false        // Core Image needs write access
        self.isPaused = true                // draw only when state changes
        self.enableSetNeedsDisplay = true
        self.preferredFramesPerSecond = 60
        self.colorPixelFormat = .bgra8Unorm
    }

    required init(coder: NSCoder) { fatalError() }

    override func draw(_ rect: CGRect) {
        guard let drawable = currentDrawable,
              let image = ciImage,
              let buffer = commandQueue.makeCommandBuffer() else { return }

        // Fit the CIImage into the drawable preserving aspect ratio.
        let drawableSize = CGSize(
            width:  CGFloat(drawable.texture.width),
            height: CGFloat(drawable.texture.height))
        let scale = min(drawableSize.width  / image.extent.width,
                        drawableSize.height / image.extent.height)
        let scaled = image
            .transformed(by: CGAffineTransform(scaleX: scale, y: scale))

        let destination = CIRenderDestination(
            mtlTexture: drawable.texture,
            commandBuffer: buffer)
        destination.isFlipped = false
        destination.colorSpace = colorSpace

        do {
            _ = try ciContext.startTask(toRender: scaled, to: destination)
        } catch {
            assertionFailure("CI render: \(error)")
        }

        buffer.present(drawable)
        buffer.commit()
    }
}
```

Key tricks (sourced from WWDC22 EDR talk + FlexMonkey
`MetalImageView`):

- `isPaused = true` + `enableSetNeedsDisplay = true`: the view only
  redraws when adjustments change, not at 60 fps idle. This drops
  GPU power use to near zero between drags.
- `framebufferOnly = false` is mandatory; otherwise `CIRenderDestination`
  cannot write through the Metal texture.
- `cacheIntermediates: true` lets Core Image keep intermediate
  CIImages from the last frame, so adjusting one slider rebuilds
  only its branch.

### Caching strategy

Core Image is lazy. We don't have to manually cache intermediate
CIImages — but we **do** cache the *input* CIImage and the
*downsampled preview* CIImage:

| Cache key                   | Source of truth                               | Invalidate when                                       |
|----------------------------|-----------------------------------------------|-------------------------------------------------------|
| `sourceCIImage`            | original file URL                             | new image opened                                      |
| `previewCIImage` (1080-px) | sourceCIImage.transformed(scale: previewK)    | new image opened                                      |
| `cropCIImage`              | previewCIImage + CropState                     | crop frame changes                                    |
| `adjustedCIImage`          | apply pipeline(cropCIImage, AdjustmentState)   | any slider value changes                              |

The graph itself is rebuilt per frame; that is cheap (CIFilter setup
is microseconds). Apple's `cacheIntermediates` option is what keeps
the actual pixel work from re-running. (Source: Apple forum thread
698511 on Core Image memory + cacheIntermediates.)

### Preview vs export resolution

- Preview: downsample on open to `min(longSide, 2048 px)`. A 10-MP
  source at 2048 px long side is ~2 megapixels — well within MTKView
  budget for chained CIFilters. Use `CILanczosScaleTransform` once,
  cache result as `previewCIImage`.
- Export: run the same `AdjustmentPipeline` on `sourceCIImage`,
  through `CIContext.writeJPEGRepresentation(of:to:colorSpace:)` or
  `writeHEIFRepresentation(...)`. No MTKView involved.

### GPU vs CPU

Always GPU for preview. `CIContext(mtlDevice:)` enables Metal-backed
kernels. CPU fallback (`CIContext(options: [.useSoftwareRenderer:
true])`) only as a debugging tool — 50× slower on a 10-MP image
(Apple WWDC22 measurements).

### Color space management

- `workingColorSpace`: **extended linear sRGB**. Apple's default and
  the right call for filter math (linear is correct for blends,
  blurs, exposure).
- `outputColorSpace`: **sRGB** for the MTKView (matches `bgra8Unorm`
  pixel format) and **Display P3** for export when source is P3.
- For wide-gamut displays (per Apple forum 66166): set the
  `CAMetalLayer.colorspace` and `pixelFormat = .bgr10a2Unorm` if you
  want P3 in the preview. We can ship sRGB preview first; P3
  preview is a follow-up.

---

## 4. State + undo/redo model

Photos uses **non-destructive editing**: every slider can be reset
individually, and the original is always recoverable. Our model
mirrors that.

### Shape (sketched, not verified-compiled)

```swift
struct AdjustmentState: Equatable, Codable {
    struct Light: Equatable, Codable {
        var brilliance: Double = 0
        var exposure:   Double = 0
        var highlights: Double = 0
        var shadows:    Double = 0
        var brightness: Double = 0
        var contrast:   Double = 0
        var blackPoint: Double = 0
        var sectionEnabled = true
    }
    struct Color: Equatable, Codable {
        var saturation: Double = 0
        var vibrance:   Double = 0
        var cast:       Double = 0
        var sectionEnabled = true
    }
    struct BlackAndWhite: Equatable, Codable {
        var on: Bool = false
        var intensity: Double = 0
        var neutrals:  Double = 0
        var tone:      Double = 0
        var grain:     Double = 0
    }
    struct WhiteBalance: Equatable, Codable {
        enum Mode: String, Codable { case neutralGray, skinTone, temperatureTint }
        var mode: Mode = .temperatureTint
        var temperature: Double = 0   // slider −1…+1
        var tint:        Double = 0
        var eyedropPoint: CGPoint?    // image-space
    }
    struct Curves: Equatable, Codable {
        var master: [CGPoint] = [.zero, CGPoint(x: 0.25, y: 0.25),
                                  CGPoint(x: 0.5, y: 0.5),
                                  CGPoint(x: 0.75, y: 0.75),
                                  CGPoint(x: 1, y: 1)]
        var red:    [CGPoint] = []
        var green:  [CGPoint] = []
        var blue:   [CGPoint] = []
        var smooth: Bool = true
    }
    struct Levels: Equatable, Codable {
        var lumaIn:  ClosedRange<Double> = 0...1
        var lumaOut: ClosedRange<Double> = 0...1
        var gamma:   Double = 1.0
        // … per-channel R/G/B equivalents
    }
    struct Definition: Equatable, Codable {
        var radius:    Double = 0
        var intensity: Double = 0
    }
    struct SelectiveColor: Equatable, Codable {
        enum Swatch: String, CaseIterable, Codable {
            case red, orange, yellow, green, aqua, blue, purple, magenta
        }
        struct HSL: Equatable, Codable { var h = 0.0, s = 0.0, l = 0.0 }
        var values: [Swatch: HSL] = [:]
    }
    struct NoiseReduction: Equatable, Codable {
        var luma: Double = 0; var color: Double = 0; var detail: Double = 0
    }
    struct Sharpen: Equatable, Codable {
        var intensity: Double = 0; var edges: Double = 0; var falloff: Double = 0
    }
    struct Vignette: Equatable, Codable {
        var radius: Double = 0; var intensity: Double = 0; var falloff: Double = 0
    }

    var light = Light()
    var color = Color()
    var bw    = BlackAndWhite()
    var redEye: [CGPoint] = []
    var whiteBalance = WhiteBalance()
    var curves = Curves()
    var levels = Levels()
    var definition = Definition()
    var selective = SelectiveColor()
    var nr = NoiseReduction()
    var sharpen = Sharpen()
    var vignette = Vignette()

    static let neutral = AdjustmentState()
}
```

### Reset semantics

- **Per-slider reset** (Photos: double-click): assign that single
  field back to `AdjustmentState.neutral`'s value. Cheap, doesn't
  touch other fields. The struct's per-slider `Equatable` is what
  lets the UI badge "this section has changes".
- **Per-section reset**: `state.light = AdjustmentState.neutral.light`.
- **Global revert**: `state = AdjustmentState.neutral` (push to undo
  stack first).

### Undo / redo

Snapshot diffing is not worth it — an `AdjustmentState` is a
few-hundred-byte struct. Stack of full copies is fine.

```swift
final class AdjustmentHistory {
    private var stack: [AdjustmentState] = []
    private var cursor: Int = -1
    private let limit = 64

    func commit(_ s: AdjustmentState) {
        if cursor < stack.count - 1 { stack.removeSubrange((cursor+1)...) }
        stack.append(s)
        if stack.count > limit { stack.removeFirst() }
        cursor = stack.count - 1
    }
    func undo() -> AdjustmentState? {
        guard cursor > 0 else { return nil }
        cursor -= 1; return stack[cursor]
    }
    func redo() -> AdjustmentState? {
        guard cursor < stack.count - 1 else { return nil }
        cursor += 1; return stack[cursor]
    }
}
```

Commit policy: debounce 200 ms during a slider drag; commit on
drag end. This avoids 60 snapshots per second.

---

## 5. Histogram + thumbnail rendering

### Live histogram (for Levels backdrop)

Two viable paths:

1. **`CIAreaHistogram` → `CIHistogramDisplayFilter`** — Apple's
   native GPU path. Output is a 1-px-tall histogram from
   `CIAreaHistogram`, then `CIHistogramDisplayFilter` renders it as
   a 2-D image. The cifilter.io and Apple forum (thread 678722)
   confirm this chain. Inputs: `inputCount = 256`, `inputScale =
   50.0`, `inputExtent = image.extent`. Per-channel split: feed
   three permuted CIImages (R, G, B in luma slot).
2. **CPU readback of a downsampled image** — render a 128×128
   version, read pixels, bucket manually. Lower fidelity, more
   flexible (you can render the histogram into SwiftUI's `Canvas`
   with custom styling). Recommended for the editor — the histogram
   only needs to refresh on slider commit, not per drag-frame.

```swift
func histogram(of image: CIImage) -> CIImage {
    let area = CIFilter(name: "CIAreaHistogram", parameters: [
        kCIInputImageKey: image,
        "inputExtent": CIVector(cgRect: image.extent),
        "inputCount":  256,
        "inputScale":  50.0,
    ])!.outputImage!
    return CIFilter(name: "CIHistogramDisplayFilter", parameters: [
        kCIInputImageKey: area,
        "inputHeight":          100.0,
        "inputHighLimit":         1.0,
        "inputLowLimit":          0.0,
    ])!.outputImage!
}
```

*Sketched, not verified-compiled.*

### Filter rail thumbnails

- **Precompute once per source change.** When the user opens an
  image, kick off a background task that takes the
  `previewCIImage` (or even smaller, ~256 px) and renders one
  thumbnail per installed filter through `CIContext.render(...,
  to: CGImage)`.
- Cache them in memory keyed by `(sourceHash, filterID)`. Drop the
  cache when the source changes.
- Re-rendering on every adjustment change is **not** worth it —
  Photos doesn't do it either; the thumbnails are based on the
  source.

---

## 6. Crop + straighten + perspective

### Order of geometric ops

The mathematically clean order is **single composed affine
+ optional perspective**:

```
imageCoord
  → rotate (straighten angle)
  → perspective (horiz keystone + vert keystone, if non-zero)
  → flip (horizontal/vertical)
  → crop (cropRect in post-rotate coords)
```

Where there is no perspective adjustment, **compose rotate + flip
+ crop into one `CIAffineTransform`** to avoid double resampling.
Apple's `CIImage.transformed(by:)` is purely matrix-level; it
defers sampling until the next non-affine filter or render. (objc.io
"Introduction to Core Image" explains the deferred-evaluation
guarantee.)

When perspective IS active, we cannot stay purely affine:

- **`CIPerspectiveTransform`** alters the geometry to simulate the
  observer's viewpoint — fits "vertical perspective" / "horizontal
  perspective" sliders. We pass 4 corner CIVectors, computed from
  the slider angle (±45°) by tilting the top edge in / out.
- **`CIPerspectiveCorrection`** is for the *opposite* use case
  (user picks 4 corners of a tilted rectangle, filter straightens
  it). Not what our sliders want. (Apple Developer Documentation
  + DZone confirm this distinction.)

So:

- Vertical perspective slider `vp ∈ [−45°, +45°]` → top-left and
  top-right CIVectors slide inward by `tan(vp) · imageWidth / 2`.
- Horizontal perspective `hp` → top-right and bottom-right slide.

```swift
func perspectiveTransform(image: CIImage, vp: Double, hp: Double) -> CIImage {
    let w = image.extent.width, h = image.extent.height
    let dxV = CGFloat(tan(vp)) * w / 2
    let dxH = CGFloat(tan(hp)) * h / 2
    let filter = CIFilter(name: "CIPerspectiveTransform")!
    filter.setValue(image, forKey: kCIInputImageKey)
    filter.setValue(CIVector(x: dxV,         y: h),       forKey: "inputTopLeft")
    filter.setValue(CIVector(x: w - dxV,     y: h),       forKey: "inputTopRight")
    filter.setValue(CIVector(x: 0 + dxH,     y: 0),       forKey: "inputBottomLeft")
    filter.setValue(CIVector(x: w - dxH,     y: 0),       forKey: "inputBottomRight")
    return filter.outputImage ?? image
}
```
*Sketched, not verified-compiled. Signs depend on Core Image's
y-up convention.*

### Keeping the crop frame valid

The crop frame is stored in **post-transform** coordinates. When
the user drags the straighten dial, two options:

1. **Clamp the crop frame** to the new post-rotation extent (Photos'
   behavior: the corners pull in as the rotation increases).
2. **Re-fit** the crop frame to the largest inscribed rectangle of
   the rotated image (also Photos'; this is the auto-fit).

Pick (1) for manual edits and (2) on the rotation gesture release.
The largest-inscribed-rectangle math for an angle θ on a `w × h`
image:

```
W' = w·cos|θ| + h·sin|θ|
H' = w·sin|θ| + h·cos|θ|
// inscribed rect inside the rotated bbox preserves aspect:
inscribedW = (w·h) / (h·|cosθ| + w·|sinθ|)  (when w ≥ h, swap otherwise)
```

(Standard derivation; verify when implementing.)

### Single-resample composition

Where possible, build one `CIAffineTransform` chain:

```swift
let t = CGAffineTransform.identity
    .translatedBy(x: image.extent.midX, y: image.extent.midY)
    .rotated(by: straightenAngle)
    .scaledBy(x: flipH ? -1 : 1, y: flipV ? -1 : 1)
    .translatedBy(x: -image.extent.midX, y: -image.extent.midY)
let rotated = image.transformed(by: t)
let cropped = rotated.cropped(to: cropRect)
```

Core Image fuses these to a single resample when rendered. Only the
perspective step (if active) forces a second pass.

---

## 7. Eyedropper for White Balance

### Image-space → screen-space mapping in MTKView

When the MTKView renders a CIImage with `aspectFit` scaling, we
already know the scale factor (`fitScale` from §3). So:

```swift
// view-coord click (x_v, y_v) → CIImage-coord (x_i, y_i)
let x_i = (x_v - offsetX) / fitScale
let y_i = (viewHeight - y_v - offsetY) / fitScale   // CI is y-up
```

`offsetX/Y` are the padding from aspect-fit. Store them on the
view after each layout pass.

### Sampling a pixel

Two sampling strategies:

1. **`CIContext.render(_:toBitmap:rowBytes:bounds:format:colorSpace:)`**
   on a 1×1 region of the *unadjusted, linear* CIImage. Cheap; one
   GPU dispatch. Recommended.
2. **CPU-side `CIImage.cropped(to: CGRect(x: x_i, y: y_i, width: 1,
   height: 1))`** → `CIContext.createCGImage(...)` → read pixel.
   Equivalent; just a different API surface.

```swift
func sample(at p: CGPoint, in image: CIImage,
            context: CIContext) -> SIMD4<Float> {
    var rgba = SIMD4<Float>(repeating: 0)
    let bounds = CGRect(x: p.x, y: p.y, width: 1, height: 1)
    context.render(image,
                   toBitmap: &rgba,
                   rowBytes: 16,
                   bounds: bounds,
                   format: .RGBAf,
                   colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
    return rgba
}
```
*Sketched. `RGBAf` and 16-byte rowBytes are correct per Apple docs.*

### Feeding into CITemperatureAndTint

Given a sampled `(r, g, b)` neutral target, set:

```swift
let wb = CIFilter(name: "CITemperatureAndTint")!
wb.setValue(source,                                    forKey: kCIInputImageKey)
wb.setValue(CIVector(x: cct(from: rgb), y: tint(from: rgb)),
            forKey: "inputNeutral")
wb.setValue(CIVector(x: 6500, y: 0),                   forKey: "inputTargetNeutral")
```

Where `cct(from:)` is McCamy's polynomial approximation on `(r, g,
b)` → chromaticity → CCT. The "Skin Tone" mode swaps the target
neutral to the canonical skin chromaticity instead.

Do **not** re-render the MTKView between sample and apply — the
eyedropper sample must be on the un-white-balanced image so it
produces idempotent results.

---

## Open uncertainties

1. **Photos' actual slider→native math is not public.** Our mappings
   are calibrated to "feel like Photos" but unverified against the
   ground-truth implementation. Plan a manual A/B pass once the
   pipeline ships: load the same image into Photos and our editor,
   set each slider to +0.5, compare histograms.
2. **`CIToneCurve`'s "perceptual gamma 2" claim** — Apple's docs say
   the curve is applied in perceptual space, but they don't expose
   a toggle. If we need a true linear-space curve (e.g. for HDR
   later) we'll have to write a CIKernel.
3. **`CIHighlightShadowAdjust` quality at extreme settings** — known
   to halo. Photos appears to use a custom local-tonemapping kernel
   for its Highlights/Shadows. For v1 the CI filter is acceptable;
   v2 may want a luma-only bilateral version.
4. **`CIVignette` is round-only.** Photos' vignette is elliptical
   when the image is non-square. Custom `CIRadialGradient` × blend
   may be needed.
5. **White-Balance eyedropper math** — McCamy's approximation is
   reasonable but Photos' neutral-gray mode likely uses a fuller
   chromatic adaptation transform (Bradford). Acceptable for v1.
6. **Selective-color band boundaries** — FlexMonkey's smoothstep is
   a known starting point; Photos may use wider overlap. Tune by
   eye in v1.
7. **EDR / wide-gamut preview** — sRGB-only preview is fine for the
   first ship. WWDC22's EDR talk covers the P3 / extended-range
   path when we move there.
8. **`CIRedEyeCorrection` is iOS-leaning.** It exists on macOS but
   the `CIDetector` pipeline behind auto-detect is less tested on
   macOS. Manual click-to-fix is the safer primary UX.

---

Word count: ~3,800.
