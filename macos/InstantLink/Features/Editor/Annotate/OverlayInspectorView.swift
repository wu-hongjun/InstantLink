import SwiftUI

/// Inspector for the currently selected overlay. Shows shared header
/// affordances (name, z-order, lock/hide, duplicate/delete), then three
/// section cards — Position, Appearance, Content — with the Content card
/// switching on overlay kind to a per-kind sub-inspector.
struct OverlayInspectorView: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        if let overlay = state.selectedOverlay {
            VStack(alignment: .leading, spacing: 10) {
                header(for: overlay)
                nameField(for: overlay)
                lockHiddenToggles(for: overlay)
                duplicateDeleteRow

                positionCard(for: overlay)
                    .disabled(overlay.isLocked)
                appearanceCard(for: overlay)
                    .disabled(overlay.isLocked)
                contentCard(for: overlay)
                    .disabled(overlay.isLocked)
            }
        }
    }

    // MARK: - Header

    private func header(for overlay: OverlayItem) -> some View {
        HStack {
            Text(displayTitle(for: overlay))
                .font(.callout)
                .fontWeight(.semibold)
            Spacer()
            Button(L("Send Backward")) {
                state.moveSelectedOverlay(forward: false)
            }
            .controlSize(.small)
            .disabled(overlay.isLocked)
            Button(L("Bring Forward")) {
                state.moveSelectedOverlay(forward: true)
            }
            .controlSize(.small)
            .disabled(overlay.isLocked)
        }
    }

    private func nameField(for overlay: OverlayItem) -> some View {
        TextField(
            L("Name"),
            text: customNameBinding(for: overlay),
            prompt: Text(defaultTitle(for: overlay))
        )
        .textFieldStyle(.roundedBorder)
    }

    private func lockHiddenToggles(for overlay: OverlayItem) -> some View {
        HStack {
            Toggle(L("Lock"), isOn: Binding(
                get: { overlay.isLocked },
                set: { newValue in state.updateOverlay(id: overlay.id) { $0.isLocked = newValue } }
            ))
            Toggle(L("Hidden"), isOn: Binding(
                get: { overlay.isHidden },
                set: { newValue in state.updateOverlay(id: overlay.id) { $0.isHidden = newValue } }
            ))
        }
        .font(.caption)
    }

    private var duplicateDeleteRow: some View {
        HStack {
            Button(L("Duplicate")) { state.duplicateSelectedOverlay() }
            Button(L("Delete")) {
                if let id = state.selectedOverlayID {
                    state.deleteOverlay(id: id)
                }
            }
        }
        .controlSize(.small)
    }

    // MARK: - Section cards

    private func positionCard(for overlay: OverlayItem) -> some View {
        AnnotateInspectorCard(title: L("annotate_inspector_position")) {
            labeledSlider(L("X"), get: { state.selectedOverlay?.placement.normalizedCenterX ?? 0.5 }, set: { newValue in
                state.updateOverlay(id: overlay.id) { $0.placement.normalizedCenterX = newValue }
            }, range: 0.05...0.95, displayMultiplier: 100, suffix: "%")
            labeledSlider(L("Y"), get: { state.selectedOverlay?.placement.normalizedCenterY ?? 0.5 }, set: { newValue in
                state.updateOverlay(id: overlay.id) { $0.placement.normalizedCenterY = newValue }
            }, range: 0.05...0.95, displayMultiplier: 100, suffix: "%")
            labeledSlider(L("Width"), get: { state.selectedOverlay?.placement.normalizedWidth ?? 0.25 }, set: { newValue in
                state.updateOverlay(id: overlay.id) { item in
                    item.setNormalizedWidth(newValue)
                }
            }, range: 0.08...0.95, displayMultiplier: 100, suffix: "%")
            labeledSlider(L("Height"), get: { state.selectedOverlay?.placement.normalizedHeight ?? 0.15 }, set: { newValue in
                state.updateOverlay(id: overlay.id) { item in
                    item.setNormalizedHeight(newValue)
                }
            }, range: 0.06...0.95, displayMultiplier: 100, suffix: "%")
            Toggle(L("Lock Aspect Ratio"), isOn: Binding(
                get: { state.selectedOverlay?.preservesAspectRatio ?? true },
                set: { newValue in
                    state.updateOverlay(id: overlay.id) { item in
                        item.setPreservesAspectRatio(newValue)
                    }
                }
            ))
            .font(.caption)
        }
    }

    private func appearanceCard(for overlay: OverlayItem) -> some View {
        AnnotateInspectorCard(title: L("annotate_inspector_appearance")) {
            labeledSlider(L("Opacity"), get: { state.selectedOverlay?.opacity ?? 1.0 }, set: { newValue in
                state.updateOverlay(id: overlay.id) { $0.opacity = newValue }
            }, range: 0.1...1.0, displayMultiplier: 100, suffix: "%")
        }
    }

    @ViewBuilder
    private func contentCard(for overlay: OverlayItem) -> some View {
        AnnotateInspectorCard(title: L("annotate_inspector_content")) {
            switch overlay.content {
            case .text:
                OverlayInspectorText(state: state, overlay: overlay)
            case .qrCode:
                OverlayInspectorQR(state: state, overlay: overlay)
            case .timestamp:
                OverlayInspectorTimestamp(state: state, overlay: overlay)
            case .image:
                OverlayInspectorImage(state: state, overlay: overlay)
            case .location:
                OverlayInspectorLocation(state: state, overlay: overlay)
            }
        }
    }

    // MARK: - Helpers

    private func customNameBinding(for overlay: OverlayItem) -> Binding<String> {
        Binding(
            get: { overlay.customName ?? "" },
            set: { newValue in
                state.updateOverlay(id: overlay.id) { item in
                    let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
                    item.customName = trimmed.isEmpty ? nil : trimmed
                }
            }
        )
    }

    private func displayTitle(for overlay: OverlayItem) -> String {
        if let custom = overlay.customName?.trimmingCharacters(in: .whitespacesAndNewlines),
           !custom.isEmpty {
            return custom
        }
        return defaultTitle(for: overlay)
    }

    private func defaultTitle(for overlay: OverlayItem) -> String {
        switch overlay.content {
        case .text(let data):
            let trimmed = data.text.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? L("Text") : trimmed
        case .qrCode:
            return L("QR Code")
        case .timestamp:
            return L("Timestamp")
        case .image(let data):
            return data.asset.fileName ?? L("Image")
        case .location:
            return L("Location")
        }
    }

    @ViewBuilder
    private func labeledSlider(
        _ title: String,
        get: @escaping () -> Double,
        set: @escaping (Double) -> Void,
        range: ClosedRange<Double>,
        displayMultiplier: Double,
        suffix: String
    ) -> some View {
        let binding = Binding<Double>(get: get, set: set)
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(Int((binding.wrappedValue * displayMultiplier).rounded()))\(suffix)")
                    .font(.caption.monospacedDigit())
                    .foregroundColor(.secondary)
            }
            Slider(value: binding, in: range)
                .controlSize(.small)
        }
    }
}

/// Compact card wrapper for an Annotate-tab inspector section.
struct AnnotateInspectorCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundColor(.secondary)

            content()
        }
        .padding(10)
        .background(Color.white.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
