import CoreImage
import Metal
import MetalKit
import SwiftUI

/// `NSViewRepresentable` wrapping an `MTKView` that draws a CIImage via
/// `CIRenderDestination`. Runs `isPaused = true` + `enableSetNeedsDisplay = true`
/// so the GPU only wakes when the editor's rendered preview changes.
///
/// Plan 047 §Q4 (film-frame in canvas): the Photos-style editor canvas is
/// pixel-accurate and intentionally does NOT render an Instax film border —
/// the simulated frame stays in the main-window queue preview, not here.
/// Confirmed moot for the new editor in PR #17 of plan 048.
struct EditorPreview: NSViewRepresentable {
    @ObservedObject var state: EditorViewState

    func makeNSView(context: Context) -> EditorMetalView {
        let device = MTLCreateSystemDefaultDevice() ?? MTLCopyAllDevices().first!
        let view = EditorMetalView(device: device)
        view.image = state.renderedPreview ?? state.previewImage
        view.zoom = state.zoomLevel
        return view
    }

    func updateNSView(_ nsView: EditorMetalView, context: Context) {
        nsView.image = state.renderedPreview ?? state.previewImage
        nsView.zoom = state.zoomLevel
    }
}

/// Minimal MTKView subclass that knows how to render a `CIImage` aspect-fitted
/// into its drawable using `CIRenderDestination`.
final class EditorMetalView: MTKView {
    private let ciContext: CIContext
    private let commandQueue: MTLCommandQueue
    private let outputColorSpace: CGColorSpace = ColorSpaces.sRGB

    /// User-facing canvas zoom, `-1…+1` (neutral `0` = aspect-fit). Plan 049:
    /// drives an extra scale factor on top of the aspect-fit scale; positive
    /// values zoom in (1.0 → 2× total), negative zoom out (-1.0 → 0.5×).
    var zoom: Double = 0 {
        didSet {
            if zoom != oldValue {
                setNeedsDisplay(bounds)
            }
        }
    }

    var image: CIImage? {
        didSet {
            // Plan 049: always re-display when `image` changes, including the
            // identity case (`oldValue == nil → image == nil` is filtered, but
            // re-assigning the SAME CIImage during initial layout should still
            // wake the next `draw(_:)` so we don't strand a blank canvas when
            // SwiftUI flushes the first frame).
            if image != oldValue || (image != nil && oldValue == nil) {
                setNeedsDisplay(bounds)
            }
        }
    }

    init(device: MTLDevice) {
        guard let queue = device.makeCommandQueue() else {
            fatalError("Failed to create Metal command queue for editor preview")
        }
        commandQueue = queue
        ciContext = CIContext(
            mtlCommandQueue: queue,
            options: [
                .workingColorSpace: ColorSpaces.linearSRGB,
                .cacheIntermediates: true,
            ]
        )
        super.init(frame: .zero, device: device)
        framebufferOnly = false
        isPaused = true
        enableSetNeedsDisplay = true
        preferredFramesPerSecond = 60
        colorPixelFormat = .bgra8Unorm
        autoResizeDrawable = true
        layer?.isOpaque = false
        // Near-black canvas backdrop matches macOS Photos.app. Plan 049: the
        // alpha-0 clear color in v0.1.45 let the SwiftUI window chrome bleed
        // through, which when combined with the (now-fixed) blank initial
        // render looked like a totally empty canvas. A solid dark clear color
        // means even a missed initial draw shows the canvas, not the window.
        clearColor = MTLClearColor(red: 0.07, green: 0.07, blue: 0.07, alpha: 1)
    }

    required init(coder: NSCoder) {
        fatalError("init(coder:) not used")
    }

    /// Force a redraw the first time the view is laid out at a non-zero size.
    /// MTKView's `setNeedsDisplay` calls issued before SwiftUI assigns the
    /// view a real frame would otherwise be lost.
    override func layout() {
        super.layout()
        if bounds.width > 0, bounds.height > 0 {
            setNeedsDisplay(bounds)
        }
    }

    override func draw(_ rect: CGRect) {
        guard let drawable = currentDrawable,
              let buffer = commandQueue.makeCommandBuffer() else { return }

        let drawableSize = CGSize(
            width: CGFloat(drawable.texture.width),
            height: CGFloat(drawable.texture.height)
        )

        if let image, image.extent.width > 0, image.extent.height > 0 {
            let aspectFit = min(
                drawableSize.width / image.extent.width,
                drawableSize.height / image.extent.height
            )
            // Map zoom (`-1…+1`) onto a 0.5× — 2× multiplier so the slider
            // stays bipolar and centred.
            let zoomMultiplier = pow(2.0, zoom)
            let scale = aspectFit * zoomMultiplier
            let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            let scaledExtent = scaled.extent
            let offsetX = (drawableSize.width - scaledExtent.width) / 2 - scaledExtent.origin.x
            let offsetY = (drawableSize.height - scaledExtent.height) / 2 - scaledExtent.origin.y
            let positioned = scaled.transformed(by: CGAffineTransform(translationX: offsetX, y: offsetY))

            let destination = CIRenderDestination(
                mtlTexture: drawable.texture,
                commandBuffer: buffer
            )
            destination.isFlipped = false
            destination.colorSpace = outputColorSpace

            do {
                _ = try ciContext.startTask(toRender: positioned, to: destination)
            } catch {
                // Drawing errors are non-fatal — fall back to clearing the frame.
            }
        }

        buffer.present(drawable)
        buffer.commit()
    }
}
