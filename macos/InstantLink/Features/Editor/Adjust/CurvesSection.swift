import CoreGraphics
import SwiftUI

/// Photos-style "Curves" panel — plan 048 PR #5.
///
/// Channel pop-up (RGB / Red / Green / Blue), monotone cubic Hermite spline
/// editor with up to 16 knots per channel, 3 eyedropper buttons (Black /
/// Mid / White point). Histogram backdrop renders behind the curve.
struct CurvesSection: View {
    @ObservedObject var state: EditorViewState
    // Plan 049: every section except Light / Color / Black & White ships
    // collapsed by default to match the Photos sidebar.
    @State private var isExpanded: Bool = false
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
                systemImage: "chart.xyaxis.line",
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
                        eyedropperButton(
                            mode: .curvesBlack,
                            systemName: "eyedropper",
                            label: L_key("curves_dropper_black")
                        )
                        eyedropperButton(
                            mode: .curvesMid,
                            systemName: "eyedropper.halffull",
                            label: L_key("curves_dropper_mid")
                        )
                        eyedropperButton(
                            mode: .curvesWhite,
                            systemName: "eyedropper.full",
                            label: L_key("curves_dropper_white")
                        )
                        Spacer()
                    }
                }
                .padding(.leading, 18)
            }
        }
    }

    // MARK: - Eyedropper buttons

    /// Plan 049 H1 fix: wire each Curves eyedropper to `EyedropperManager`
    /// with a callback that drops the sampled luminance into the matching
    /// master-RGB control point (point0 = black, point2 = mid, point4 = white).
    /// The CIToneCurve master curve has five points; we keep their `x`
    /// coordinates fixed and write the sampled luminance into `y`.
    private func eyedropperButton(
        mode: EyedropperManager.ActiveMode,
        systemName: String,
        label: LocalizedStringKey
    ) -> some View {
        let isActive = state.eyedropperManager.active == mode
        return Button {
            if isActive {
                state.eyedropperManager.cancel()
                return
            }
            state.eyedropperManager.start(mode) { [state] sample in
                let luma = 0.299 * sample.red + 0.587 * sample.green + 0.114 * sample.blue
                let pointIndex: Int
                switch mode {
                case .curvesBlack: pointIndex = 0
                case .curvesMid:   pointIndex = 2
                case .curvesWhite: pointIndex = 4
                default:           return
                }
                var pts = state.adjustments.curves.master
                guard pts.indices.contains(pointIndex) else { return }
                pts[pointIndex].y = CGFloat(max(0, min(1, luma)))
                state.adjustments.curves.master = pts
            }
        } label: {
            Image(systemName: isActive ? "scope" : systemName)
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

    /// Auto curve: copy the 5 control points the Apple analyzer's CIToneCurve
    /// returns into the master RGB curve via `AutoEnhance`. Toggles back to
    /// neutral on a second click.
    private func applyAuto() {
        if !isNeutral {
            reset()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .curves, image: image, state: state)
    }
}
