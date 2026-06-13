import SwiftUI

/// Per-kind inspector content for a Text overlay. Ported from
/// `SelectedOverlayInspectorView.textControls` in the retired legacy editor.
struct OverlayInspectorText: View {
    @ObservedObject var state: EditorViewState
    let overlay: OverlayItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField(L("Text"), text: textBinding)

            sizeSlider

            Picker(L("Alignment"), selection: alignmentBinding) {
                Text(L("Leading")).tag(OverlayTextAlignment.leading)
                Text(L("Center")).tag(OverlayTextAlignment.center)
                Text(L("Trailing")).tag(OverlayTextAlignment.trailing)
            }
            .pickerStyle(.segmented)

            Picker(L("Shadow"), selection: shadowBinding) {
                Text(L("None")).tag(OverlayShadowStyle.none)
                Text(L("Soft")).tag(OverlayShadowStyle.soft)
                Text(L("Strong")).tag(OverlayShadowStyle.strong)
            }
            .pickerStyle(.segmented)
        }
    }

    private var data: TextOverlayData {
        if case .text(let value) = overlay.content { return value }
        return TextOverlayData()
    }

    private var textBinding: Binding<String> {
        Binding(
            get: { data.text },
            set: { newValue in update { $0.text = newValue } }
        )
    }

    private var alignmentBinding: Binding<OverlayTextAlignment> {
        Binding(
            get: { data.textAlignment },
            set: { newValue in update { $0.textAlignment = newValue } }
        )
    }

    private var shadowBinding: Binding<OverlayShadowStyle> {
        Binding(
            get: { data.shadowStyle },
            set: { newValue in update { $0.shadowStyle = newValue } }
        )
    }

    private var sizeSlider: some View {
        let binding = Binding<Double>(
            get: { data.fontScale },
            set: { newValue in update { $0.fontScale = newValue } }
        )
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(L("Size"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(Int((binding.wrappedValue * 100).rounded()))%")
                    .font(.caption.monospacedDigit())
                    .foregroundColor(.secondary)
            }
            Slider(value: binding, in: 0.05...0.24)
                .controlSize(.small)
        }
    }

    private func update(_ mutate: (inout TextOverlayData) -> Void) {
        state.updateOverlay(id: overlay.id) { item in
            guard case .text(var data) = item.content else { return }
            mutate(&data)
            item.content = .text(data)
        }
    }
}
