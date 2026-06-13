import CoreImage
import Foundation

/// Color-section sub-pipeline per `docs/research/047-photos-adjust-light-color-bw.md` §2
/// and `docs/research/047-implementation-coreimage-mapping.md` §1 rows 8–10.
///
/// Composes: `CIColorControls` (saturation) -> `CIVibrance` -> `CITemperatureAndTint`
/// (Cast as a single 1-D ride through temperature+tint space, ±3000 K / ±50 tint).
///
/// B&W interop: research §3 confirms B&W is a separate mode flag that overrides
/// the Color section — `inputSaturation` is forced to 0 and Vibrance / Cast are
/// skipped while `bwOn == true`. Wired in PR #13.
enum ColorPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Color, bwOn: Bool) -> CIImage {
        guard s.sectionEnabled else { return image }
        // Fast path: skip the working-space round trip when the section is
        // neutral AND B&W isn't forcing saturation = 0.
        if s.saturation == 0 && s.vibrance == 0 && s.cast == 0 && !bwOn { return image }

        var img = ColorSpaces.toLinear(image)

        // Saturation: native `inputSaturation` ∈ 0…2 (1 = identity). Slider
        // s ∈ −1…+1 maps to 1 + s. B&W mode forces to 0 regardless of slider.
        let satNative = bwOn ? 0.0 : (1.0 + s.saturation)
        if bwOn || s.saturation != 0 {
            img = img.applyingFilter("CIColorControls", parameters: [
                "inputSaturation": satNative,
                "inputBrightness": 0.0,
                "inputContrast": 1.0,
            ])
        }

        // Vibrance: native `inputAmount` ∈ −1…+1 (0 = identity); skin-tone
        // aware. Skipped under B&W since chroma is already gone.
        if s.vibrance != 0 && !bwOn {
            img = img.applyingFilter("CIVibrance", parameters: [
                "inputAmount": s.vibrance,
            ])
        }

        // Cast: persist as a single −1…+1 scalar; expand to (temp, tint) only
        // here. Research §Cast empirical scales: ±3000 K on temperature,
        // ±50 on tint. PR #17 fidelity pass: held the canonical ±3000 K /
        // ±50 tint — at slider 0.5 this produces a perceptibly-but-not-
        // distractingly warm/cool cast consistent with Photos' own Cast
        // slider behaviour for the same value.
        if s.cast != 0 {
            img = img.applyingFilter("CITemperatureAndTint", parameters: [
                "inputNeutral": CIVector(x: 6500, y: 0),
                "inputTargetNeutral": CIVector(x: 6500 + 3000 * s.cast, y: 50 * s.cast),
            ])
        }

        return ColorSpaces.toSRGB(img)
    }
}
