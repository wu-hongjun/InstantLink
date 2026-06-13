import Foundation

/// McCamy's polynomial approximation of correlated color temperature (CCT)
/// from a sampled sRGB triple.
///
/// Pipeline:
/// 1. sRGB → CIE 1931 XYZ via the standard D65 matrix.
/// 2. XYZ → xy chromaticity.
/// 3. McCamy 1992: `n = (x − 0.3320) / (0.1858 − y)`,
///    `CCT = 437n³ + 3601n² + 6861n + 5517`.
/// 4. Tint approximated as the y-axis offset from the canonical neutral
///    (positive = magenta, negative = green) scaled into Photos'
///    ±150 working range.
///
/// Output is clamped to `(2000…12000 K, −150…+150 tint)` — the envelope
/// `CITemperatureAndTint` accepts before producing visibly broken results.
///
/// Reference: `docs/research/047-implementation-coreimage-mapping.md` §1
/// rows 17–20 + §7 (eyedropper math).
enum McCamy {
    /// Estimate `(CCT, tint)` from a sampled sRGB triple.
    static func estimate(rgb: SampledRGB) -> (cct: Double, tint: Double) {
        let r = rgb.red
        let g = rgb.green
        let b = rgb.blue

        // sRGB → XYZ (D65). Simplified matrix; the overlay samples through
        // a context whose working space is linear sRGB so the input is
        // already linearised.
        let x = 0.4124 * r + 0.3576 * g + 0.1805 * b
        let y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        let z = 0.0193 * r + 0.1192 * g + 0.9505 * b

        let sum = x + y + z
        guard sum > 1e-6 else { return (6500, 0) }

        let cx = x / sum
        let cy = y / sum

        let denom = 0.1858 - cy
        guard abs(denom) > 1e-6 else { return (6500, 0) }
        let n = (cx - 0.3320) / denom
        let cct = 437.0 * n * n * n + 3601.0 * n * n + 6861.0 * n + 5517.0

        // Crude tint estimate: offset from the locus's y baseline,
        // scaled into Photos' working range. Refined in PR #17 fidelity
        // pass against side-by-side Photos comparison.
        let tint = (cy - 0.3320) * 1000.0

        return (
            cct: max(2000.0, min(12000.0, cct)),
            tint: max(-150.0, min(150.0, tint))
        )
    }
}
