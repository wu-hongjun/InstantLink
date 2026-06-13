import CoreImage
import Foundation

/// Selective Color custom CIColorKernel — plan 048 PR #10.
///
/// Per-pixel HSL conversion + raised-cosine hue-band weighting across up to
/// 6 user-defined wells; per-well Δhue / Δsat / Δlum are summed (weighted by
/// each well's `cos(π/2 · r)²` falloff inside its `range`-derived band), then
/// the modified HSL is converted back to RGB.
///
/// v1 implementation uses the CI Kernel Language source string form
/// (`CIColorKernel(source:)`) so we don't have to extend `scripts/build-app.sh`
/// with a `metal -fcikernel` + `metallib -cikernel` pass. PR #17 polish:
/// migrate this to a pre-compiled `.ci.metallib` for performance and tune
/// the raised-cosine band edges against side-by-side Photos comparison.
///
/// Reference: FlexMonkey selective HSL kernel pattern + research file
/// `docs/research/047-photos-adjust-def-sel-nr-sharp-vignette.md` §2 and
/// `docs/research/047-implementation-coreimage-mapping.md` row 27 "Path A".
enum SelectiveColorKernel {

    // MARK: - Kernel source (CI Kernel Language)

    private static let kernelSource: String = """
    kernel vec4 selectiveColor(__sample input,
                               vec4 wellSeed0, vec4 wellSeed1, vec4 wellSeed2,
                               vec4 wellSeed3, vec4 wellSeed4, vec4 wellSeed5,
                               vec4 wellDelta0, vec4 wellDelta1, vec4 wellDelta2,
                               vec4 wellDelta3, vec4 wellDelta4, vec4 wellDelta5)
    {
        // ---- RGB -> HSL ----------------------------------------------------
        float r = input.r;
        float g = input.g;
        float b = input.b;
        float maxC = max(r, max(g, b));
        float minC = min(r, min(g, b));
        float L = (maxC + minC) * 0.5;
        float H = 0.0;
        float S = 0.0;
        float d = maxC - minC;
        if (d > 1.0e-5) {
            S = (L > 0.5) ? (d / (2.0 - maxC - minC)) : (d / (maxC + minC));
            if (maxC == r) {
                H = (g - b) / d + (g < b ? 6.0 : 0.0);
            } else if (maxC == g) {
                H = (b - r) / d + 2.0;
            } else {
                H = (r - g) / d + 4.0;
            }
            H /= 6.0;
        }

        // ---- Accumulate weighted Δhue/Δsat/Δlum across 6 wells -------------
        vec3 delta = vec3(0.0, 0.0, 0.0);
        float wsum = 0.0;

        // Inline each well — CI Kernel Language doesn't support for-loops
        // over uniforms cleanly; unrolling is the canonical pattern.
        // wellSeedN = (seedHue, band, _, hasSeed:0|1)
        // wellDeltaN = (Δhue, Δsat, Δlum, _)
        #define APPLY_WELL(SEED, DELTA) \\
            if (SEED.w > 0.5) { \\
                float dh = H - SEED.x; \\
                dh -= floor(dh + 0.5); \\
                float r2 = abs(dh) / max(SEED.y, 1.0e-4); \\
                if (r2 < 1.0) { \\
                    float cw = cos(r2 * 1.57079632679); \\
                    float w = cw * cw; \\
                    if (S < 0.05) { w *= S / 0.05; } \\
                    delta += w * vec3(DELTA.x, DELTA.y, DELTA.z); \\
                    wsum += w; \\
                } \\
            }

        APPLY_WELL(wellSeed0, wellDelta0)
        APPLY_WELL(wellSeed1, wellDelta1)
        APPLY_WELL(wellSeed2, wellDelta2)
        APPLY_WELL(wellSeed3, wellDelta3)
        APPLY_WELL(wellSeed4, wellDelta4)
        APPLY_WELL(wellSeed5, wellDelta5)

        if (wsum > 1.0e-4) {
            delta /= max(1.0, wsum);
        }

        float outH = H + delta.x * 0.2;
        float outS = clamp(S * (1.0 + delta.y), 0.0, 1.0);
        float outL = clamp(L + delta.z * 0.5, 0.0, 1.0);
        outH = outH - floor(outH);

        // ---- HSL -> RGB ----------------------------------------------------
        vec3 outRgb;
        if (outS < 1.0e-5) {
            outRgb = vec3(outL, outL, outL);
        } else {
            float q = (outL < 0.5) ? (outL * (1.0 + outS)) : (outL + outS - outL * outS);
            float p = 2.0 * outL - q;
            // hue2rgb inline for each channel.
            float tR = outH + 1.0 / 3.0;
            float tG = outH;
            float tB = outH - 1.0 / 3.0;
            tR = tR - floor(tR);
            tG = tG - floor(tG);
            tB = tB - floor(tB);
            float cR, cG, cB;
            if (tR < 1.0 / 6.0)      cR = p + (q - p) * 6.0 * tR;
            else if (tR < 0.5)       cR = q;
            else if (tR < 2.0 / 3.0) cR = p + (q - p) * (2.0 / 3.0 - tR) * 6.0;
            else                     cR = p;
            if (tG < 1.0 / 6.0)      cG = p + (q - p) * 6.0 * tG;
            else if (tG < 0.5)       cG = q;
            else if (tG < 2.0 / 3.0) cG = p + (q - p) * (2.0 / 3.0 - tG) * 6.0;
            else                     cG = p;
            if (tB < 1.0 / 6.0)      cB = p + (q - p) * 6.0 * tB;
            else if (tB < 0.5)       cB = q;
            else if (tB < 2.0 / 3.0) cB = p + (q - p) * (2.0 / 3.0 - tB) * 6.0;
            else                     cB = p;
            outRgb = vec3(cR, cG, cB);
        }

        return vec4(outRgb, input.a);
    }
    """

    // MARK: - Compiled kernel (lazy)

    private static let kernel: CIColorKernel? = {
        CIColorKernel(source: kernelSource)
    }()

    // MARK: - Apply

    /// Compose the Selective Color pass on top of `image`. Returns `image`
    /// unchanged when the section is disabled, no wells have a seed, or the
    /// kernel failed to compile (defensive — should not happen at runtime).
    static func apply(_ image: CIImage, _ state: AdjustmentState.SelectiveColor) -> CIImage {
        guard state.sectionEnabled, let kernel else { return image }
        guard state.wells.contains(where: { $0.seed != nil && !isWellNeutral($0) }) else {
            return image
        }

        var seeds: [CIVector] = []
        var deltas: [CIVector] = []
        seeds.reserveCapacity(AdjustmentState.SelectiveColor.maxWells)
        deltas.reserveCapacity(AdjustmentState.SelectiveColor.maxWells)

        // Pad / truncate to exactly maxWells so the kernel always gets six
        // (seed, delta) pairs.
        for i in 0..<AdjustmentState.SelectiveColor.maxWells {
            let well = i < state.wells.count ? state.wells[i] : AdjustmentState.SelectiveColor.Well()
            if let seed = well.seed {
                let hsl = rgbToHSL(r: seed.red, g: seed.green, b: seed.blue)
                let band = max(0.05, well.range * 0.5)
                seeds.append(CIVector(x: CGFloat(hsl.h), y: CGFloat(band), z: 0, w: 1))
            } else {
                seeds.append(CIVector(x: 0, y: 0, z: 0, w: 0))
            }
            deltas.append(CIVector(
                x: CGFloat(well.hue),
                y: CGFloat(well.saturation),
                z: CGFloat(well.luminance),
                w: 0
            ))
        }

        let args: [Any] = [image] + seeds + deltas
        return kernel.apply(extent: image.extent, arguments: args) ?? image
    }

    // MARK: - Helpers

    private static func isWellNeutral(_ well: AdjustmentState.SelectiveColor.Well) -> Bool {
        well.hue == 0 && well.saturation == 0 && well.luminance == 0
    }

    /// Standard RGB -> HSL. Mirrors the kernel's per-pixel conversion so the
    /// seed picker and the pixel weighting agree.
    static func rgbToHSL(r: Double, g: Double, b: Double) -> (h: Double, s: Double, l: Double) {
        let maxC = max(r, g, b)
        let minC = min(r, g, b)
        let L = (maxC + minC) * 0.5
        let d = maxC - minC
        guard d > 1e-5 else { return (0, 0, L) }
        let S = L > 0.5 ? d / (2 - maxC - minC) : d / (maxC + minC)
        var H: Double
        if maxC == r {
            H = (g - b) / d + (g < b ? 6 : 0)
        } else if maxC == g {
            H = (b - r) / d + 2
        } else {
            H = (r - g) / d + 4
        }
        H /= 6
        return (H, S, L)
    }
}
