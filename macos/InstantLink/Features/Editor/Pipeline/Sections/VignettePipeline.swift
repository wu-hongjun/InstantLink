import CoreImage
import CoreGraphics
import Foundation

/// Vignette sub-pipeline per `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §5.
///
/// CIVignette and CIVignetteEffect both clamp `inputIntensity ≥ 0` and only
/// darken — they can't produce a white halo. To honor Photos' bipolar
/// Strength, this routes around them: build a smoothstep-style radial mask
/// via CIRadialGradient (whose alpha ramps with image-diagonal-normalized
/// radius + softness), then CIBlendWithMask onto a constant-color black or
/// white target keyed by the sign of Strength.
///
/// Runs LAST in the pipeline (after crop) — composition already orders it
/// that way in `AdjustmentPipeline.compose`.
enum VignettePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Vignette) -> CIImage {
        guard s.sectionEnabled else { return image }
        if s.strength == 0 { return image }

        let extent = image.extent
        guard extent.width > 0, extent.height > 0 else { return image }

        // Normalize radius to image diagonal. Radius slider 0..1 maps to
        // 0.1..1.0 of half-diagonal so the inner unaffected disc never
        // collapses to a point. Softness 0..1 maps to 0.05..0.55.
        let diagonal = sqrt(extent.width * extent.width + extent.height * extent.height)
        let halfDiag = diagonal / 2
        let radiusPx = CGFloat(0.1 + 0.9 * s.radius) * halfDiag
        let softnessPx = CGFloat(0.05 + 0.5 * s.softness) * halfDiag

        // CIRadialGradient produces a linear alpha ramp between radius0 and
        // radius1. Centered on the image, transparent at radius0 (inner
        // disc), opaque at the outer edge. Final mask alpha scales with
        // |strength| so the slider intensity drives the blend.
        // PR #17 polish can swap the linear ramp for a true Hermite
        // smoothstep curve via a custom CIKernel if needed.
        let center = CIVector(x: extent.midX, y: extent.midY)
        let innerRadius = max(0, radiusPx - softnessPx / 2)
        let outerRadius = max(innerRadius + 1, radiusPx + softnessPx / 2)
        let maskFilter = CIFilter(name: "CIRadialGradient", parameters: [
            "inputCenter": center,
            "inputRadius0": innerRadius,
            "inputRadius1": outerRadius,
            "inputColor0": CIColor(red: 0, green: 0, blue: 0, alpha: 0),
            "inputColor1": CIColor(red: 1, green: 1, blue: 1, alpha: CGFloat(abs(s.strength))),
        ])
        guard let mask = maskFilter?.outputImage?.cropped(to: extent) else {
            return image
        }

        // Target color: black for negative strength (classic vignette),
        // white for positive (halo).
        let target: CIImage
        if s.strength < 0 {
            target = CIImage(color: CIColor.black).cropped(to: extent)
        } else {
            target = CIImage(color: CIColor.white).cropped(to: extent)
        }

        return target.applyingFilter("CIBlendWithMask", parameters: [
            "inputBackgroundImage": image,
            "inputMaskImage": mask,
        ])
    }
}
