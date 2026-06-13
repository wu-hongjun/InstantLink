import SwiftUI

/// Single well in the Selective Color well strip.
///
/// Renders a swatch (seed colour, or a dashed "+" placeholder when empty),
/// an eyedropper button (consumes PR #12 `EyedropperManager`), a SwiftUI
/// `ColorPicker` for manual seed entry, and a clear button (only when
/// a seed exists). Tapping the swatch selects this well for editing in
/// the parent section.
struct SelectiveColorWellRow: View {
    @ObservedObject var state: EditorViewState
    let wellIndex: Int
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        VStack(spacing: 4) {
            swatch
                .onTapGesture { onSelect() }

            HStack(spacing: 2) {
                Button {
                    toggleEyedropper()
                } label: {
                    Image(systemName: isEyedropperActive ? "eyedropper.halffull" : "eyedropper")
                        .font(.caption2)
                }
                .buttonStyle(.borderless)
                .controlSize(.mini)
                .help(L_key("sel_eyedropper"))

                ColorPicker("", selection: colorPickerBinding, supportsOpacity: false)
                    .labelsHidden()
                    .controlSize(.mini)
                    .help(L_key("sel_pick_color"))
                    .frame(width: 16)

                if hasSeed {
                    Button {
                        clearWell()
                    } label: {
                        Image(systemName: "xmark.circle")
                            .font(.caption2)
                    }
                    .buttonStyle(.borderless)
                    .controlSize(.mini)
                    .help(L_key("sel_clear"))
                }
            }
        }
    }

    // MARK: - Swatch

    @ViewBuilder
    private var swatch: some View {
        let size: CGFloat = 28
        if let seed = wellSeed {
            RoundedRectangle(cornerRadius: 6)
                .fill(Color(red: seed.red, green: seed.green, blue: seed.blue))
                .frame(width: size, height: size)
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(isSelected ? Color.accentColor : Color.secondary.opacity(0.4), lineWidth: isSelected ? 2 : 1)
                )
        } else {
            RoundedRectangle(cornerRadius: 6)
                .stroke(
                    style: StrokeStyle(lineWidth: 1, dash: [3, 2])
                )
                .foregroundStyle(isSelected ? Color.accentColor : Color.secondary)
                .frame(width: size, height: size)
                .overlay(
                    Image(systemName: "plus")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                )
        }
    }

    // MARK: - State accessors

    private var wellSeed: CodableColor? {
        guard wellIndex < state.adjustments.selective.wells.count else { return nil }
        return state.adjustments.selective.wells[wellIndex].seed
    }

    private var hasSeed: Bool { wellSeed != nil }

    private var isEyedropperActive: Bool {
        state.eyedropperManager.active == .selectiveColorWell(wellIndex)
    }

    private var colorPickerBinding: Binding<Color> {
        Binding(
            get: {
                if let seed = wellSeed {
                    return Color(red: seed.red, green: seed.green, blue: seed.blue)
                }
                return Color.gray
            },
            set: { newColor in
                let nsColor = NSColor(newColor).usingColorSpace(.sRGB) ?? NSColor(newColor)
                let r = Double(nsColor.redComponent)
                let g = Double(nsColor.greenComponent)
                let b = Double(nsColor.blueComponent)
                guard wellIndex < state.adjustments.selective.wells.count else { return }
                state.adjustments.selective.wells[wellIndex].seed = CodableColor(red: r, green: g, blue: b)
                onSelect()
            }
        )
    }

    // MARK: - Actions

    private func toggleEyedropper() {
        let mode: EyedropperManager.ActiveMode = .selectiveColorWell(wellIndex)
        if state.eyedropperManager.active == mode {
            state.eyedropperManager.cancel()
            return
        }
        state.eyedropperManager.start(mode) { [weak state] sample in
            guard let state, wellIndex < state.adjustments.selective.wells.count else { return }
            state.adjustments.selective.wells[wellIndex].seed = CodableColor(
                red: sample.red,
                green: sample.green,
                blue: sample.blue
            )
        }
        onSelect()
    }

    private func clearWell() {
        guard wellIndex < state.adjustments.selective.wells.count else { return }
        state.adjustments.selective.wells[wellIndex] = AdjustmentState.SelectiveColor.Well()
    }
}
