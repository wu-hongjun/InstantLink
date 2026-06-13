import SwiftUI

/// Photos-style "Noise Reduction" panel: master ("Reduce Noise") slider plus
/// the RAW v6+ Luminance / Color / Detail sub-sliders. For v1 all four are
/// always visible; RAW gating is a follow-up (per plan 048 §PR #8).
///
/// All sliders are asymmetric `0...1` (off by default, no negative side).
/// The Auto button is a placeholder preset until PR #16 wires the Apple
/// analyzer; clicking Auto toggles between a sensible (master = 0.3,
/// detail = 0.6) preset and neutral.
struct NoiseReductionSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("nr_section"),
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(spacing: 6) {
                    AdjustmentSlider(
                        value: $state.adjustments.nr.master,
                        range: 0...1,
                        neutral: 0,
                        label: L_key("nr_master"),
                        asymmetric: true
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.nr.luma,
                        range: 0...1,
                        neutral: 0,
                        label: L_key("nr_luminance"),
                        asymmetric: true
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.nr.color,
                        range: 0...1,
                        neutral: 0,
                        label: L_key("nr_color"),
                        asymmetric: true
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.nr.detail,
                        range: 0...1,
                        neutral: 0,
                        label: L_key("nr_detail"),
                        asymmetric: true
                    )
                }
                .padding(.leading, 18)
            }
        }
    }

    private var isNeutral: Bool {
        let n = state.adjustments.nr
        return n.master == 0 && n.luma == 0 && n.color == 0 && n.detail == 0
    }

    private func reset() {
        state.adjustments.nr = AdjustmentState.NoiseReduction()
    }

    /// Apply a placeholder Auto preset. PR #16 wires the Apple analyzer
    /// end-to-end across all sections; for v1 we set a mild denoise preset
    /// that engages the master slider with edge preservation via Detail.
    // TODO: wire Apple analyzer in PR #16 Auto buttons.
    private func applyAuto() {
        if isNeutral {
            state.adjustments.nr.master = 0.3
            state.adjustments.nr.detail = 0.6
        } else {
            // Photos toggles Auto off when clicked a second time.
            reset()
        }
    }
}

/// Helper so the SwiftUI view sites can spell `LocalizedStringKey` for
/// `AdjustmentSlider.label` / `AdjustmentSectionHeader.title` without
/// having to import the runtime `NSLocalizedString` lookup. Mirrors the
/// existing `L(_:)` global but returns the SwiftUI key type.
@inline(__always)
private func L_key(_ key: String) -> LocalizedStringKey {
    LocalizedStringKey(key)
}
