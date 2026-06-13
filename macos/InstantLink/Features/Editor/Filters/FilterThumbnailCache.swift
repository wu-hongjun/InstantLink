import AppKit
import CoreImage

/// Cache of pre-rendered filter thumbnails for the Filters tab right-rail
/// strip. Keyed by `"\(sourceHash)/\(filterID)"`; thumbnails are computed
/// once per source change and reused across every filter switch so dragging
/// through the strip stays cheap.
///
/// The cache holds NSImages at the displayed thumbnail size (88 pt). The
/// source CIImage is downsampled to 256 px (long side) before the filter is
/// applied, so even the original "None" thumbnail composes off a small
/// image.
@MainActor
final class FilterThumbnailCache: ObservableObject {
    /// Square pixel size of the cached NSImage (matches `FilterRail` cell
    /// height). 88 pt @ 1× is fine — the rail is small and we don't render
    /// large blow-ups.
    static let thumbnailSize: CGFloat = 88

    /// Long-side cap (in pixels) for the downsampled source before the
    /// filter LUT runs.
    private static let downsampleLongSide: CGFloat = 256

    private var cache: [String: NSImage] = [:]
    private var currentSourceHash: String?
    private let context = CIContext(options: nil)

    /// Synchronously fetch or compute a thumbnail for `entry`.
    ///
    /// Returns `nil` only if the CIContext rendering itself fails (which
    /// should be vanishingly rare in practice — bad CIFilter names would
    /// also fall back to the input image).
    func thumbnail(for entry: FilterEntry, source: CIImage, sourceHash: String) -> NSImage? {
        if currentSourceHash != sourceHash {
            invalidate(sourceHash: sourceHash)
        }
        let key = "\(sourceHash)/\(entry.id)"
        if let cached = cache[key] { return cached }

        let downsampled = downsample(source)
        let filtered: CIImage = entry.id == FilterThumbnailCache.noneFilterID
            ? downsampled
            : downsampled.applyingFilter(entry.ciFilterName)
        guard let cg = context.createCGImage(filtered, from: filtered.extent) else {
            return nil
        }
        let size = NSSize(
            width: FilterThumbnailCache.thumbnailSize,
            height: FilterThumbnailCache.thumbnailSize
        )
        let img = NSImage(cgImage: cg, size: size)
        cache[key] = img
        return img
    }

    /// Reset the cache to a new source. Always called when the editor loads
    /// a new image; callers don't need to invoke it explicitly.
    func invalidate(sourceHash: String) {
        cache.removeAll(keepingCapacity: false)
        currentSourceHash = sourceHash
    }

    /// Compute a stable hash of `source`'s pixel content so the cache key
    /// changes whenever the user opens a different image. Plan 049 L1:
    /// in addition to extent dimensions, sample the four corners + center
    /// pixels so same-dimension images from the same camera don't collide.
    /// Falls back to extent-only if pixel readback fails.
    static func hash(for source: CIImage) -> String {
        let extent = source.extent
        let dimensions = "\(Int(extent.width))x\(Int(extent.height))@\(extent.origin.x),\(extent.origin.y)"
        let ctx = CIContext(options: nil)
        guard let cg = ctx.createCGImage(source, from: extent),
              let data = cg.dataProvider?.data,
              let bytes = CFDataGetBytePtr(data) else {
            return dimensions
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
        return dimensions + "@" + signature.map { String($0, radix: 16) }.joined(separator: ".")
    }

    /// Sentinel ID used by the rail's "None" entry. Calling
    /// `thumbnail(for:source:sourceHash:)` with an entry of this ID returns
    /// the downsampled source without any filter applied.
    static let noneFilterID = "__none__"

    /// Convenience entry for the "None" row at the top of the rail.
    static let noneEntry = FilterEntry(
        id: noneFilterID,
        displayNameKey: "filters_none",
        isBlackAndWhite: false,
        ciFilterName: ""
    )

    private func downsample(_ image: CIImage) -> CIImage {
        let extent = image.extent
        let longSide = max(extent.width, extent.height)
        guard longSide > FilterThumbnailCache.downsampleLongSide else { return image }
        let scale = FilterThumbnailCache.downsampleLongSide / longSide
        let filter = CIFilter(name: "CILanczosScaleTransform")
        filter?.setValue(image, forKey: kCIInputImageKey)
        filter?.setValue(scale, forKey: kCIInputScaleKey)
        filter?.setValue(1.0, forKey: kCIInputAspectRatioKey)
        return filter?.outputImage
            ?? image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    }
}
