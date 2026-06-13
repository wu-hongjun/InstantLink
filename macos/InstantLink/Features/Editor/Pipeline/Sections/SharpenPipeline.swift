import CoreImage
import Foundation

/// Sharpen sub-pipeline per `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §4.
///
/// Uses CISharpenLuminance (luma-only) as the base — Photos never applies
/// chroma sharpening on edges, which is why their result is grain-free in
/// flat areas. Edges drives a CIEdges + CIGaussianBlur threshold mask that
/// blends the sharpened result back over the original where local variance
/// is high, so flat regions (sky, skin) stay clean. Falloff maps to the
/// CISharpenLuminance inputRadius — Photos doesn't expose radius directly.
///
/// All coefficients are research-derived empirical starting points; the
/// PR #17 fidelity pass tunes them against side-by-side Photos comparison.
enum SharpenPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Sharpen) -> CIImage {
        guard s.sectionEnabled, s.intensity > 0 else { return image }

        // CISharpenLuminance defaults: inputSharpness 0.4, inputRadius ~1.69.
        // We scale intensity to 0..2 so the slider's top end is visibly
        // sharper than the filter default without over-sharpening.
        let radius = 0.5 + 2.0 * s.falloff
        let sharpened = image.applyingFilter("CISharpenLuminance", parameters: [
            "inputSharpness": 2.0 * s.intensity,
            "inputRadius": radius,
        ])

        // Edges threshold mask: only sharpen where local luma variance is
        // high. CIEdges produces a high-luma map where edges are; blurring
        // it gives a soft mask. CIBlendWithMask uses the mask alpha — high
        // mask ⇒ foreground (sharpened) shows through; low mask ⇒ original.
        // PR #17 polish refines (likely a real luma-variance kernel).
        if s.edges > 0 {
            let edgeMask = image
                .applyingFilter("CIEdges", parameters: ["inputIntensity": 1.0])
                .applyingFilter("CIGaussianBlur", parameters: ["inputRadius": 4.0])
            return sharpened.applyingFilter("CIBlendWithMask", parameters: [
                "inputBackgroundImage": image,
                "inputMaskImage": edgeMask,
            ])
        }
        return sharpened
    }
}
