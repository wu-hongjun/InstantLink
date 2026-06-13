import CoreImage
import Foundation

/// Noise-Reduction sub-pipeline per `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §3.
///
/// Photos exposes a master Noise Reduction slider plus a RAW v6+ disclosure
/// with Luminance / Color / Detail sub-sliders. For v1 we ship all four
/// always; RAW gating is a follow-up. `master` is the primary luma slider
/// and `luma` mirrors it for future RAW-mode separation — we collapse them
/// here with `max(master, luma)` so either control drives the luma path.
///
/// Order: luma denoise via `CINoiseReduction` (linear sRGB), then chroma
/// denoise via `CIMedianFilter` repeated proportional to the Color slider.
/// `CIMedianFilter` preserves edges and is a reasonable approximation for
/// color noise reduction without writing a full YCbCr decomposition.
/// The Detail slider scales `CINoiseReduction.inputSharpness` so edges are
/// preserved after denoise.
///
/// Pipeline position: runs **before** Sharpen so we don't sharpen noise
/// and then denoise it.
enum NoiseReductionPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.NoiseReduction) -> CIImage {
        guard s.sectionEnabled else { return image }
        // Cheap fast path when section is neutral.
        if s.master == 0 && s.luma == 0 && s.color == 0 {
            return image
        }

        var img = ColorSpaces.toLinear(image)

        // Luma denoise: CINoiseReduction. master and luma both drive this
        // (luma reserved for the future RAW disclosure split); take the max
        // so either slider engages the filter. Detail tunes inputSharpness
        // to preserve edges.
        let effectiveLuma = max(s.master, s.luma)
        if effectiveLuma > 0 {
            img = img.applyingFilter("CINoiseReduction", parameters: [
                "inputNoiseLevel": 0.02 + 0.06 * effectiveLuma,
                "inputSharpness": 0.4 + 1.6 * s.detail,
            ])
        }

        // Color denoise: CIMedianFilter, applied multiple times for stronger
        // effect. CIGaussianBlur on chroma would require YCbCr conversion via
        // CIColorMatrix — for v1, CIMedianFilter (which preserves edges) is a
        // reasonable approximation; PR #17 polish can refine.
        if s.color > 0 {
            let passes = Int(round(s.color * 3)) // 0..3 passes
            for _ in 0..<passes {
                img = img.applyingFilter("CIMedianFilter")
            }
        }

        return ColorSpaces.toSRGB(img)
    }
}
