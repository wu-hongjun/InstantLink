import SwiftUI

/// Aspect-ratio popup + landscape/portrait segmented toggle.
///
/// Mirrors Photos' Crop popup: Original / Freeform / Square / 16:9 / 10:8 /
/// 7:5 / 4:3 / 5:3 / 3:2 / Custom… Printer-aware presets (Mini / Square / Wide
/// Link) appear only when a printer profile is paired.
struct AspectRatioPicker: View {
    @Binding var crop: CropState
    let printerAvailable: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Menu {
                    aspectSection(title: nil, cases: [.original, .freeform, .square])
                    Divider()
                    aspectSection(title: nil, cases: [.r16x9, .r10x8, .r7x5, .r4x3, .r5x3, .r3x2])
                    Divider()
                    Button(L("crop_aspect_custom")) { crop.aspect = .custom }
                    if printerAvailable {
                        Divider()
                        aspectSection(title: nil, cases: [.printerMini, .printerSquare, .printerWide])
                    }
                } label: {
                    HStack {
                        Text(label(for: crop.aspect))
                        Spacer(minLength: 4)
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption2)
                    }
                }
                .menuStyle(.borderlessButton)
                .frame(maxWidth: .infinity, alignment: .leading)

                if supportsOrientationToggle(crop.aspect) {
                    orientationToggle
                }
            }

            if crop.aspect == .custom {
                customAspectEntry
            }
        }
    }

    // MARK: - Sub-views

    @ViewBuilder
    private func aspectSection(title: String?, cases: [CropState.Aspect]) -> some View {
        if let title { Text(title) }
        ForEach(cases, id: \.self) { c in
            Button(label(for: c)) { crop.aspect = c }
        }
    }

    private var orientationToggle: some View {
        Picker("", selection: $crop.orientation) {
            Image(systemName: "rectangle")
                .tag(CropState.Orientation.landscape)
                .help(L("crop_orientation_landscape"))
            Image(systemName: "rectangle.portrait")
                .tag(CropState.Orientation.portrait)
                .help(L("crop_orientation_portrait"))
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .frame(width: 80)
    }

    private var customAspectEntry: some View {
        HStack(spacing: 6) {
            customField(value: Binding<Double>(
                get: { Double(crop.customAspect.width) },
                set: { crop.customAspect.width = CGFloat(max(0.1, $0)) }
            ))
            Text("×")
                .foregroundStyle(.secondary)
            customField(value: Binding<Double>(
                get: { Double(crop.customAspect.height) },
                set: { crop.customAspect.height = CGFloat(max(0.1, $0)) }
            ))
        }
    }

    private func customField(value: Binding<Double>) -> some View {
        TextField("", value: value, format: .number.precision(.fractionLength(0...3)))
            .textFieldStyle(.roundedBorder)
            .frame(width: 56)
    }

    // MARK: - Label helpers

    private func label(for aspect: CropState.Aspect) -> String {
        switch aspect {
        case .original: return L("crop_aspect_original")
        case .freeform: return L("crop_aspect_freeform")
        case .square:   return L("crop_aspect_square")
        case .r16x9:    return "16:9"
        case .r10x8:    return "10:8"
        case .r7x5:     return "7:5"
        case .r4x3:     return "4:3"
        case .r5x3:     return "5:3"
        case .r3x2:     return "3:2"
        case .custom:   return L("crop_aspect_custom")
        case .printerMini:   return L("crop_aspect_printer_mini")
        case .printerSquare: return L("crop_aspect_printer_square")
        case .printerWide:   return L("crop_aspect_printer_wide")
        }
    }

    /// Original / Freeform / Square are intrinsically orientation-neutral.
    private func supportsOrientationToggle(_ aspect: CropState.Aspect) -> Bool {
        switch aspect {
        case .original, .freeform, .square, .printerSquare: return false
        default: return true
        }
    }
}
