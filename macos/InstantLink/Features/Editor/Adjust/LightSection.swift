import SwiftUI

/// Photos-style "Light" panel — plan 049 rebuild.
///
/// Header + 5-thumbnail intensity strip (dominant slider = Brilliance) +
/// `Options` disclosure that hides the full 7-slider stack until requested.
struct LightSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true
    @State private var showOptions: Bool = false

    private let intensities: [Double] = [-1.0, -0.5, 0, 0.5, 1.0]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("light_section"),
                systemImage: "sun.max",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                SectionThumbnailStrip(
                    state: state,
                    sectionID: "light",
                    intensities: intensities,
                    currentValue: state.adjustments.light.brilliance,
                    renderForIntensity: { value in
                        var snap = state.snapshot()
                        snap.adjustments.light.brilliance = value
                        return snap
                    },
                    onSelect: { value in
                        state.adjustments.light.brilliance = value
                    }
                )

                DisclosureGroup(isExpanded: $showOptions) {
                    VStack(spacing: 6) {
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
                    .padding(.leading, 6)
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
