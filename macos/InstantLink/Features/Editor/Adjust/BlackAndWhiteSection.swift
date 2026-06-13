import SwiftUI

/// Photos-style "Black & White" panel — plan 049 rebuild.
///
/// Header + 5-thumbnail intensity strip (dominant slider = Intensity) +
/// `Options` disclosure for the full Intensity / Neutrals / Tone / Grain
/// slider set. The on/off circle in the header is the section enable.
///
/// B&W is a **mode flag** (`AdjustmentState.BlackAndWhite.on`), not
/// Saturation = −1. While `on == true`:
/// - The Color section grays out (wired in ColorPipeline).
/// - The four sliders below are enabled.
struct BlackAndWhiteSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true
    @State private var showOptions: Bool = false

    private let intensities: [Double] = [-1.0, -0.5, 0, 0.5, 1.0]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("bw_section"),
                systemImage: "circle.lefthalf.filled",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral,
                enabledBinding: $state.adjustments.bw.on
            )

            if isExpanded {
                SectionThumbnailStrip(
                    state: state,
                    sectionID: "bw",
                    intensities: intensities,
                    currentValue: state.adjustments.bw.intensity,
                    renderForIntensity: { value in
                        var snap = state.snapshot()
                        // Force the B&W stack on so the strip previews the
                        // mode itself, not just intensity deltas on a colour
                        // image. This matches Photos' strip behavior.
                        snap.adjustments.bw.on = true
                        snap.adjustments.bw.intensity = value
                        return snap
                    },
                    onSelect: { value in
                        state.adjustments.bw.on = true
                        state.adjustments.bw.intensity = value
                    }
                )

                DisclosureGroup(isExpanded: $showOptions) {
                    VStack(spacing: 6) {
                        AdjustmentSlider(
                            value: $state.adjustments.bw.intensity,
                            range: -1...1,
                            neutral: 0,
                            label: L_key("bw_intensity")
                        )
                        AdjustmentSlider(
                            value: $state.adjustments.bw.neutrals,
                            range: -1...1,
                            neutral: 0,
                            label: L_key("bw_neutrals")
                        )
                        AdjustmentSlider(
                            value: $state.adjustments.bw.tone,
                            range: -1...1,
                            neutral: 0,
                            label: L_key("bw_tone")
                        )
                        AdjustmentSlider(
                            value: $state.adjustments.bw.grain,
                            range: 0...1,
                            neutral: 0,
                            label: L_key("bw_grain"),
                            asymmetric: true
                        )
                    }
                    .padding(.leading, 6)
                    .disabled(!state.adjustments.bw.on)
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
        let b = state.adjustments.bw
        return !b.on && b.intensity == 0 && b.neutrals == 0 && b.tone == 0 && b.grain == 0
    }

    private func reset() {
        state.adjustments.bw = AdjustmentState.BlackAndWhite()
    }

    /// Apply Auto via `AutoEnhance.apply(target: .blackWhite, …)`. The
    /// analyzer has no native B&W mode, so the helper turns on B&W and seeds
    /// a mild intensity/tone preset. Toggles back to neutral on a second
    /// click to match Photos.
    private func applyAuto() {
        if !isNeutral {
            reset()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .blackWhite, image: image, state: state)
    }
}
