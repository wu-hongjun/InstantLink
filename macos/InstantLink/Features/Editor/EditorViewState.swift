import AppKit
import Combine
import CoreImage
import Foundation
import SwiftUI

/// Observable state for the new Photos-style editor shell. Holds the source
/// image, downsampled preview, current snapshot, undo / redo history, and the
/// post-pipeline `renderedPreview` consumed by `EditorPreview`.
@MainActor
final class EditorViewState: ObservableObject {
    @Published var activeTab: EditorTab = .adjust
    @Published var adjustments: AdjustmentState = .neutral
    @Published var crop: CropState = .neutral
    @Published var overlays: [OverlayItem] = []
    @Published var selectedOverlayID: UUID?
    /// Selected filter ID from `FilterCatalog`, or `nil` for "no filter".
    /// When a B&W filter is selected, the Adjust B&W stack is suppressed in
    /// the pipeline (locked decision Q9, plan 048 PR #15).
    @Published var filterID: String?
    @Published var sourceImage: CIImage?
    @Published var previewImage: CIImage?
    @Published var renderedPreview: CIImage?
    /// Canvas zoom slider position (`-1…+1`, neutral `0`). Drives an extra
    /// scale factor on top of the MTKView's aspect-fit display; positive
    /// zooms in, negative zooms out. Wired by `EditorShellTopBar` (plan 049).
    @Published var zoomLevel: Double = 0

    let history = AdjustmentHistory()
    let pipeline = AdjustmentPipeline()

    /// Shared coordinator for the editor's eyedropper UX (PR #12 of plan 048).
    /// White Balance, Curves point pickers (PR #5), Selective Color wells
    /// (PR #10), and Red Eye manual mode (PR #11) all activate the same
    /// `EyedropperOverlay` via this manager.
    let eyedropperManager = EyedropperManager()

    /// Long-side cap (in pixels) for the cached preview image.
    static let previewLongSide: CGFloat = 2048

    private var renderTask: Task<Void, Never>?
    private var cancellables: Set<AnyCancellable> = []
    /// Reentry guard for `apply()`. Note: the 16 ms debounce can fire after this
    /// flag is reset; undo/redo correctness depends on `AdjustmentHistory.commit`'s
    /// dedup check, not on this guard's timing alone.
    private var isRestoring = false

    init() {
        // Re-render whenever a user-visible field changes. 16 ms matches one
        // 60 Hz frame so dragging coalesces cleanly. Overlay edits also push
        // through so the live preview updates with the Annotate tab. Filter
        // changes (PR #15) also live-update the canvas.
        Publishers.CombineLatest4($adjustments, $crop, $overlays, $filterID)
            .dropFirst()
            .debounce(for: .milliseconds(16), scheduler: DispatchQueue.main)
            .sink { [weak self] _, _, _, _ in
                guard let self else { return }
                self.scheduleRender()
                if !self.isRestoring {
                    self.history.commitDebounced(self.snapshot())
                }
            }
            .store(in: &cancellables)

        // Plan 049: do NOT `dropFirst()` here. The very first emission of
        // `previewImage` is the freshly-downsampled source produced inside
        // `loadSource`. Dropping it meant the editor's initial render only
        // happened via the explicit `scheduleRender()` call at the end of
        // `loadSource` — which races with the CombineLatest4 sink for the
        // same Task slot. In the v0.1.45 build the race surfaced as a blank
        // canvas. Letting every `previewImage` change schedule a render keeps
        // the contract simple: "preview source changed → re-render".
        $previewImage
            .sink { [weak self] _ in self?.scheduleRender() }
            .store(in: &cancellables)

        // Keep `selectedOverlayID` consistent when the overlay list mutates
        // (deletion clears stale IDs).
        $overlays
            .sink { [weak self] items in
                guard let self else { return }
                if let id = self.selectedOverlayID,
                   !items.contains(where: { $0.id == id }) {
                    self.selectedOverlayID = items.last?.id
                }
            }
            .store(in: &cancellables)

        history.reset(to: snapshot())
    }

    deinit {
        renderTask?.cancel()
    }

    /// Capture the current editable state.
    func snapshot() -> EditorSnapshot {
        EditorSnapshot(
            adjustments: adjustments,
            crop: crop,
            filterID: filterID,
            overlays: overlays
        )
    }

    /// Restore a snapshot without re-pushing it onto the history stack.
    func apply(_ snap: EditorSnapshot) {
        isRestoring = true
        adjustments = snap.adjustments
        crop = snap.crop
        overlays = snap.overlays
        filterID = snap.filterID
        if let id = selectedOverlayID,
           !snap.overlays.contains(where: { $0.id == id }) {
            selectedOverlayID = snap.overlays.last?.id
        }
        isRestoring = false
    }

    /// Load the editor's source image, build the downsampled preview, and seed
    /// history with the starting snapshot. Optional `initialSnapshot` restores
    /// per-image state on reopen (locked decision Q3 — plan 048 PR #14).
    func loadSource(_ image: NSImage, initialSnapshot: EditorSnapshot? = nil) {
        guard let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let cg = bitmap.cgImage else {
            sourceImage = nil
            previewImage = nil
            renderedPreview = nil
            return
        }
        loadSource(CIImage(cgImage: cg), initialSnapshot: initialSnapshot)
    }

    func loadSource(_ image: CIImage, initialSnapshot: EditorSnapshot? = nil) {
        sourceImage = image
        previewImage = downsampledPreview(from: image)
        let snap = initialSnapshot ?? .neutral
        isRestoring = true
        adjustments = snap.adjustments
        crop = snap.crop
        overlays = snap.overlays
        filterID = snap.filterID
        selectedOverlayID = snap.overlays.last?.id
        isRestoring = false
        history.reset(to: snapshot())
        scheduleRender()
    }

    func undo() {
        if let snap = history.undo() { apply(snap) }
    }

    func redo() {
        if let snap = history.redo() { apply(snap) }
    }

    /// Reset adjustments + crop + overlays back to neutral and commit one
    /// history entry.
    func revert() {
        let snap = EditorSnapshot.neutral
        apply(snap)
        history.commit(snap)
    }

    // MARK: - Overlay mutation helpers

    var selectedOverlay: OverlayItem? {
        guard let id = selectedOverlayID else { return nil }
        return overlays.first(where: { $0.id == id })
    }

    func selectOverlay(_ id: UUID?) {
        selectedOverlayID = id
    }

    func addOverlay(_ overlay: OverlayItem) {
        var item = overlay
        item.zIndex = (overlays.map(\.zIndex).max() ?? -1) + 1
        overlays.append(item)
        selectedOverlayID = item.id
    }

    func deleteOverlay(id: UUID) {
        overlays.removeAll { $0.id == id }
    }

    func updateOverlay(id: UUID, _ mutate: (inout OverlayItem) -> Void) {
        guard let index = overlays.firstIndex(where: { $0.id == id }) else { return }
        var updated = overlays[index]
        mutate(&updated)
        if updated.aspectRatioReference == nil || !updated.preservesAspectRatio {
            updated.syncAspectRatioToPlacement()
        }
        updated.placement = updated.placement.clamped
        overlays[index] = updated
    }

    func updateSelectedOverlay(_ mutate: (inout OverlayItem) -> Void) {
        guard let id = selectedOverlayID else { return }
        updateOverlay(id: id, mutate)
    }

    func moveSelectedOverlay(forward: Bool) {
        guard let id = selectedOverlayID,
              let index = overlays.firstIndex(where: { $0.id == id }) else { return }
        if forward {
            guard index < overlays.count - 1 else { return }
            overlays.swapAt(index, index + 1)
        } else {
            guard index > 0 else { return }
            overlays.swapAt(index, index - 1)
        }
        for (i, _) in overlays.enumerated() {
            overlays[i].zIndex = i
        }
    }

    func duplicateSelectedOverlay() {
        guard let overlay = selectedOverlay else { return }
        var copy = overlay
        copy.id = UUID()
        copy.createdAt = Date()
        copy.placement.normalizedCenterX = min(0.92, copy.placement.normalizedCenterX + 0.04)
        copy.placement.normalizedCenterY = min(0.92, copy.placement.normalizedCenterY + 0.04)
        addOverlay(copy)
    }

    private func scheduleRender() {
        renderTask?.cancel()
        guard let source = previewImage else {
            renderedPreview = nil
            return
        }
        let snap = snapshot()
        let pipeline = pipeline
        renderTask = Task { @MainActor [weak self] in
            let composed = pipeline.compose(source, state: snap)
            guard !Task.isCancelled else { return }
            self?.renderedPreview = composed
        }
    }

    private func downsampledPreview(from image: CIImage) -> CIImage {
        let extent = image.extent
        let longSide = max(extent.width, extent.height)
        guard longSide > Self.previewLongSide else { return image }
        let scale = Self.previewLongSide / longSide
        let filter = CIFilter(name: "CILanczosScaleTransform")
        filter?.setValue(image, forKey: kCIInputImageKey)
        filter?.setValue(scale, forKey: kCIInputScaleKey)
        filter?.setValue(1.0, forKey: kCIInputAspectRatioKey)
        return filter?.outputImage ?? image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    }
}
