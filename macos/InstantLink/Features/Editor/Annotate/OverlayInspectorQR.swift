import SwiftUI

/// Per-kind inspector content for a QR Code overlay. Ported from
/// `SelectedOverlayInspectorView.qrControls` in the retired legacy editor.
struct OverlayInspectorQR: View {
    @ObservedObject var state: EditorViewState
    let overlay: OverlayItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField(L("Content"), text: Binding(
                get: { data.payload },
                set: { newValue in update { $0.payload = newValue } }
            ))

            Toggle(L("Show Caption"), isOn: Binding(
                get: { data.showsCaption },
                set: { newValue in update { $0.showsCaption = newValue } }
            ))

            if data.showsCaption {
                TextField(L("Caption"), text: Binding(
                    get: { data.caption },
                    set: { newValue in update { $0.caption = newValue } }
                ))
            }

            Toggle(L("Quiet Zone"), isOn: Binding(
                get: { data.includesQuietZone },
                set: { newValue in update { $0.includesQuietZone = newValue } }
            ))

            Picker(L("Error Correction"), selection: Binding(
                get: { data.correctionLevel },
                set: { newValue in update { $0.correctionLevel = newValue } }
            )) {
                Text("L").tag(QRErrorCorrectionLevel.low)
                Text("M").tag(QRErrorCorrectionLevel.medium)
                Text("Q").tag(QRErrorCorrectionLevel.quartile)
                Text("H").tag(QRErrorCorrectionLevel.high)
            }
            .pickerStyle(.segmented)
        }
    }

    private var data: QROverlayData {
        if case .qrCode(let value) = overlay.content { return value }
        return QROverlayData()
    }

    private func update(_ mutate: (inout QROverlayData) -> Void) {
        state.updateOverlay(id: overlay.id) { item in
            guard case .qrCode(var data) = item.content else { return }
            mutate(&data)
            item.content = .qrCode(data)
        }
    }
}
