import SwiftUI

/// Photos-style "Color" panel — plan 049 rebuild.
///
/// Header + 5-thumbnail intensity strip (dominant slider = Saturation) +
/// `Options` disclosure for the full Saturation / Vibrance / Cast slider
/// set. When `state.adjustments.bw.on` (set by the B&W section), the strip
/// and sliders gray out and an explanatory note appears.
struct ColorSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true
    @State private var showOptions: Bool = false

    private let intensities: [Double] = [-1.0, -0.5, 0, 0.5, 1.0]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("color_section"),
                systemImage: "paintpalette",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral,
                enabledBinding: $state.adjustments.color.sectionEnabled
            )

            if isExpanded {
                if state.adjustments.bw.on {
                    Text(L_key("color_disabled_bw"))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .padding(.leading, 18)
                }

                SectionThumbnailStrip(
                    state: state,
                    sectionID: "color",
                    intensities: intensities,
                    currentValue: state.adjustments.color.saturation,
                    renderForIntensity: { value in
                        var snap = state.snapshot()
                        snap.adjustments.color.saturation = value
                        return snap
                    },
                    onSelect: { value in
                        state.adjustments.color.saturation = value
                    }
                )
                .disabled(state.adjustments.bw.on)
                .opacity(state.adjustments.bw.on ? 0.5 : 1)

                DisclosureGroup(isExpanded: $showOptions) {
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
                    .padding(.leading, 6)
                    .disabled(state.adjustments.bw.on)
                } label: {
                    Text(L_key("adjust_options"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .padding(.leading, 18)
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
