import CoreImage
import CoreGraphics
import Foundation

/// Light-section sub-pipeline per `docs/research/047-photos-adjust-light-color-bw.md` §1.
///
/// Order: Highlights+Shadows -> Brilliance composite -> Black Point ->
/// Exposure (all in linear sRGB) -> Brightness+Contrast (sRGB-gamma).
///
/// All coefficients are research-derived empirical starting points; the
/// PR #17 fidelity pass tunes them against side-by-side Photos comparison.
enum LightPipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.Light) -> CIImage {
        guard s.sectionEnabled else { return image }
        // Cheap fast path when section is neutral.
        if s.brilliance == 0 && s.exposure == 0 && s.highlights == 0
            && s.shadows == 0 && s.brightness == 0 && s.contrast == 0
            && s.blackPoint == 0 {
            return image
        }

        var img = ColorSpaces.toLinear(image)

        // Highlights + Shadows share one CIHighlightShadowAdjust instance.
        // Native: inputHighlightAmount ∈ 0…1 (1 = identity), inputShadowAmount
        // ∈ −1…+1 (0 = identity). We pin highlight at 1.0 when slider is 0
        // and pull it down for positive (lift bright detail), use the tone
        // curve below to push it up for negative.
        if s.highlights != 0 || s.shadows != 0 {
            let highlightAmount: Double = 1.0 - 0.5 * max(s.highlights, 0)
            img = img.applyingFilter("CIHighlightShadowAdjust", parameters: [
                "inputHighlightAmount": highlightAmount,
                "inputShadowAmount": s.shadows,
                "inputRadius": 0,
            ])
        }

        // Brilliance: composite of damped HighlightShadow + mid-S tone curve.
        // Coefficients per research §Brilliance: shadow ≈ 0.5·b, highlight pull
        // ≈ −0.3·b, contrast S ≈ 0.15·b. Apple does not publish exact values.
        // TODO: tune in PR #17 fidelity pass.
        if s.brilliance != 0 {
            img = applyBrilliance(img, s.brilliance)
        }

        // Black Point: CIToneCurve point0 shift. Positive crushes the toe
        // (move x right); negative lifts the floor (move y up).
        if s.blackPoint != 0 {
            img = applyBlackPoint(img, s.blackPoint)
        }

        // Exposure: classic EV multiply in scene-linear.
        if s.exposure != 0 {
            img = img.applyingFilter("CIExposureAdjust", parameters: [
                "inputEV": 2.0 * s.exposure,
            ])
        }

        // Brightness + Contrast in sRGB-gamma — Photos' perceptual feel.
        if s.brightness != 0 || s.contrast != 0 {
            img = ColorSpaces.toSRGB(img)
            img = img.applyingFilter("CIColorControls", parameters: [
                "inputBrightness": 0.3 * s.brightness,
                "inputContrast": 1.0 + 0.6 * s.contrast,
                // Saturation untouched — Color section owns it.
                "inputSaturation": 1.0,
            ])
        } else {
            img = ColorSpaces.toSRGB(img)
        }

        return img
    }

    // MARK: - Brilliance composite

    private static func applyBrilliance(_ image: CIImage, _ b: Double) -> CIImage {
        // Leg 1: damped HighlightShadow.
        // Positive brilliance pulls highlights down and lifts shadows;
        // negative brilliance flattens both legs.
        let shadow = 0.5 * b
        let highlight = 1.0 - 0.3 * max(b, 0)
        let withTone = image.applyingFilter("CIHighlightShadowAdjust", parameters: [
            "inputHighlightAmount": highlight,
            "inputShadowAmount": shadow,
            "inputRadius": 0,
        ])

        // Leg 2: mid-S CIToneCurve whose curvature scales with |b|.
        // Anchors pinned at endpoints; midpoint adjusted with a small S
        // around (0.5, 0.5).
        let curvature = 0.15 * abs(b) * (b >= 0 ? 1.0 : -1.0)
        let p1 = CIVector(x: 0.25, y: 0.25 - curvature * 0.5)
        let p2 = CIVector(x: 0.5, y: 0.5)
        let p3 = CIVector(x: 0.75, y: 0.75 + curvature * 0.5)
        return withTone.applyingFilter("CIToneCurve", parameters: [
            "inputPoint0": CIVector(x: 0, y: 0),
            "inputPoint1": p1,
            "inputPoint2": p2,
            "inputPoint3": p3,
            "inputPoint4": CIVector(x: 1, y: 1),
        ])
    }

    // MARK: - Black Point

    private static func applyBlackPoint(_ image: CIImage, _ bp: Double) -> CIImage {
        // Positive bp ∈ (0, 1]: move point0 along x → crush shadows.
        // Negative bp ∈ [−1, 0): move point0 along y → lifted-floor / film
        // look.
        var point0X: Double = 0
        var point0Y: Double = 0
        if bp > 0 {
            point0X = min(0.25, 0.25 * bp)
        } else {
            point0Y = min(0.1, 0.1 * abs(bp))
        }
        return image.applyingFilter("CIToneCurve", parameters: [
            "inputPoint0": CIVector(x: point0X, y: point0Y),
            "inputPoint1": CIVector(x: 0.25, y: 0.25),
            "inputPoint2": CIVector(x: 0.5, y: 0.5),
            "inputPoint3": CIVector(x: 0.75, y: 0.75),
            "inputPoint4": CIVector(x: 1, y: 1),
        ])
    }
}
