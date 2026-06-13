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
    @Published var sourceImage: CIImage?
    @Published var previewImage: CIImage?
    @Published var renderedPreview: CIImage?

    let history = AdjustmentHistory()
    let pipeline = AdjustmentPipeline()

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
        // 60 Hz frame so dragging coalesces cleanly.
        Publishers.CombineLatest($adjustments, $crop)
            .dropFirst()
            .debounce(for: .milliseconds(16), scheduler: DispatchQueue.main)
            .sink { [weak self] _, _ in
                guard let self else { return }
                self.scheduleRender()
                if !self.isRestoring {
                    self.history.commitDebounced(self.snapshot())
                }
            }
            .store(in: &cancellables)

        $previewImage
            .dropFirst()
            .sink { [weak self] _ in self?.scheduleRender() }
            .store(in: &cancellables)

        history.reset(to: snapshot())
    }

    deinit {
        renderTask?.cancel()
    }

    /// Capture the current editable state.
    func snapshot() -> EditorSnapshot {
        EditorSnapshot(adjustments: adjustments, crop: crop)
    }

    /// Restore a snapshot without re-pushing it onto the history stack.
    func apply(_ snap: EditorSnapshot) {
        isRestoring = true
        adjustments = snap.adjustments
        crop = snap.crop
        isRestoring = false
    }

    /// Load the editor's source image, build the downsampled preview, and seed
    /// history with the starting snapshot.
    func loadSource(_ image: NSImage) {
        guard let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let cg = bitmap.cgImage else {
            sourceImage = nil
            previewImage = nil
            renderedPreview = nil
            return
        }
        loadSource(CIImage(cgImage: cg))
    }

    func loadSource(_ image: CIImage) {
        sourceImage = image
        previewImage = downsampledPreview(from: image)
        adjustments = .neutral
        crop = .neutral
        history.reset(to: snapshot())
        scheduleRender()
    }

    func undo() {
        if let snap = history.undo() { apply(snap) }
    }

    func redo() {
        if let snap = history.redo() { apply(snap) }
    }

    /// Reset adjustments + crop back to neutral and commit one history entry.
    func revert() {
        let snap = EditorSnapshot.neutral
        apply(snap)
        history.commit(snap)
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
