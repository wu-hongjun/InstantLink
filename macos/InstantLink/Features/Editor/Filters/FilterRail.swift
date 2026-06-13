import AppKit
import CoreImage
import SwiftUI

/// Vertical thumbnail strip of available filters for the Filters tab.
///
/// Click a thumbnail to apply the filter; click again (or click the "None"
/// row at the top) to remove it. The selected filter is outlined with a
/// highlight ring per Photos parity.
///
/// Thumbnails are sourced from `FilterThumbnailCache` keyed by the current
/// preview image's hash so each is computed once and reused as the user
/// flips through filters.
struct FilterRail: View {
    @ObservedObject var state: EditorViewState
    @StateObject private var cache = FilterThumbnailCache()

    private static let thumbnailSize: CGFloat = FilterThumbnailCache.thumbnailSize
    private static let cornerRadius: CGFloat = 10

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                FilterRailCell(
                    entry: FilterThumbnailCache.noneEntry,
                    thumbnail: thumbnail(for: FilterThumbnailCache.noneEntry),
                    isSelected: state.filterID == nil
                ) {
                    state.filterID = nil
                }

                ForEach(FilterCatalog.all) { entry in
                    FilterRailCell(
                        entry: entry,
                        thumbnail: thumbnail(for: entry),
                        isSelected: state.filterID == entry.id
                    ) {
                        // Click again on the active filter removes it
                        // (Photos parity).
                        if state.filterID == entry.id {
                            state.filterID = nil
                        } else {
                            state.filterID = entry.id
                        }
                    }
                }
            }
            .padding(.vertical, 14)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
        }
        .onChange(of: sourceHash) { _, newHash in
            cache.invalidate(sourceHash: newHash)
        }
    }

    private var sourceHash: String {
        guard let preview = state.previewImage else { return "<empty>" }
        return FilterThumbnailCache.hash(for: preview)
    }

    private func thumbnail(for entry: FilterEntry) -> NSImage? {
        guard let preview = state.previewImage else { return nil }
        return cache.thumbnail(for: entry, source: preview, sourceHash: sourceHash)
    }
}

/// One row in the filter rail — thumbnail above, name below, optional
/// highlight ring when selected.
private struct FilterRailCell: View {
    let entry: FilterEntry
    let thumbnail: NSImage?
    let isSelected: Bool
    let action: () -> Void

    private static let thumbnailSize: CGFloat = FilterThumbnailCache.thumbnailSize
    private static let cornerRadius: CGFloat = 10

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                ZStack {
                    RoundedRectangle(cornerRadius: Self.cornerRadius)
                        .fill(Color.secondary.opacity(0.15))
                    if let thumbnail {
                        Image(nsImage: thumbnail)
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(
                                width: Self.thumbnailSize,
                                height: Self.thumbnailSize
                            )
                            .clipShape(
                                RoundedRectangle(cornerRadius: Self.cornerRadius)
                            )
                    }
                    if isSelected {
                        RoundedRectangle(cornerRadius: Self.cornerRadius)
                            .strokeBorder(Color.accentColor, lineWidth: 3)
                    } else {
                        RoundedRectangle(cornerRadius: Self.cornerRadius)
                            .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
                    }
                }
                .frame(width: Self.thumbnailSize, height: Self.thumbnailSize)

                Text(entry.displayName)
                    .font(.caption2)
                    .foregroundStyle(isSelected ? Color.accentColor : Color.primary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }
}
