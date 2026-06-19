import SwiftUI

/// Photos-style "Sharpen" panel: 3 sliders + section header with Auto / Reset.
///
/// Defaults match Photos (per MacMost community reporting):
///   intensity 0.00, edges 0.22, falloff 0.69.
/// Reset returns to those defaults, NOT all-zero — Photos preserves the
/// edges/falloff baseline so that raising intensity has its tuned response
/// out of the gate.
struct SharpenSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("sharpen_section"),
                systemImage: "triangle.righthalf.filled",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral,
                enabledBinding: $state.adjustments.sharpen.sectionEnabled
            )

            if isExpanded {
                VStack(spacing: 6) {
                    AdjustmentSlider(
                        value: $state.adjustments.sharpen.intensity,
                        range: 0...1,
                        neutral: 0,
                        label: L_key("sharpen_intensity"),
                        asymmetric: true
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.sharpen.edges,
                        range: 0...1,
                        neutral: 0.22,
                        label: L_key("sharpen_edges"),
                        asymmetric: true
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.sharpen.falloff,
                        range: 0...1,
                        neutral: 0.69,
                        label: L_key("sharpen_falloff"),
                        asymmetric: true
                    )
                }
                .padding(.leading, 18)
            }
        }
    }

    private var isNeutral: Bool {
        let s = state.adjustments.sharpen
        return s.intensity == 0
            && abs(s.edges - 0.22) < 1e-6
            && abs(s.falloff - 0.69) < 1e-6
    }

    private func reset() {
        state.adjustments.sharpen = AdjustmentState.Sharpen()
    }

    /// Auto preset: toggle a moderate sharpen (`intensity = 0.3`) on/off.
    /// `CIImage.autoAdjustmentFilters` does not surface a sharpen analyzer
    /// recommendation, so this preset-based Auto is the shipped behavior.
    private func applyAuto() {
        if isNeutral {
            state.adjustments.sharpen.intensity = 0.3
        } else {
            reset()
        }
    }
}

// `L_key(_:)` is provided by `LocalizedKey.swift` (hoisted in PR #4).
