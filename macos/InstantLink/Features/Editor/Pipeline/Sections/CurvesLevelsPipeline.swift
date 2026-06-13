import CoreGraphics
import CoreImage
import Foundation

/// Curves + Levels composite — plan 048 PR #5.
///
/// Strategy: bake the user's spline curves AND the per-channel Levels transfer
/// function into a single 256-sample `CIColorCurves` LUT per channel and ship
/// it through one GPU pass. The combined transfer for each channel `c ∈ {R,G,B}`
/// at input `x ∈ [0, 1]` is:
///
///   1. Apply the per-channel Levels (R / G / B) transfer.
///   2. Apply the RGB Levels transfer (acts on all three channels).
///   3. Apply Luminance Levels via a luma-preserving rescale on the result.
///   4. Compose the per-channel Curves spline.
///   5. Compose the RGB / master Curves spline.
///
/// All five passes are folded into one 256-entry RGB LUT and pushed through
/// `CIColorCurves` for a single-pass execution.
enum CurvesLevelsPipeline {

    /// LUT resolution. 256 is the sweet spot — bigger doesn't reduce banding
    /// once the spline is monotone, smaller introduces visible quantization.
    private static let lutResolution = 256

    static func apply(_ image: CIImage,
                      curves: AdjustmentState.Curves,
                      levels: AdjustmentState.Levels) -> CIImage {
        guard curves.sectionEnabled || levels.sectionEnabled else { return image }
        let curvesActive = curves.sectionEnabled && !curvesAllIdentity(curves)
        let levelsActive = levels.sectionEnabled && !levels.isNeutral
        guard curvesActive || levelsActive else { return image }

        // Build per-component lookup tables for the active stack.
        var lutR = [Float](repeating: 0, count: lutResolution)
        var lutG = [Float](repeating: 0, count: lutResolution)
        var lutB = [Float](repeating: 0, count: lutResolution)

        // Pre-evaluate the spline samplers once.
        let masterSpline = curvesActive ? MonotoneSpline(points: curves.master) : nil
        let redSpline    = curvesActive ? MonotoneSpline(points: curves.red)    : nil
        let greenSpline  = curvesActive ? MonotoneSpline(points: curves.green)  : nil
        let blueSpline   = curvesActive ? MonotoneSpline(points: curves.blue)   : nil

        let lumLevels = levelsActive ? levels.channels[.luminance] : nil
        let rgbLevels = levelsActive ? levels.channels[.rgb]       : nil
        let rLevels   = levelsActive ? levels.channels[.red]       : nil
        let gLevels   = levelsActive ? levels.channels[.green]     : nil
        let bLevels   = levelsActive ? levels.channels[.blue]      : nil

        for i in 0..<lutResolution {
            let t = Double(i) / Double(lutResolution - 1)

            // We treat the LUT as feeding the same `t` into all three
            // channels, then sequencing per-channel transforms. The luminance
            // pass is handled approximately on the LUT diagonal — the GPU LUT
            // path is per-pixel-independent, so true luma preservation lives
            // in a follow-up. For now the luminance handles act as a
            // global-channel response identical to RGB.
            var r = t
            var g = t
            var b = t

            // 1. Per-channel Levels.
            if let l = rLevels { r = applyLevels(r, l) }
            if let l = gLevels { g = applyLevels(g, l) }
            if let l = bLevels { b = applyLevels(b, l) }

            // 2. RGB Levels (applied to each channel).
            if let l = rgbLevels {
                r = applyLevels(r, l)
                g = applyLevels(g, l)
                b = applyLevels(b, l)
            }

            // 3. Luminance Levels (per-channel approximation in the LUT path).
            if let l = lumLevels {
                r = applyLevels(r, l)
                g = applyLevels(g, l)
                b = applyLevels(b, l)
            }

            // 4. Per-channel Curves spline.
            if let s = redSpline   { r = s.evaluate(r) }
            if let s = greenSpline { g = s.evaluate(g) }
            if let s = blueSpline  { b = s.evaluate(b) }

            // 5. Master / RGB Curves spline.
            if let s = masterSpline {
                r = s.evaluate(r)
                g = s.evaluate(g)
                b = s.evaluate(b)
            }

            lutR[i] = Float(max(0.0, min(1.0, r)))
            lutG[i] = Float(max(0.0, min(1.0, g)))
            lutB[i] = Float(max(0.0, min(1.0, b)))
        }

        var packed = [Float](repeating: 0, count: lutResolution * 3)
        for i in 0..<lutResolution {
            packed[i * 3 + 0] = lutR[i]
            packed[i * 3 + 1] = lutG[i]
            packed[i * 3 + 2] = lutB[i]
        }
        let data = packed.withUnsafeBufferPointer { Data(buffer: $0) }
        let filter = CIFilter(name: "CIColorCurves") ?? CIFilter(name: "CIColorCurves")
        guard let filter else { return image }
        filter.setValue(image, forKey: kCIInputImageKey)
        filter.setValue(data, forKey: "inputCurvesData")
        filter.setValue(CIVector(x: 0, y: 1), forKey: "inputCurvesDomain")
        filter.setValue(CGColorSpaceCreateDeviceRGB(), forKey: "inputColorSpace")
        return filter.outputImage ?? image
    }

    // MARK: - Levels transfer

    /// Photoshop-style Levels transfer for one channel value `v ∈ [0, 1]`:
    /// input clamp + stretch, midtone gamma, then output remap. The
    /// shadows/highlights handles bias the gamma curvature.
    static func applyLevels(_ v: Double, _ l: AdjustmentState.Levels.ChannelLevels) -> Double {
        let blackIn = min(max(l.blackIn, 0.0), 0.999)
        let whiteIn = max(blackIn + 1e-3, min(l.whiteIn, 1.0))
        // Stage 1: input clamp + stretch.
        var t = (v - blackIn) / (whiteIn - blackIn)
        if t < 0 { t = 0 } else if t > 1 { t = 1 }
        // Stage 2: shadows / highlights shaping. Map the inflection points
        // (which live in input-domain coords) into the stretched domain and
        // pull the toe / shoulder toward them with a piecewise mix.
        let shadowsT = clamp01((l.shadows - blackIn) / (whiteIn - blackIn))
        let highlightsT = clamp01((l.highlights - blackIn) / (whiteIn - blackIn))
        let shadowDelta = shadowsT - 0.25
        let highlightDelta = highlightsT - 0.75
        // Subtle nudge — keep the diagonal recognisable when handles sit at
        // their defaults (delta == 0 means no change).
        let shadowBias = shadowDelta * (1 - t) * t * 4
        let highlightBias = highlightDelta * t * (1 - t) * 4
        t = clamp01(t - shadowBias - highlightBias)
        // Stage 3: midtone gamma (Photoshop direction: > 1 = brighter mids).
        let gamma = max(0.1, min(9.99, l.gamma))
        t = pow(t, 1.0 / gamma)
        // Stage 4: output remap.
        let blackOut = clamp01(l.blackOut)
        let whiteOut = clamp01(l.whiteOut)
        return blackOut + t * (whiteOut - blackOut)
    }

    private static func clamp01(_ x: Double) -> Double {
        x < 0 ? 0 : (x > 1 ? 1 : x)
    }

    // MARK: - Curves identity check

    private static func curvesAllIdentity(_ c: AdjustmentState.Curves) -> Bool {
        isIdentity(c.master) && isIdentity(c.red) && isIdentity(c.green) && isIdentity(c.blue)
    }

    private static func isIdentity(_ points: [CGPoint]) -> Bool {
        guard !points.isEmpty else { return true }
        for p in points where abs(p.x - p.y) > 1e-6 {
            return false
        }
        return true
    }
}

// MARK: - Monotone cubic Hermite spline

/// Monotone cubic Hermite spline through a sorted set of `(x, y)` knots in
/// `[0, 1] × [0, 1]`. Uses the Fritsch–Carlson tangent construction so the
/// resulting curve is guaranteed to be monotone wherever the data is.
///
/// The spline is clamped (constant extrapolation) outside the knot domain
/// per the Photos behaviour documented in research 047.
struct MonotoneSpline {
    private let xs: [Double]
    private let ys: [Double]
    private let m: [Double]

    init(points: [CGPoint]) {
        // Defensive: dedup x, sort, clamp to [0, 1].
        let sorted = points.sorted { $0.x < $1.x }
        var rawX: [Double] = []
        var rawY: [Double] = []
        for p in sorted {
            let x = max(0.0, min(1.0, Double(p.x)))
            let y = max(0.0, min(1.0, Double(p.y)))
            if let last = rawX.last, x - last < 1e-4 { continue }
            rawX.append(x)
            rawY.append(y)
        }
        if rawX.isEmpty {
            rawX = [0, 1]; rawY = [0, 1]
        } else if rawX.count == 1 {
            rawX.insert(0, at: 0); rawY.insert(rawY[0], at: 0)
            rawX.append(1); rawY.append(rawY.last!)
        }
        self.xs = rawX
        self.ys = rawY
        self.m = MonotoneSpline.tangents(xs: rawX, ys: rawY)
    }

    /// Evaluate the spline at `x`, clamped to the knot domain.
    func evaluate(_ x: Double) -> Double {
        guard xs.count >= 2 else { return ys.first ?? x }
        if x <= xs.first! { return ys.first! }
        if x >= xs.last!  { return ys.last! }
        // Binary search for the segment.
        var lo = 0, hi = xs.count - 1
        while hi - lo > 1 {
            let mid = (lo + hi) >> 1
            if xs[mid] <= x { lo = mid } else { hi = mid }
        }
        let h = xs[hi] - xs[lo]
        let t = (x - xs[lo]) / h
        let t2 = t * t
        let t3 = t2 * t
        let h00 =  2 * t3 - 3 * t2 + 1
        let h10 =      t3 - 2 * t2 + t
        let h01 = -2 * t3 + 3 * t2
        let h11 =      t3 -     t2
        return h00 * ys[lo] + h10 * h * m[lo] + h01 * ys[hi] + h11 * h * m[hi]
    }

    private static func tangents(xs: [Double], ys: [Double]) -> [Double] {
        let n = xs.count
        guard n >= 2 else { return [0] }
        var d = [Double](repeating: 0, count: n - 1)
        for i in 0..<(n - 1) {
            d[i] = (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
        }
        var m = [Double](repeating: 0, count: n)
        m[0] = d[0]
        m[n - 1] = d[n - 2]
        for i in 1..<(n - 1) {
            if d[i - 1] * d[i] <= 0 {
                m[i] = 0
            } else {
                m[i] = (d[i - 1] + d[i]) * 0.5
            }
        }
        // Fritsch–Carlson monotone correction.
        for i in 0..<(n - 1) {
            if d[i] == 0 {
                m[i] = 0
                m[i + 1] = 0
            } else {
                let a = m[i]     / d[i]
                let b = m[i + 1] / d[i]
                let h = hypot(a, b)
                if h > 3 {
                    let k = 3 / h
                    m[i]     = k * a * d[i]
                    m[i + 1] = k * b * d[i]
                }
            }
        }
        return m
    }
}
