import SwiftUI

/// Photos-style "Color" panel: 3 sliders (Saturation / Vibrance / Cast)
/// + section header with Auto / Reset.
///
/// B&W interop: when `state.adjustments.bw.on` (set by PR #13), the Color
/// sliders are disabled and the section shows an explanatory tooltip line.
struct ColorSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("color_section"),
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(alignment: .leading, spacing: 6) {
                    if state.adjustments.bw.on {
                        Text(L_key("color_disabled_bw"))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .padding(.leading, 18)
                    }

                    VStack(spacing: 6) {
                        AdjustmentSlider(
                            value: $state.adjustments.color.saturation,
                            range: -1...1,
                            neutral: 0,
                            label: L_key("color_saturation")
                        )
                        AdjustmentSlider(
                            value: $state.adjustments.color.vibrance,
                            range: -1...1,
                            neutral: 0,
                            label: L_key("color_vibrance")
                        )
                        AdjustmentSlider(
                            value: $state.adjustments.color.cast,
                            range: -1...1,
                            neutral: 0,
                            label: L_key("color_cast")
                        )
                    }
                    .padding(.leading, 18)
                    .disabled(state.adjustments.bw.on)
                }
            }
        }
    }

    private var isNeutral: Bool {
        let c = state.adjustments.color
        return c.saturation == 0 && c.vibrance == 0 && c.cast == 0
    }

    private func reset() {
        state.adjustments.color = AdjustmentState.Color()
    }

    /// Fold the Apple analyzer's Color-relevant filters (CIVibrance,
    /// CITemperatureAndTint) into the Color sliders via `AutoEnhance`. Toggles
    /// back to neutral on a second click to match Photos.
    private func applyAuto() {
        if !isNeutral {
            reset()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .color, image: image, state: state)
    }
}
