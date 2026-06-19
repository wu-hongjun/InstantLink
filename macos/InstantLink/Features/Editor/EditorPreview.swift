import CoreImage
import Metal
import MetalKit
import SwiftUI
import os.log

private let mtkLog = Logger(subsystem: "fi.bullpen.instantlink.editor", category: "mtkview")

/// Editor canvas. After multiple iterations of MTKView + CIRenderDestination
/// producing only a black box (see EditorMetalView below — kept for future
/// debug but not used), the canvas now renders via a SwiftUI `Image` driven by
/// a CGImage rasterised on every preview change. Performance is "good enough"
/// for the editor's interactive sliders; we can revisit a GPU live-preview
/// path once the underlying MTKView issue is properly diagnosed.
///
/// Plan 047 §Q4 (film-frame in canvas): the Photos-style editor canvas is
/// pixel-accurate and intentionally does NOT render an Instax film border —
/// the simulated frame stays in the main-window queue preview, not here.
struct EditorPreview: View {
    @ObservedObject var state: EditorViewState

    /// Shared CIContext for rasterisation. CPU-backed (default) is fine here;
    /// the bottleneck is the SwiftUI Image redraw, not the render itself.
    private static let renderContext: CIContext = {
        if let device = MTLCreateSystemDefaultDevice() {
            return CIContext(mtlDevice: device, options: [.cacheIntermediates: true])
        }
        return CIContext(options: [.cacheIntermediates: true])
    }()

    var body: some View {
        Group {
            if let ci = state.renderedPreview ?? state.previewImage,
               let cg = Self.renderContext.createCGImage(ci, from: ci.extent) {
                Image(cg, scale: 1.0, label: Text(""))
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: .fit)
                    .scaleEffect(pow(2.0, state.zoomLevel))
            } else {
                Color.clear
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Minimal MTKView subclass that knows how to render a `CIImage` aspect-fitted
/// into its drawable using `CIRenderDestination`.
final class EditorMetalView: MTKView {
    private let ciContext: CIContext
    private let commandQueue: MTLCommandQueue?
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
        let queue = device.makeCommandQueue()
        commandQueue = queue
        if let queue {
            ciContext = CIContext(
                mtlCommandQueue: queue,
                options: [
                    .workingColorSpace: ColorSpaces.linearSRGB,
                    .cacheIntermediates: true,
                ]
            )
        } else {
            mtkLog.error("Failed to create Metal command queue for editor preview")
            ciContext = CIContext(
                mtlDevice: device,
                options: [
                    .workingColorSpace: ColorSpaces.linearSRGB,
                    .cacheIntermediates: true,
                ]
            )
        }
        super.init(frame: .zero, device: device)
        framebufferOnly = false
        isPaused = true
        enableSetNeedsDisplay = true
        preferredFramesPerSecond = 60
        // Plan 049 follow-up: the original `.bgra8Unorm` (linear) format
        // combined with a `CIRenderDestination.colorSpace = sRGB` meant
        // CI was sRGB-encoding pixels into a texture CALayer treated as
        // linear — the texture stayed at clear color (visible as a black
        // box). `.bgra8Unorm_srgb` matches what the destination is
        // emitting; CALayer reads it as sRGB and composits correctly.
        colorPixelFormat = .bgra8Unorm_srgb
        autoResizeDrawable = true
        layer?.isOpaque = true
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
              let commandQueue,
              let buffer = commandQueue.makeCommandBuffer() else {
            mtkLog.error("draw(\(rect.width)x\(rect.height)): no drawable, command queue, or command buffer")
            return
        }

        let drawableSize = CGSize(
            width: CGFloat(drawable.texture.width),
            height: CGFloat(drawable.texture.height)
        )
        mtkLog.info("draw(\(rect.width)x\(rect.height)) drawable=\(drawableSize.width)x\(drawableSize.height) image=\(self.image == nil ? "nil" : String(format: "%.0fx%.0f", self.image!.extent.width, self.image!.extent.height))")

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
                mtkLog.info("startTask submitted: scale=\(scale) positioned extent=\(positioned.extent.width)x\(positioned.extent.height) at (\(positioned.extent.origin.x),\(positioned.extent.origin.y))")
            } catch {
                mtkLog.error("CIContext.startTask FAILED: \(error.localizedDescription)")
            }
        }

        buffer.present(drawable)
        buffer.commit()
    }
}
