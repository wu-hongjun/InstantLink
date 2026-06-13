import AppKit
import SwiftUI

/// Photos-style bipolar slider primitive. The reusable surface for every
/// adjustment section that follows (Light, Color, Curves, Levels, Vignette,
/// Sharpen, NR, Definition, Selective Color, WB, B&W).
///
/// Behaviors:
/// - Bipolar track centered at `neutral` (default `0`).
/// - Double-click anywhere on the row resets the slider to `neutral` —
///   intentionally row-wide rather than thumb-only because the row is small
///   and the thumb is a moving target. Photos itself resets on row-tap.
/// - Numeric readout on the right shows integer percent (−100…+100 for
///   `[-1, 1]`, neutral-relative for other ranges).
/// - `asymmetric = true` switches the track to a `0..+1`-style mode where
///   there is no negative side (used by B&W Grain in PR #13).
/// - Option-drag extends the slider's effective range to **2×** the natural
///   travel for the duration of the drag. SwiftUI's `Slider` cannot intercept
///   modifier flags during its own gesture, so we layer an invisible
///   `DragGesture` over the row; when the option key is held at gesture
///   start the value follows the drag through `[neutral − 2·negSpan,
///   neutral + 2·posSpan]`. The native `Slider` is left in place for the
///   non-option path (better focus / keyboard / accessibility behaviour).
/// - VoiceOver: every instance exposes `accessibilityLabel` (section + slider
///   name) and `accessibilityValue` (the same neutral-relative percent the
///   readout shows).
struct AdjustmentSlider: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    let neutral: Double
    let label: LocalizedStringKey
    var asymmetric: Bool = false

    /// Sensitivity for option-drag (units of `range` per point of horizontal
    /// drag). Tuned so the visible travel of the row roughly maps the
    /// extended ±2× range without feeling jittery.
    private let optionDragSensitivity: Double = 1.0 / 140.0

    @State private var optionDragStart: Double?

    var body: some View {
        HStack(spacing: 12) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.primary)
                .frame(width: 92, alignment: .leading)

            Slider(value: $value, in: range)
                .controlSize(.small)
                .simultaneousGesture(optionDragGesture)

            Text(displayValue)
                .font(.caption.monospacedDigit())
                .foregroundStyle(isNeutral ? .secondary : .primary)
                .frame(width: 44, alignment: .trailing)
        }
        .contentShape(Rectangle())
        .onTapGesture(count: 2) {
            value = neutral
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(label))
        .accessibilityValue(Text(displayValue))
        .accessibilityAdjustableAction { direction in
            let step = (range.upperBound - range.lowerBound) / 100.0
            switch direction {
            case .increment:
                value = min(range.upperBound, value + step)
            case .decrement:
                value = max(range.lowerBound, value - step)
            @unknown default:
                break
            }
        }
    }

    /// Simultaneous DragGesture that activates only when the option key is
    /// held at gesture-start. Drives `value` through ±2× the natural travel
    /// while option is down; non-option drags fall through to the native
    /// `Slider`.
    private var optionDragGesture: some Gesture {
        DragGesture(minimumDistance: 1)
            .onChanged { drag in
                guard NSEvent.modifierFlags.contains(.option) else {
                    optionDragStart = nil
                    return
                }
                if optionDragStart == nil {
                    optionDragStart = value
                }
                guard let start = optionDragStart else { return }
                let posSpan = range.upperBound - neutral
                let negSpan = neutral - range.lowerBound
                let extendedLower = neutral - 2 * negSpan
                let extendedUpper = neutral + 2 * posSpan
                let delta = Double(drag.translation.width) * optionDragSensitivity
                    * (posSpan + negSpan)
                let proposed = start + delta
                value = min(extendedUpper, max(extendedLower, proposed))
            }
            .onEnded { _ in
                optionDragStart = nil
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
