import SwiftUI

/// Focused editor sheet for a single Adjustments axis (saturation,
/// exposure, sharpness, hue, vignette).
///
/// The main Adjustments card lists axes as tappable value rows — tapping
/// one opens this sheet, which renders a larger preview at the top, the
/// slider for that one axis, and Cancel / Done buttons. While the sheet
/// is open the slider drives the shared ``BridgeSettingsDraft`` directly
/// so the preview updates live; Cancel restores the value captured on
/// appear, Done just closes.
///
/// Per-axis editing keeps the main card scan-friendly (label + value +
/// chevron rows) and gives each adjustment a focused surface for the
/// slider gesture without competing with eight other rows on screen.
struct BridgeAdjustmentSliderSheet: View {
    @ObservedObject var draft: BridgeSettingsDraft
    let field: BridgeSliderField
    let onClose: () -> Void

    /// Value the axis held when the sheet opened. Cancel restores it.
    @State private var initialValue: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            BridgeAdjustmentsPreviewView(
                draft: draft,
                renderSize: Self.previewSize,
                showsCaption: false
            )
            if let help = field.help, !help.isEmpty {
                Text(L(help))
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            sliderRow
            Spacer(minLength: 0)
            buttonRow
        }
        .padding(20)
        .frame(width: 520, height: 480)
        .onAppear(perform: captureInitialValue)
    }

    // MARK: - Pieces

    private var header: some View {
        HStack(spacing: 8) {
            Text(L(field.label))
                .font(.title3)
                .fontWeight(.semibold)
            Spacer()
        }
    }

    private var sliderRow: some View {
        let intBinding = Binding<Int>(
            get: {
                (draft.adjustmentsValue(forKey: field.key) as? Int) ?? Int(field.range.min)
            },
            set: { newValue in
                draft.setAdjustmentsValue(newValue, forKey: field.key)
            }
        )
        let doubleBinding = Binding<Double>(
            get: { Double(intBinding.wrappedValue) },
            set: { intBinding.wrappedValue = Int($0.rounded()) }
        )
        return HStack(spacing: 10) {
            Text("\(Int(field.range.min))")
                .font(.caption.monospacedDigit())
                .foregroundColor(.secondary)
                .frame(width: 32, alignment: .trailing)
            Slider(
                value: doubleBinding,
                in: field.range.min...field.range.max,
                step: field.range.step
            )
            Text("\(Int(field.range.max))")
                .font(.caption.monospacedDigit())
                .foregroundColor(.secondary)
                .frame(width: 32, alignment: .leading)
            Text(formatSliderBadge(value: intBinding.wrappedValue, display: field.display))
                .font(.callout.monospacedDigit())
                .foregroundColor(.primary)
                .frame(width: 56, alignment: .trailing)
        }
    }

    private var buttonRow: some View {
        HStack(spacing: 12) {
            Button(L("Cancel"), role: .cancel) {
                if let initial = initialValue {
                    draft.setAdjustmentsValue(initial, forKey: field.key)
                }
                onClose()
            }
            .keyboardShortcut(.cancelAction)
            Spacer()
            Button(L("Done")) {
                onClose()
            }
            .keyboardShortcut(.defaultAction)
            .buttonStyle(.borderedProminent)
        }
    }

    // MARK: - State plumbing

    private func captureInitialValue() {
        // Only capture once per sheet lifecycle. SwiftUI may re-call
        // onAppear if the parent rebuilds while the sheet is up; we
        // must not overwrite the snapshot mid-edit.
        guard initialValue == nil else { return }
        initialValue = (draft.adjustmentsValue(forKey: field.key) as? Int) ?? Int(field.range.min)
    }

    private func formatSliderBadge(value: Int, display: BridgeSliderDisplay) -> String {
        // Mirrors ``BridgeSchemaSectionView.formatSliderBadge`` so the
        // sheet's live readout matches the value badge on the main
        // card. Centralising this helper would mean exposing the
        // schema renderer's privates; the duplication is cheap.
        switch display {
        case .signedPercent:
            if value > 0 { return "+\(value) %" }
            return "\(value) %"
        case .unsignedPercent:
            return "\(value) %"
        case .signedEV:
            let ev = Double(value) / 100.0
            let sign = ev > 0 ? "+" : (ev < 0 ? "−" : "")
            return String(format: "%@%.2f EV", sign, abs(ev))
        case .signedDegrees:
            let sign = value > 0 ? "+" : (value < 0 ? "−" : "")
            return "\(sign)\(abs(value))°"
        case .integer:
            return "\(value)"
        }
    }

    private static let previewSize = CGSize(width: 480, height: 280)
}

/// Identifiable wrapper so a single ``BridgeSliderField`` can drive
/// SwiftUI's ``View.sheet(item:)`` modifier in the parent settings view.
struct BridgeAdjustmentSliderEditTarget: Identifiable, Equatable {
    let field: BridgeSliderField
    var id: String { field.key }
}
