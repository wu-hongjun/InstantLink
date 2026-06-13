import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI

/// One entry in the editor's filter rail.
///
/// `isBlackAndWhite` drives the locked decision Q9 behaviour: while a B&W
/// filter is selected, the Adjust B&W stack is suppressed in
/// `AdjustmentPipeline` so the filter LUT desaturates without compounding
/// with the section's own `desaturate → tone curve → grain` chain.
struct FilterEntry: Identifiable, Equatable {
    var id: String
    var displayNameKey: String
    var isBlackAndWhite: Bool
    var ciFilterName: String

    var displayName: LocalizedStringKey { LocalizedStringKey(displayNameKey) }
}

/// Catalog of filters offered by the Filters tab right-rail strip.
///
/// IDs match the legacy InstantLink filter set so persisted
/// `EditorSnapshot.filterID` values stay backward-compatible. New filter
/// additions append at the bottom — never reuse an ID.
enum FilterCatalog {
    static let all: [FilterEntry] = [
        FilterEntry(
            id: "mono",
            displayNameKey: "filter_mono",
            isBlackAndWhite: true,
            ciFilterName: "CIPhotoEffectMono"
        ),
        FilterEntry(
            id: "noir",
            displayNameKey: "filter_noir",
            isBlackAndWhite: true,
            ciFilterName: "CIPhotoEffectNoir"
        ),
        FilterEntry(
            id: "silvertone",
            displayNameKey: "filter_silvertone",
            isBlackAndWhite: true,
            ciFilterName: "CIPhotoEffectTonal"
        ),
        FilterEntry(
            id: "fade",
            displayNameKey: "filter_fade",
            isBlackAndWhite: false,
            ciFilterName: "CIPhotoEffectFade"
        ),
        FilterEntry(
            id: "chrome",
            displayNameKey: "filter_chrome",
            isBlackAndWhite: false,
            ciFilterName: "CIPhotoEffectChrome"
        ),
        FilterEntry(
            id: "instant",
            displayNameKey: "filter_instant",
            isBlackAndWhite: false,
            ciFilterName: "CIPhotoEffectInstant"
        ),
        FilterEntry(
            id: "process",
            displayNameKey: "filter_process",
            isBlackAndWhite: false,
            ciFilterName: "CIPhotoEffectProcess"
        ),
        FilterEntry(
            id: "transfer",
            displayNameKey: "filter_transfer",
            isBlackAndWhite: false,
            ciFilterName: "CIPhotoEffectTransfer"
        ),
    ]

    /// Look up an entry by ID. Unknown IDs return `nil` — callers (including
    /// the pipeline) treat that as "no filter applied".
    static func entry(for id: String?) -> FilterEntry? {
        guard let id else { return nil }
        return all.first { $0.id == id }
    }

    /// Apply the filter named by `id` to `image`. Unknown IDs pass through.
    static func apply(_ image: CIImage, id: String?) -> CIImage {
        guard let entry = entry(for: id) else { return image }
        return image.applyingFilter(entry.ciFilterName)
    }

    /// Returns true if the active filter forces the image to monochrome
    /// (Q9 override of the Adjust B&W stack).
    static func isBlackAndWhite(id: String?) -> Bool {
        entry(for: id)?.isBlackAndWhite == true
    }
}
