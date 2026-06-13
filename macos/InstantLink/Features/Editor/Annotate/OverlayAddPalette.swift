import AppKit
import SwiftUI

/// 5-button palette for adding a new overlay kind in the Annotate tab.
/// Adds the new overlay to `EditorViewState.overlays` with a kind-specific
/// default placement (mirrors the legacy `addOverlay(kind:)` behavior from
/// `ViewModel`).
struct OverlayAddPalette: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        LazyVGrid(
            columns: [
                GridItem(.flexible(minimum: 0), spacing: 8),
                GridItem(.flexible(minimum: 0), spacing: 8)
            ],
            alignment: .leading,
            spacing: 8
        ) {
            addButton(L("annotate_add_text"), systemImage: "textformat") {
                addOverlay(of: .text)
            }
            addButton(L("annotate_add_qr"), systemImage: "qrcode") {
                addOverlay(of: .qrCode)
            }
            addButton(L("annotate_add_timestamp"), systemImage: "calendar") {
                addOverlay(of: .timestamp)
            }
            addButton(L("annotate_add_image"), systemImage: "photo") {
                addOverlay(of: .image)
            }
            addButton(L("annotate_add_location"), systemImage: "location") {
                addOverlay(of: .location)
            }
        }
    }

    private func addButton(_ title: String, systemImage: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.bordered)
        .buttonBorderShape(.roundedRectangle)
        .controlSize(.small)
    }

    private func addOverlay(of kind: OverlayKind) {
        let content: OverlayContent
        switch kind {
        case .image:
            guard let asset = selectImageAsset() else { return }
            content = .image(ImageOverlayData(asset: asset))
        case .text:
            content = .text(TextOverlayData())
        case .qrCode:
            content = .qrCode(QROverlayData())
        case .timestamp:
            content = .timestamp(TimestampOverlayData())
        case .location:
            content = .location(LocationOverlayData())
        }

        let placement = defaultPlacement(for: kind)
        let aspectRatio: Double
        if case .image(let data) = content,
           let imageAR = imageAspectRatio(for: data.asset) {
            aspectRatio = imageAR
        } else {
            aspectRatio = placement.aspectRatio
        }

        let overlay = OverlayItem(
            content: content,
            placement: adjusted(placement, toAspectRatio: aspectRatio),
            aspectRatioReference: aspectRatio,
            preservesAspectRatio: true,
            opacity: 1.0,
            zIndex: 0
        )
        state.addOverlay(overlay)
    }

    private func defaultPlacement(for kind: OverlayKind) -> OverlayPlacement {
        switch kind {
        case .qrCode:
            return OverlayPlacement(normalizedCenterX: 0.78, normalizedCenterY: 0.78, normalizedWidth: 0.22, normalizedHeight: 0.22)
        case .image:
            return OverlayPlacement(normalizedCenterX: 0.78, normalizedCenterY: 0.24, normalizedWidth: 0.24, normalizedHeight: 0.24)
        case .timestamp:
            return OverlayPlacement(normalizedCenterX: 0.82, normalizedCenterY: 0.93, normalizedWidth: 0.34, normalizedHeight: 0.1)
        case .location:
            return OverlayPlacement(normalizedCenterX: 0.24, normalizedCenterY: 0.9, normalizedWidth: 0.21, normalizedHeight: 0.25)
        case .text:
            return OverlayPlacement(normalizedCenterX: 0.5, normalizedCenterY: 0.16, normalizedWidth: 0.42, normalizedHeight: 0.14)
        }
    }

    private func adjusted(_ placement: OverlayPlacement, toAspectRatio aspectRatio: Double) -> OverlayPlacement {
        guard aspectRatio > 0 else { return placement.clamped }
        var adjusted = placement
        adjusted.normalizedHeight = adjusted.normalizedWidth / aspectRatio
        return adjusted.clamped
    }

    private func imageAspectRatio(for asset: OverlayImageAsset) -> Double? {
        guard let image = NSImage(data: asset.imageData), image.size.height > 0 else {
            return nil
        }
        return Double(image.size.width / image.size.height)
    }

    private func selectImageAsset() -> OverlayImageAsset? {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.message = L("annotate_select_image_overlay")
        guard panel.runModal() == .OK,
              let url = panel.url,
              let image = NSImage(contentsOf: url),
              let tiff = image.tiffRepresentation else { return nil }
        return OverlayImageAsset(fileName: url.lastPathComponent, imageData: tiff)
    }
}
