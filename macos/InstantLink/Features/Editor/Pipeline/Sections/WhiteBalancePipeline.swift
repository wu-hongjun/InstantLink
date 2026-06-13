import CoreImage
import Foundation

/// White-Balance sub-pipeline per `docs/research/047-photos-adjust-redeye-wb-curves-levels.md`
/// §White Balance and `docs/research/047-implementation-coreimage-mapping.md`
/// §1 rows 17–20.
///
/// Routes the three Photos modes through a single `CITemperatureAndTint`
/// pass:
///
/// - **Temperature & Tint** — sliders feed `inputNeutral` directly
///   (`temp = 6500 + 4000·s.temperature`, `tint = 150·s.tint`); target stays at
///   D65 / 0.
/// - **Neutral Gray** — McCamy's polynomial converts the sampled RGB to a
///   `(CCT, tint)` pair, fed as `inputNeutral`; target stays at D65 / 0.
/// - **Skin Tone** — same source neutral, but `inputTargetNeutral` is the
///   canonical skin reference `(5500 K, 8)` so the sampled pixel maps to a
///   skin-tone-correct white instead of D65.
///
/// Each mode keeps its own parameter set per Photos parity — switching
/// modes does NOT silently re-apply the previous mode's adjustment.
enum WhiteBalancePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.WhiteBalance) -> CIImage {
        guard s.sectionEnabled else { return image }

        switch s.mode {
        case .temperatureTint:
            // Fast path: identity when both sliders are neutral.
            if s.temperature == 0 && s.tint == 0 { return image }
            return image.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral": CIVector(x: 6500 + 4000 * s.temperature, y: 150 * s.tint),
                "inputTargetNeutral": CIVector(x: 6500, y: 0),
            ])

        case .neutralGray:
            guard let sample = s.eyedropSample else { return image }
            let cct = McCamy.estimate(rgb: sample)
            return image.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral": CIVector(x: cct.cct, y: cct.tint),
                "inputTargetNeutral": CIVector(x: 6500, y: 0),
            ])

        case .skinTone:
            guard let sample = s.eyedropSample else { return image }
            let cct = McCamy.estimate(rgb: sample)
            // Canonical skin chromaticity approximation — research §White
            // Balance notes Apple does not publish the exact swatch, so the
            // PR #17 fidelity pass tunes this against Photos behaviour.
            return image.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral": CIVector(x: cct.cct, y: cct.tint),
                "inputTargetNeutral": CIVector(x: 5500, y: 8),
            ])
        }
    }
}
