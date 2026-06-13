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
                    // PR #5: shared histogram backdrop above the Light sliders.
                    HistogramView(state: state, height: 56, cornerRadius: 4)
                        .padding(.bottom, 4)
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

    /// Fold the Apple analyzer's Light-relevant filters (CIToneCurve,
    /// CIHighlightShadowAdjust) into the Light sliders via `AutoEnhance`.
    /// Photos toggles Auto off on a second click — we honor that by resetting
    /// when already non-neutral.
    private func applyAuto() {
        if !isNeutral {
            reset()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .light, image: image, state: state)
    }
}
