import SwiftUI

/// Photos-style "Vignette" panel: bipolar Strength + asymmetric Radius and
/// Softness sliders, with section header + Auto / Reset.
///
/// Strength is bipolar (`−1…+1`, neutral 0): negative paints a black
/// vignette, positive paints a white halo. Radius and Softness are
/// asymmetric (`0…+1`) and default to 0.5 so the inner unaffected disc has
/// a sensible starting size.
struct VignetteSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("vignette_section"),
                systemImage: "circle.dotted",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral,
                enabledBinding: $state.adjustments.vignette.sectionEnabled
            )

            if isExpanded {
                VStack(spacing: 6) {
                    AdjustmentSlider(
                        value: $state.adjustments.vignette.strength,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("vignette_strength")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.vignette.radius,
                        range: 0...1,
                        neutral: 0.5,
                        label: L_key("vignette_radius"),
                        asymmetric: true
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.vignette.softness,
                        range: 0...1,
                        neutral: 0.5,
                        label: L_key("vignette_softness"),
                        asymmetric: true
                    )
                }
                .padding(.leading, 18)
            }
        }
    }

    private var isNeutral: Bool {
        let v = state.adjustments.vignette
        return v.strength == 0 && v.radius == 0.5 && v.softness == 0.5
    }

    private func reset() {
        state.adjustments.vignette = AdjustmentState.Vignette()
    }

    /// Auto preset: toggle a mild dark vignette (`strength = -0.2`).
    /// `CIImage.autoAdjustmentFilters` does not surface a vignette analyzer
    /// recommendation, so this preset-based Auto is the shipped behavior.
    private func applyAuto() {
        if state.adjustments.vignette.strength == 0 {
            state.adjustments.vignette.strength = -0.2
        } else {
            // Photos toggles Auto off when clicked a second time.
            reset()
        }
    }
}

// `L_key(_:)` is provided by `LocalizedKey.swift` (hoisted in PR #4).
