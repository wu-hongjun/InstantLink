import SwiftUI

/// Photos-style "Levels" panel — plan 048 PR #5.
///
/// Channel pop-up (Luminance / RGB / R / G / B), histogram strip with 5
/// bottom handles (Black / Shadows / Mid / Highlights / White) + 2 top
/// handles (output Black / White). Option-drag a bottom handle pairs the
/// top counterpart.
struct LevelsSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("levels_section"),
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

    /// Auto-Levels: 0.5% / 99.5% percentile cuts on the active channel.
    /// Placeholder mid-point preset until PR #16 wires the analyzer end to
    /// end. Per research 047 the percentile cuts shave noise from the tails
    /// without saturating; here we model that with a small in/out crush.
    // TODO: wire CIAreaHistogram percentile reader in PR #16.
    private func applyAuto() {
        let channel = state.adjustments.levels.activeChannel
        if state.adjustments.levels.channels[channel]?.isNeutral == true {
            var c = AdjustmentState.Levels.ChannelLevels()
            c.blackIn = 0.02
            c.whiteIn = 0.98
            state.adjustments.levels.channels[channel] = c
        } else {
            state.adjustments.levels.channels[channel] = AdjustmentState.Levels.ChannelLevels()
        }
    }
}
