import AppKit
import SwiftUI

/// Per-kind inspector content for an Image overlay. Ported from
/// `SelectedOverlayInspectorView.imageControls` in the retired legacy editor.
struct OverlayInspectorImage: View {
    @ObservedObject var state: EditorViewState
    let overlay: OverlayItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(L("Replace Image")) {
                replaceAsset()
            }
            .controlSize(.small)

            Picker(L("Fit Mode"), selection: Binding(
                get: { data.contentMode },
                set: { newValue in update { $0.contentMode = newValue } }
            )) {
                Text(L("Contain")).tag(OverlayImageContentMode.fit)
                Text(L("Crop")).tag(OverlayImageContentMode.fill)
            }
            .pickerStyle(.segmented)

            Toggle(L("Background"), isOn: Binding(
                get: { data.showsBacking },
                set: { newValue in update { $0.showsBacking = newValue } }
            ))

            cornerRadiusSlider
        }
    }

    private var data: ImageOverlayData {
        if case .image(let value) = overlay.content { return value }
        return ImageOverlayData(asset: OverlayImageAsset(fileName: nil, imageData: Data()))
    }

    private var cornerRadiusSlider: some View {
        let binding = Binding<Double>(
            get: { data.cornerRadius },
            set: { newValue in update { $0.cornerRadius = newValue } }
        )
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(L("Corner Radius"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(Int(binding.wrappedValue.rounded()))pt")
                    .font(.caption.monospacedDigit())
                    .foregroundColor(.secondary)
            }
            Slider(value: binding, in: 0...32)
                .controlSize(.small)
        }
    }

    private func update(_ mutate: (inout ImageOverlayData) -> Void) {
        state.updateOverlay(id: overlay.id) { item in
            guard case .image(var data) = item.content else { return }
            mutate(&data)
            item.content = .image(data)
        }
    }

    private func replaceAsset() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.message = L("Select an image to print")
        guard panel.runModal() == .OK,
              let url = panel.url,
              let image = NSImage(contentsOf: url),
              let tiff = image.tiffRepresentation else { return }
        let asset = OverlayImageAsset(fileName: url.lastPathComponent, imageData: tiff)
        let aspectRatio: Double? = image.size.height > 0
            ? Double(image.size.width / image.size.height)
            : nil

        state.updateOverlay(id: overlay.id) { item in
            guard case .image(var data) = item.content else { return }
            data.asset = asset
            item.content = .image(data)
            if let ar = aspectRatio, ar > 0 {
                item.aspectRatioReference = ar
                var adjusted = item.placement
                adjusted.normalizedHeight = adjusted.normalizedWidth / ar
                item.placement = adjusted.clamped
            }
        }
    }
}
