import SwiftUI

/// Photos-style "Black & White" panel: on/off toggle + 4 sliders
/// (Intensity, Neutrals, Tone, Grain) + section header with Auto / Reset.
///
/// B&W is a **mode flag** (`AdjustmentState.BlackAndWhite.on`), not
/// Saturation = −1. While `on == true`:
/// - The Color section grays out (wired in PR #4 / ColorPipeline).
/// - The four sliders below are enabled.
///
/// Neutrals is a **mid-tone LUMINANCE shift** (no hue/tint — Photos has no
/// hue-tint slider in B&W). Grain is asymmetric (`0..+1`); negative is a
/// no-op in the pipeline.
struct BlackAndWhiteSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("bw_section"),
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral,
                enabledBinding: $state.adjustments.bw.on
            )

            if isExpanded {
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
                .padding(.leading, 18)
                .disabled(!state.adjustments.bw.on)
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
