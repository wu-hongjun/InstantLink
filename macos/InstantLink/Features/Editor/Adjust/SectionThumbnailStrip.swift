import AppKit
import CoreImage
import SwiftUI

/// Plan 049: Photos-style 5-thumbnail intensity strip.
///
/// Each Adjust section that ships a strip provides:
///   - `sectionID` (e.g. "light") — caches per section so swapping section
///     doesn't poison the others.
///   - `intensities` — 5 dominant-slider values, e.g. `[-1, -0.5, 0, 0.5, 1]`.
///   - `currentValue` — the section's dominant slider's live value, used to
///     ring-highlight the matching thumbnail.
///   - `renderForIntensity(_:)` — builds an `EditorSnapshot` reflecting this
///     section + dominant slider at the given intensity.
///   - `onSelect(_:)` — fires when the user taps a tile.
///
/// Thumbnails are rendered through the existing `AdjustmentPipeline` so
/// every section gets visually-correct previews. Tiles are cached by
/// `(sourceHash, sectionID, intensity)` and invalidated whenever the source
/// changes.
struct SectionThumbnailStrip: View {
    @ObservedObject var state: EditorViewState
    let sectionID: String
    let intensities: [Double]
    let currentValue: Double
    let renderForIntensity: (Double) -> EditorSnapshot
    let onSelect: (Double) -> Void

    @StateObject private var cache = SectionThumbnailCache()

    private static let tileWidth: CGFloat = 56
    private static let tileHeight: CGFloat = 44

    var body: some View {
        HStack(spacing: 4) {
            ForEach(intensities, id: \.self) { intensity in
                ThumbnailTile(
                    image: thumbnail(for: intensity),
                    isSelected: abs(intensity - currentValue) < 0.05,
                    width: Self.tileWidth,
                    height: Self.tileHeight,
                    onTap: { onSelect(intensity) }
                )
            }
        }
        .padding(.horizontal, 8)
    }

    @MainActor
    private func thumbnail(for intensity: Double) -> NSImage? {
        guard let preview = state.previewImage else { return nil }
        let sourceHash = SectionThumbnailCache.hash(for: preview)
        if cache.currentHash != sourceHash {
            cache.invalidate(hash: sourceHash)
        }
        let key = "\(sectionID)/\(String(format: "%.2f", intensity))"
        if let cached = cache.image(forKey: key) { return cached }

        let snap = renderForIntensity(intensity)
        let downsampled = SectionThumbnailCache.downsample(preview)
        let composed = state.pipeline.compose(downsampled, state: snap)
        guard let cg = cache.context.createCGImage(composed, from: composed.extent) else {
            return nil
        }
        let img = NSImage(cgImage: cg, size: NSSize(width: Self.tileWidth, height: Self.tileHeight))
        cache.set(img, forKey: key)
        return img
    }
}

/// Single thumbnail tile with subtle selection ring.
private struct ThumbnailTile: View {
    let image: NSImage?
    let isSelected: Bool
    let width: CGFloat
    let height: CGFloat
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            ZStack {
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(Color.black.opacity(0.2))
                if let image {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: width, height: height)
                        .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
                }
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .stroke(
                        isSelected ? Color.accentColor : Color.white.opacity(0.15),
                        lineWidth: isSelected ? 2 : 0.5
                    )
            }
            .frame(width: width, height: height)
        }
        .buttonStyle(.plain)
    }
}

/// Owns the per-strip thumbnail cache. Held by SwiftUI `@StateObject` so the
/// cache survives view body re-evaluation but is torn down with the editor.
@MainActor
final class SectionThumbnailCache: ObservableObject {
    private var images: [String: NSImage] = [:]
    private(set) var currentHash: String?
    let context = CIContext(options: nil)

    /// Long-side cap for the source downsampled before each thumbnail is
    /// rendered. 128 px keeps render cheap (≤ 5 tiles × ≤ 3 sections strips
    /// per editor open).
    private static let downsampleLongSide: CGFloat = 128

    func image(forKey key: String) -> NSImage? { images[key] }

    func set(_ image: NSImage, forKey key: String) {
        images[key] = image
    }

    func invalidate(hash: String) {
        images.removeAll(keepingCapacity: false)
        currentHash = hash
    }

    /// Pixel-content hash of `source`. Samples 4 corners plus the center so
    /// same-dimension images from the same camera don't collide.
    static func hash(for source: CIImage) -> String {
        let extent = source.extent
        let dim = "\(Int(extent.width))x\(Int(extent.height))"
        let ctx = CIContext(options: nil)
        guard let cg = ctx.createCGImage(source, from: extent),
              let data = cg.dataProvider?.data,
              let bytes = CFDataGetBytePtr(data) else {
            return dim
        }
        let bpr = cg.bytesPerRow
        let w = cg.width
        let h = cg.height
        func pixel(_ x: Int, _ y: Int) -> Int {
            let xi = max(0, min(w - 1, x))
            let yi = max(0, min(h - 1, y))
            let i = yi * bpr + xi * 4
            return (Int(bytes[i]) << 16)
                | (Int(bytes[i + 1]) << 8)
                | Int(bytes[i + 2])
        }
        let signature = [
            pixel(0, 0),
            pixel(w - 1, 0),
            pixel(0, h - 1),
            pixel(w - 1, h - 1),
            pixel(w / 2, h / 2),
        ]
        return dim + "@" + signature.map { String($0, radix: 16) }.joined(separator: ".")
    }

    /// Public downsample helper so the strip can pre-size the source before
    /// running the full adjustment pipeline.
    static func downsample(_ image: CIImage) -> CIImage {
        let extent = image.extent
        let longSide = max(extent.width, extent.height)
        guard longSide > downsampleLongSide else { return image }
        let scale = downsampleLongSide / longSide
        let filter = CIFilter(name: "CILanczosScaleTransform")
        filter?.setValue(image, forKey: kCIInputImageKey)
        filter?.setValue(scale, forKey: kCIInputScaleKey)
        filter?.setValue(1.0, forKey: kCIInputAspectRatioKey)
        return filter?.outputImage
            ?? image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    }
}
