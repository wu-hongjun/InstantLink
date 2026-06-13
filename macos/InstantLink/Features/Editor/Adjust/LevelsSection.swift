import SwiftUI

/// Photos-style "Levels" panel — plan 048 PR #5.
///
/// Channel pop-up (Luminance / RGB / R / G / B), histogram strip with 5
/// bottom handles (Black / Shadows / Mid / Highlights / White) + 2 top
/// handles (output Black / White). Option-drag a bottom handle pairs the
/// top counterpart.
struct LevelsSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("levels_section"),
                systemImage: "chart.bar",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(alignment: .leading, spacing: 8) {
                    Picker("", selection: $state.adjustments.levels.activeChannel) {
                        ForEach(AdjustmentState.Levels.Channel.allCases, id: \.self) { c in
                            Text(L_key(localizationKey(for: c))).tag(c)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()

                    ZStack {
                        HistogramView(state: state, height: 84, cornerRadius: 4)
                            .padding(.vertical, 14) // leave room for top/bottom handle rows
                        LevelsHandleStrip(channel: channelBinding())
                    }
                }
                .padding(.leading, 18)
            }
        }
    }

    private func channelBinding() -> Binding<AdjustmentState.Levels.ChannelLevels> {
        Binding(
            get: {
                state.adjustments.levels.channels[state.adjustments.levels.activeChannel]
                    ?? AdjustmentState.Levels.ChannelLevels()
            },
            set: { newValue in
                state.adjustments.levels.channels[state.adjustments.levels.activeChannel] = newValue
            }
        )
    }

    private func localizationKey(for channel: AdjustmentState.Levels.Channel) -> String {
        switch channel {
        case .luminance: return "levels_channel_luminance"
        case .rgb:       return "levels_channel_rgb"
        case .red:       return "levels_channel_red"
        case .green:     return "levels_channel_green"
        case .blue:      return "levels_channel_blue"
        }
    }

    private var isNeutral: Bool {
        state.adjustments.levels.isNeutral
    }

    private func reset() {
        state.adjustments.levels = AdjustmentState.Levels()
    }

    /// Auto-Levels: ask the Apple analyzer for a CIToneCurve fit and read its
    /// end-points as input black / white on the Luminance channel. Toggles
    /// back to neutral on a second click when the active channel is already
    /// non-neutral.
    private func applyAuto() {
        let channel = state.adjustments.levels.activeChannel
        if state.adjustments.levels.channels[channel]?.isNeutral == false {
            state.adjustments.levels.channels[channel] = AdjustmentState.Levels.ChannelLevels()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .levels, image: image, state: state)
    }
}
