import CoreGraphics
import SwiftUI

/// Photos-style "Curves" panel — plan 048 PR #5.
///
/// Channel pop-up (RGB / Red / Green / Blue), monotone cubic Hermite spline
/// editor with up to 16 knots per channel, 3 eyedropper buttons (Black /
/// Mid / White point). Histogram backdrop renders behind the curve.
struct CurvesSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true
    @State private var activeChannel: ActiveChannel = .rgb

    /// Curves is per Apple: RGB master + R / G / B per-channel. No Luminance
    /// option — that lives in Levels.
    enum ActiveChannel: String, CaseIterable, Identifiable {
        case rgb, red, green, blue
        var id: String { rawValue }
        var labelKey: String {
            switch self {
            case .rgb:   return "curves_channel_rgb"
            case .red:   return "curves_channel_red"
            case .green: return "curves_channel_green"
            case .blue:  return "curves_channel_blue"
            }
        }
        var stroke: Color {
            switch self {
            case .rgb:   return .white
            case .red:   return Color(red: 1, green: 0.35, blue: 0.35)
            case .green: return Color(red: 0.35, green: 1, blue: 0.45)
            case .blue:  return Color(red: 0.4, green: 0.55, blue: 1)
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("curves_section"),
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(alignment: .leading, spacing: 8) {
                    Picker("", selection: $activeChannel) {
                        ForEach(ActiveChannel.allCases) { c in
                            Text(L_key(c.labelKey)).tag(c)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()

                    ZStack {
                        HistogramView(state: state, height: 160, cornerRadius: 4)
                        CurvePointEditor(points: activeBinding(), stroke: activeChannel.stroke)
                            .padding(2)
                    }
                    .frame(height: 160)

                    HStack(spacing: 6) {
                        eyedropperButton(systemName: "eyedropper", label: L_key("curves_dropper_black"))
                        eyedropperButton(systemName: "eyedropper.halffull", label: L_key("curves_dropper_mid"))
                        eyedropperButton(systemName: "eyedropper.full", label: L_key("curves_dropper_white"))
                        Spacer()
                    }
                }
                .padding(.leading, 18)
            }
        }
    }

    // MARK: - Eyedropper buttons (UI scaffold — image hit-test lands in PR #12)

    private func eyedropperButton(systemName: String, label: LocalizedStringKey) -> some View {
        // The actual click-on-canvas wiring lands with the eyedropper
        // infrastructure in PR #12; in PR #5 we surface the buttons so
        // the section's layout matches Photos.
        Button {
            // TODO(PR #12): activate EyedropperManager for the matching
            // curves dropper kind (.curvesBlack / .curvesMid / .curvesWhite).
        } label: {
            Image(systemName: systemName)
                .font(.caption)
                .help(label)
                .frame(width: 22, height: 18)
        }
        .buttonStyle(.borderless)
    }

    // MARK: - Bindings / helpers

    private func activeBinding() -> Binding<[CGPoint]> {
        switch activeChannel {
        case .rgb:   return $state.adjustments.curves.master
        case .red:   return $state.adjustments.curves.red
        case .green: return $state.adjustments.curves.green
        case .blue:  return $state.adjustments.curves.blue
        }
    }

    private var isNeutral: Bool {
        let c = state.adjustments.curves
        return isIdentity(c.master) && isIdentity(c.red) && isIdentity(c.green) && isIdentity(c.blue)
    }

    private func isIdentity(_ points: [CGPoint]) -> Bool {
        guard !points.isEmpty else { return true }
        for p in points where abs(p.x - p.y) > 1e-6 { return false }
        return true
    }

    private func reset() {
        state.adjustments.curves = AdjustmentState.Curves()
    }

    /// Auto curve: gentle mid-tone S applied to the master / RGB curve. PR
    /// #16 replaces with `CIImage.autoAdjustmentFilters`.
    // TODO: wire Apple analyzer in PR #16 Auto buttons.
    private func applyAuto() {
        if isNeutral {
            state.adjustments.curves.master = [
                CGPoint(x: 0, y: 0),
                CGPoint(x: 0.25, y: 0.21),
                CGPoint(x: 0.5, y: 0.5),
                CGPoint(x: 0.75, y: 0.79),
                CGPoint(x: 1, y: 1),
            ]
        } else {
            reset()
        }
    }
}
