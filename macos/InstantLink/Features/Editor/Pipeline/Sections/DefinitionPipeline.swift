import CoreImage
import Foundation

/// Definition-section sub-pipeline per `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §1.
///
/// Locked decision Q7: single slider + Auto (Photos parity, not Lightroom's
/// Radius + Intensity). The internal radius is fixed at ~2% of the image's
/// short edge, so the user only adjusts the amount.
///
/// Approach: high-radius / low-amount unsharp mask for the local-contrast
/// boost, then composited back over the original via a luminance-derived
/// midtone mask (tent function via `CIToneCurve` peaking at L = 0.5).
/// This suppresses the effect in shadows and highlights so the slider
/// doesn't crush blacks or blow out whites — matches Lightroom Clarity
/// behavior, which Photos' Definition mirrors.
enum DefinitionPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Definition) -> CIImage {
        guard s.sectionEnabled, s.amount > 0 else { return image }
        let extent = image.extent
        guard extent.width > 0, extent.height > 0 else { return image }

        // Internal radius = ~2% of the short edge per locked decision Q7.
        let radius = 0.02 * min(extent.width, extent.height)

        // High-radius / low-amount unsharp mask.
        let boosted = image.applyingFilter("CIUnsharpMask", parameters: [
            "inputRadius": radius,
            "inputIntensity": 0.15 * s.amount,
        ])

        // Midtone mask: tent function m(L) = 1 - |2L - 1|, approximated via
        // a CIToneCurve that peaks at L = 0.5 and falls to 0 at L = 0 and
        // L = 1. CIColorControls with saturation 0 first collapses RGB to
        // luminance so the curve maps brightness → mask alpha.
        let midtoneMask = boosted
            .applyingFilter("CIColorControls", parameters: ["inputSaturation": 0.0])
            .applyingFilter("CIToneCurve", parameters: [
                "inputPoint0": CIVector(x: 0.0,  y: 0.0),
                "inputPoint1": CIVector(x: 0.25, y: 0.5),
                "inputPoint2": CIVector(x: 0.5,  y: 1.0),
                "inputPoint3": CIVector(x: 0.75, y: 0.5),
                "inputPoint4": CIVector(x: 1.0,  y: 0.0),
            ])

        // Blend the boosted image over the original via the midtone mask.
        return boosted.applyingFilter("CIBlendWithMask", parameters: [
            "inputBackgroundImage": image,
            "inputMaskImage": midtoneMask,
        ])
    }
}
