import CoreImage
import Foundation
import simd
import SwiftUI

/// Transparent overlay that captures canvas clicks while
/// `EditorViewState.eyedropperManager.active != nil` and samples a 3×3 px
/// average from the editor's **pre-WB** preview image.
///
/// View-coord → image-coord mapping mirrors the aspect-fit math in
/// `EditorMetalView.draw(_:)`. Sampling reads
/// `EditorViewState.previewImage` (the cached, downsampled source) so the
/// result is idempotent regardless of the current White Balance state —
/// matches the eyedropper contract documented in
/// `docs/research/047-implementation-coreimage-mapping.md` §7.
///
/// Magnifier loupe is deferred to PR #17 polish; v1 shows a plain
/// crosshair cursor while the overlay is active.
struct EyedropperOverlay: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        GeometryReader { geo in
            Rectangle()
                .fill(Color.black.opacity(0.0001)) // hit-test only
                .contentShape(Rectangle())
                .onTapGesture(coordinateSpace: .local) { point in
                    handleTap(at: point, viewSize: geo.size)
                }
        }
        .allowsHitTesting(state.eyedropperManager.active != nil)
    }

    private func handleTap(at point: CGPoint, viewSize: CGSize) {
        guard state.eyedropperManager.active != nil,
              let image = state.previewImage else {
            return
        }

        let extent = image.extent
        guard extent.width > 0, extent.height > 0 else {
            state.eyedropperManager.cancel()
            return
        }

        let scale = min(viewSize.width / extent.width, viewSize.height / extent.height)
        guard scale > 0 else { return }
        let renderedWidth = extent.width * scale
        let renderedHeight = extent.height * scale
        let offsetX = (viewSize.width - renderedWidth) / 2
        let offsetY = (viewSize.height - renderedHeight) / 2

        // Reject clicks that fall in the letterbox margins.
        let localX = point.x - offsetX
        let localY = point.y - offsetY
        guard localX >= 0, localX <= renderedWidth,
              localY >= 0, localY <= renderedHeight else {
            return
        }

        // SwiftUI taps come in top-down; CIImage is y-up.
        let imageX = localX / scale + extent.origin.x
        let imageY = (renderedHeight - localY) / scale + extent.origin.y

        // Position-only modes (Red Eye manual, PR #11) short-circuit the
        // 3×3 color sampling pass and dispatch the image-space click point.
        if state.eyedropperManager.isPositionOnlyMode {
            state.eyedropperManager.consumePoint(CGPoint(x: imageX, y: imageY))
            return
        }

        let sample = sample3x3(in: image, x: imageX, y: imageY)
        state.eyedropperManager.consume(sample)
    }

    /// 3×3 average centered on `(x, y)` in image-space. Reads the
    /// pre-WB `previewImage` directly through a one-shot `CIContext`.
    private func sample3x3(in image: CIImage, x: CGFloat, y: CGFloat) -> SIMD4<Float> {
        let region = CGRect(x: x - 1.5, y: y - 1.5, width: 3, height: 3)
            .intersection(image.extent)
        guard !region.isNull, region.width > 0, region.height > 0 else {
            return .zero
        }

        // Downscale the local 3×3 to 1×1 via Lanczos so the bitmap read
        // yields a single averaged pixel.
        let downscale = 1.0 / max(region.width, region.height)
        let scaled = image
            .cropped(to: region)
            .applyingFilter("CILanczosScaleTransform", parameters: [
                kCIInputScaleKey: downscale,
                kCIInputAspectRatioKey: 1.0,
            ])

        var pixel = SIMD4<Float>(repeating: 0)
        let context = CIContext(options: [
            .workingColorSpace: ColorSpaces.linearSRGB,
            .outputColorSpace: ColorSpaces.sRGB,
        ])
        let readBounds = CGRect(
            x: scaled.extent.origin.x,
            y: scaled.extent.origin.y,
            width: 1,
            height: 1
        )
        context.render(
            scaled,
            toBitmap: &pixel,
            rowBytes: 16,
            bounds: readBounds,
            format: .RGBAf,
            colorSpace: ColorSpaces.sRGB
        )
        return pixel
    }
}
