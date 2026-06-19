import SwiftUI

/// Photos-style "White Balance" panel: mode picker (Neutral Gray /
/// Skin Tone / Temperature & Tint), per-mode eyedropper button, and
/// Temperature + Tint sliders for the T&T mode.
///
/// Each mode keeps its own parameter set per Photos parity — switching
/// modes does NOT silently re-apply the previous mode's adjustment.
/// `WhiteBalancePipeline` only consumes the parameters belonging to the
/// currently-selected mode.
struct WhiteBalanceSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = false

    // Plan 049 M4 — White Balance intentionally ships without an Auto
    // button. `CIImage.autoAdjustmentFilters` only returns a global
    // `CITemperatureAndTint` recommendation, which would force the section
    // into Temperature & Tint mode regardless of the user's current
    // Neutral Gray / Skin Tone selection. Photos avoids that here.

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("wb_section"),
                systemImage: "thermometer.medium",
                onReset: { reset() },
                isNeutral: isNeutral,
                enabledBinding: $state.adjustments.whiteBalance.sectionEnabled
            )

            if isExpanded {
                VStack(alignment: .leading, spacing: 8) {
                    Picker("", selection: $state.adjustments.whiteBalance.mode) {
                        Text(L_key("wb_mode_neutral_gray"))
                            .tag(AdjustmentState.WhiteBalance.Mode.neutralGray)
                        Text(L_key("wb_mode_skin_tone"))
                            .tag(AdjustmentState.WhiteBalance.Mode.skinTone)
                        Text(L_key("wb_mode_temp_tint"))
                            .tag(AdjustmentState.WhiteBalance.Mode.temperatureTint)
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .controlSize(.small)

                    Button {
                        toggleEyedropper()
                    } label: {
                        Label(L_key("wb_eyedropper"), systemImage: eyedropperSystemImage)
                    }
                    .buttonStyle(.borderless)
                    .controlSize(.small)

                    if state.adjustments.whiteBalance.mode == .temperatureTint {
                        VStack(spacing: 6) {
                            AdjustmentSlider(
                                value: $state.adjustments.whiteBalance.temperature,
                                range: -1...1,
                                neutral: 0,
                                label: L_key("wb_temperature")
                            )
                            AdjustmentSlider(
                                value: $state.adjustments.whiteBalance.tint,
                                range: -1...1,
                                neutral: 0,
                                label: L_key("wb_tint")
                            )
                        }
                    }
                }
                .padding(.leading, 18)
            }
        }
    }

    private var isNeutral: Bool {
        let wb = state.adjustments.whiteBalance
        return wb.temperature == 0
            && wb.tint == 0
            && wb.eyedropSample == nil
            && wb.eyedropPoint == nil
    }

    private var eyedropperSystemImage: String {
        let active = state.eyedropperManager.active
        let isActiveForMode: Bool
        switch state.adjustments.whiteBalance.mode {
        case .neutralGray, .temperatureTint:
            isActiveForMode = (active == .wbNeutral)
        case .skinTone:
            isActiveForMode = (active == .wbSkin)
        }
        return isActiveForMode ? "eyedropper.halffull" : "eyedropper"
    }

    private func reset() {
        state.adjustments.whiteBalance = AdjustmentState.WhiteBalance()
    }

    private func toggleEyedropper() {
        let mode = state.adjustments.whiteBalance.mode
        let activeMode: EyedropperManager.ActiveMode = (mode == .skinTone) ? .wbSkin : .wbNeutral

        if state.eyedropperManager.active == activeMode {
            state.eyedropperManager.cancel()
            return
        }

        state.eyedropperManager.start(activeMode) { [weak state] sample in
            guard let state else { return }
            state.adjustments.whiteBalance.eyedropSample = sample
        }
    }
}
