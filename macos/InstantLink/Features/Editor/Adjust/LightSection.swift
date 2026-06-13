import SwiftUI

/// Photos-style "Light" panel: 7 sliders + section header with Auto / Reset.
struct LightSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("light_section"),
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(spacing: 6) {
                    AdjustmentSlider(
                        value: $state.adjustments.light.brilliance,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_brilliance")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.light.exposure,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_exposure")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.light.highlights,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_highlights")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.light.shadows,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_shadows")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.light.brightness,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_brightness")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.light.contrast,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_contrast")
                    )
                    AdjustmentSlider(
                        value: $state.adjustments.light.blackPoint,
                        range: -1...1,
                        neutral: 0,
                        label: L_key("light_black_point")
                    )
                }
                .padding(.leading, 18)
            }
        }
    }

    private var isNeutral: Bool {
        let l = state.adjustments.light
        return l.brilliance == 0
            && l.exposure == 0
            && l.highlights == 0
            && l.shadows == 0
            && l.brightness == 0
            && l.contrast == 0
            && l.blackPoint == 0
    }

    private func reset() {
        state.adjustments.light = AdjustmentState.Light()
    }

    /// Apply a placeholder Auto preset. PR #16 wires the Apple analyzer
    /// (`CIImage.autoAdjustmentFilters`) end-to-end across all sections;
    /// for v1 we set a sensible expand-the-range preset.
    // TODO: wire Apple analyzer in PR #16 Auto buttons.
    private func applyAuto() {
        if isNeutral {
            state.adjustments.light.highlights = -0.3
            state.adjustments.light.shadows = 0.3
            state.adjustments.light.contrast = 0.2
            state.adjustments.light.blackPoint = 0.1
        } else {
            // Photos toggles Auto off when clicked a second time.
            reset()
        }
    }
}
