import CoreGraphics
import CoreImage
import Foundation
import Vision

/// Photos-style "Auto" / global Enhance facade — plan 048 PR #16.
///
/// Calls `CIImage.autoAdjustmentFilters(options:)` to ask the system analyzer
/// what it would do to the image, then folds the returned `CIFilter` chain's
/// inputs back into our `AdjustmentState`. Replaces the v1 placeholder presets
/// each section was wired with in PRs #3–#11.
///
/// Targets line up with Photos' UI surfaces:
/// - `.light` / `.color` / `.blackWhite` / `.levels` / `.curves` / `.definition`
///   / `.redEye` — wired to each Adjust section's Auto button.
/// - `.global` — bound to the magic-wand toolbar button in `EditorShell`;
///   applies every section's Auto in one call (matches the top-level Photos
///   Enhance button).
///
/// Coefficient mapping from CI filter inputs to our [-1, +1] slider domain is
/// calibrated to "feel like Photos". PR #17 (fidelity pass) refines against a
/// side-by-side Photos comparison.
enum AutoEnhance {
    enum Target {
        case light
        case color
        case blackWhite
        case levels
        case curves
        case definition
        case redEye
        case global
    }

    /// Apply auto-adjustment of `target` to the given image, writing slider
    /// values back into `state.adjustments`. Safe to call on the main actor —
    /// `autoAdjustmentFilters` is a synchronous analyzer call.
    @MainActor
    static func apply(target: Target, image: CIImage, state: EditorViewState) {
        let wantsEnhance = target.usesEnhanceFilters
        let wantsRedEye = target.usesRedEyeFilters

        let options: [CIImageAutoAdjustmentOption: Any] = [
            .enhance: wantsEnhance,
            .redEye: wantsRedEye,
        ]
        let filters = image.autoAdjustmentFilters(options: options)

        for filter in filters {
            applyFilter(filter, target: target, state: state)
        }

        // Sections without a corresponding CIImage analyzer filter — derive
        // sensible Auto values from a fixed preset (matches plan 048 PR #16
        // sketch). PR #17 tunes these against Photos side-by-side.
        if target == .blackWhite || target == .global {
            applyBlackWhitePreset(state: state)
        }
        if target == .definition || target == .global {
            applyDefinitionPreset(state: state)
        }
    }

    // MARK: - Per-filter folding

    @MainActor
    private static func applyFilter(_ filter: CIFilter, target: Target, state: EditorViewState) {
        switch filter.name {
        case "CIVibrance":
            guard target.affectsColor else { return }
            if let amount = filter.value(forKey: "inputAmount") as? Double {
                state.adjustments.color.vibrance = clamp(amount)
            } else if let amount = filter.value(forKey: "inputAmount") as? NSNumber {
                state.adjustments.color.vibrance = clamp(amount.doubleValue)
            }

        case "CITemperatureAndTint":
            guard target.affectsColor else { return }
            // CITemperatureAndTint exposes `inputNeutral` and
            // `inputTargetNeutral` as CIVectors (x=temperature K, y=tint).
            // Map the delta between them to our [-1, +1] cast slider so the
            // Auto produces a perceptible warm/cool nudge.
            if let neutral = filter.value(forKey: "inputNeutral") as? CIVector,
               let target_ = filter.value(forKey: "inputTargetNeutral") as? CIVector {
                let deltaTemp = target_.x - neutral.x
                // Photos' auto WB typically nudges +/- a few hundred K. Map a
                // 1000 K delta to a full-scale cast = 1.
                let cast = clamp(Double(deltaTemp) / 1000.0)
                state.adjustments.color.cast = cast
            }

        case "CIHighlightShadowAdjust":
            guard target.affectsLight else { return }
            if let h = filter.value(forKey: "inputHighlightAmount") as? Double {
                // Filter input 0…1 (1 = no change). Map below 1 to a
                // highlight pull-down on our [-1, +1] slider.
                state.adjustments.light.highlights = clamp(h - 1.0)
            }
            if let s = filter.value(forKey: "inputShadowAmount") as? Double {
                // Filter input 0…1 (0 = no change). Map directly to a
                // shadow lift on our [-1, +1] slider.
                state.adjustments.light.shadows = clamp(s)
            }

        case "CIToneCurve":
            applyToneCurve(filter, target: target, state: state)

        case "CIRedEyeCorrection":
            guard target.affectsRedEye else { return }
            if let centers = filter.value(forKey: "inputCenters") as? [CIVector] {
                let radius = state.adjustments.redEye.size
                let appended = centers.map { v in
                    AdjustmentState.RedEyeCorrection(
                        point: CGPoint(x: CGFloat(v.x), y: CGFloat(v.y)),
                        radius: radius
                    )
                }
                state.adjustments.redEye.corrections.append(contentsOf: appended)
            }

        default:
            break
        }
    }

    /// CIToneCurve carries 5 control points (`inputPoint0`…`inputPoint4`).
    /// Depending on `target`, fold them into Light (mid-tone lift), Levels
    /// (input black / white from end-points), and/or Curves (master spline).
    @MainActor
    private static func applyToneCurve(_ filter: CIFilter, target: Target, state: EditorViewState) {
        guard target.affectsLight || target.affectsLevels || target.affectsCurves else { return }

        let points = (0..<5).compactMap { idx -> CIVector? in
            filter.value(forKey: "inputPoint\(idx)") as? CIVector
        }
        guard points.count == 5 else { return }

        if target.affectsLight {
            // Midpoint y offset from 0.5 = midtone lift / pull.
            let lift = Double(points[2].y) - 0.5
            state.adjustments.light.brightness = clamp(lift * 2.0)
            // End-point spread = contrast hint.
            let blackY = Double(points[0].y)
            let whiteY = Double(points[4].y)
            let contrastDelta = (whiteY - blackY) - 1.0
            state.adjustments.light.contrast = clamp(contrastDelta)
        }

        if target.affectsLevels {
            let blackIn = clamp01(Double(points[0].x))
            let whiteIn = clamp01(Double(points[4].x))
            var lum = state.adjustments.levels.channels[.luminance] ?? AdjustmentState.Levels.ChannelLevels()
            lum.blackIn = blackIn
            lum.whiteIn = max(whiteIn, blackIn + 0.01)
            state.adjustments.levels.channels[.luminance] = lum
        }

        if target.affectsCurves {
            state.adjustments.curves.master = points.map { v in
                CGPoint(x: clamp01(Double(v.x)), y: clamp01(Double(v.y)))
            }
        }
    }

    // MARK: - Section presets without analyzer support

    @MainActor
    private static func applyBlackWhitePreset(state: EditorViewState) {
        state.adjustments.bw.on = true
        state.adjustments.bw.intensity = 0.2
        state.adjustments.bw.tone = 0.3
    }

    @MainActor
    private static func applyDefinitionPreset(state: EditorViewState) {
        state.adjustments.definition.amount = 0.25
    }

    // MARK: - Helpers

    private static func clamp(_ value: Double) -> Double {
        min(max(value, -1.0), 1.0)
    }

    private static func clamp01(_ value: Double) -> Double {
        min(max(value, 0.0), 1.0)
    }
}

private extension AutoEnhance.Target {
    var usesEnhanceFilters: Bool {
        switch self {
        case .light, .color, .blackWhite, .levels, .curves, .definition, .global:
            return true
        case .redEye:
            return false
        }
    }

    var usesRedEyeFilters: Bool {
        self == .redEye || self == .global
    }

    var affectsLight: Bool {
        self == .light || self == .global
    }

    var affectsColor: Bool {
        self == .color || self == .global
    }

    var affectsLevels: Bool {
        self == .levels || self == .global
    }

    var affectsCurves: Bool {
        self == .curves || self == .global
    }

    var affectsRedEye: Bool {
        self == .redEye || self == .global
    }
}
