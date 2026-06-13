import SwiftUI

/// Photos-style bipolar slider primitive. The reusable surface for every
/// adjustment section that follows (Light, Color, Curves, Levels, Vignette,
/// Sharpen, NR, Definition, Selective Color, WB, B&W).
///
/// Behaviors:
/// - Bipolar track centered at `neutral` (default `0`).
/// - Double-click anywhere on the row resets the slider to `neutral`.
/// - Numeric readout on the right shows integer percent (−100…+100 for
///   `[-1, 1]`, neutral-relative for other ranges).
/// - `asymmetric = true` switches the track to a `0..+1`-style mode where
///   there is no negative side (used by B&W Grain in PR #13).
///
/// Option-drag extended range (±2× the natural travel) is documented but
/// not yet wired — SwiftUI's `Slider` does not expose a hook to intercept
/// modifier flags during drag without a custom drag implementation. PR #17
/// (polish + fidelity pass) owns wiring this; the comment below marks the
/// known TODO.
struct AdjustmentSlider: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    let neutral: Double
    let label: LocalizedStringKey
    var asymmetric: Bool = false

    // TODO: Option-drag extended range (PR #17 polish).
    var body: some View {
        HStack(spacing: 12) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.primary)
                .frame(width: 92, alignment: .leading)

            Slider(value: $value, in: range)
                .controlSize(.small)

            Text(displayValue)
                .font(.caption.monospacedDigit())
                .foregroundStyle(isNeutral ? .secondary : .primary)
                .frame(width: 44, alignment: .trailing)
        }
        .contentShape(Rectangle())
        .onTapGesture(count: 2) {
            value = neutral
        }
    }

    private var isNeutral: Bool {
        abs(value - neutral) < 1e-6
    }

    private var displayValue: String {
        if asymmetric {
            // Map [neutral, upperBound] → 0…100.
            let span = range.upperBound - neutral
            guard span > 0 else { return "0" }
            let percent = Int(((value - neutral) / span * 100).rounded())
            return "\(max(0, percent))"
        } else {
            // Map [lowerBound, upperBound] → −100…+100, neutral-relative.
            let posSpan = range.upperBound - neutral
            let negSpan = neutral - range.lowerBound
            let span = value >= neutral ? posSpan : negSpan
            guard span > 0 else { return "0" }
            let percent = Int(((value - neutral) / span * 100).rounded())
            if percent > 0 { return "+\(percent)" }
            if percent < 0 { return "\(percent)" }
            return "0"
        }
    }
}
