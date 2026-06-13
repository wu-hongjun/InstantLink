import CoreImage
import Foundation

/// Black & White sub-pipeline per `docs/research/047-photos-adjust-light-color-bw.md` §3
/// and `docs/research/047-implementation-coreimage-mapping.md` §1 rows 11–14.
///
/// B&W is a mode flag (`on: Bool`), not Saturation = −1. When `on == true`:
///
///   1. Desaturate via `CIColorControls(inputSaturation = 0)` (panchromatic
///      luma weighting); the Color section is already gated off in
///      `ColorPipeline.apply` when `bwOn == true`.
///   2. Apply a combined `CIToneCurve` for Intensity (corner-pull), Tone
///      (mid-S shape), and Neutrals (mid-tone LUMA shift — *not* a hue/tint
///      slider; B&W has no hue-tint in Photos).
///   3. If `grain > 0`, composite a luma-only noise overlay scaled by the
///      Grain amount. Grain is asymmetric (`0..+1`); negative is a no-op.
///
/// All coefficients are research-derived empirical starting points; the
/// PR #17 fidelity pass tunes them against side-by-side Photos comparison.
enum BlackAndWhitePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.BlackAndWhite) -> CIImage {
        // Plan 049 H2: respect `sectionEnabled` like every other pipeline,
        // then the `on` mode flag. Skips when EITHER is off.
        guard s.sectionEnabled, s.on else { return image }

        var img = image.applyingFilter("CIColorControls", parameters: [
            "inputSaturation": 0.0,
            "inputBrightness": 0.0,
            "inputContrast": 1.0,
        ])

        // Combined tone curve for Intensity + Tone + Neutrals.
        // - Intensity: pull endpoints toward the corners on positive (steeper
        //   response, deeper blacks + brighter whites).
        // - Tone: shape a mid-S around the midpoint.
        // - Neutrals: shift the midpoint y up/down (LUMINANCE, not hue).
        let curvature = 0.15 * s.tone
        let neutralsShift = 0.3 * s.neutrals
        let intensityScale = 0.5 * s.intensity
        let p1 = CIVector(x: 0.25, y: 0.25 - curvature * 0.5 - intensityScale * 0.1)
        let p2 = CIVector(x: 0.5, y: 0.5 + neutralsShift)
        let p3 = CIVector(x: 0.75, y: 0.75 + curvature * 0.5 + intensityScale * 0.1)
        img = img.applyingFilter("CIToneCurve", parameters: [
            "inputPoint0": CIVector(x: 0, y: 0),
            "inputPoint1": p1,
            "inputPoint2": p2,
            "inputPoint3": p3,
            "inputPoint4": CIVector(x: 1, y: 1),
        ])

        // Grain (asymmetric 0..+1).
        if s.grain > 0 {
            img = composeGrain(over: img, amount: s.grain)
        }

        return img
    }

    // MARK: - Grain composite

    private static func composeGrain(over base: CIImage, amount: Double) -> CIImage {
        let extent = base.extent
        guard extent.width > 0, extent.height > 0 else { return base }
        let noise = CIFilter(name: "CIRandomGenerator")?.outputImage ?? base

        // Extract luminance (Rec.601 luma weights) and scale alpha by `amount`
        // so stronger Grain produces a denser overlay.
        let lumaScale = CIVector(x: 0.299, y: 0.587, z: 0.114, w: 0)
        let alphaScale = CIVector(x: 0, y: 0, z: 0, w: amount)
        let grayNoise = noise.applyingFilter("CIColorMatrix", parameters: [
            "inputRVector": lumaScale,
            "inputGVector": lumaScale,
            "inputBVector": lumaScale,
            "inputAVector": alphaScale,
            "inputBiasVector": CIVector(x: 0, y: 0, z: 0, w: 0),
        ]).cropped(to: extent)

        let blurred = grayNoise.applyingFilter("CIGaussianBlur", parameters: [
            "inputRadius": 0.5 + 0.5 * amount,
        ]).cropped(to: extent)

        return blurred.composited(over: base)
    }
}
