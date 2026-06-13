import SwiftUI

/// Photos-style horizontal slider used for Straighten / Vertical / Horizontal.
/// Includes a 0-detent (soft snap) and double-click to reset.
struct StraightenSlider: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    let neutral: Double
    let label: String
    /// Unit string shown after the readout (e.g. "°" for Straighten).
    var unit: String = ""
    /// Snap width either side of `neutral` where the value rounds to neutral.
    var snapThreshold: Double = 0.5

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label)
                    .font(.callout)
                Spacer()
                Text(readout)
                    .font(.system(.callout, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            Slider(value: $value, in: range) { editing in
                if !editing { snapToDetent() }
            }
            .onTapGesture(count: 2) {
                value = neutral
            }
        }
    }

    private var readout: String {
        let v = value
        if abs(v - neutral) < 0.05 { return "0\(unit)" }
        return String(format: "%+.1f\(unit)", v)
    }

    private func snapToDetent() {
        if abs(value - neutral) < snapThreshold {
            value = neutral
        }
    }
}
