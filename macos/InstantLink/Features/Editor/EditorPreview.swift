import CoreImage
import Metal
import MetalKit
import SwiftUI

/// `NSViewRepresentable` wrapping an `MTKView` that draws a CIImage via
/// `CIRenderDestination`. Runs `isPaused = true` + `enableSetNeedsDisplay = true`
/// so the GPU only wakes when the editor's rendered preview changes.
struct EditorPreview: NSViewRepresentable {
    @ObservedObject var state: EditorViewState

    func makeNSView(context: Context) -> EditorMetalView {
        let device = MTLCreateSystemDefaultDevice() ?? MTLCopyAllDevices().first!
        let view = EditorMetalView(device: device)
        view.image = state.renderedPreview ?? state.previewImage
        return view
    }

    func updateNSView(_ nsView: EditorMetalView, context: Context) {
        nsView.image = state.renderedPreview ?? state.previewImage
    }
}

/// Minimal MTKView subclass that knows how to render a `CIImage` aspect-fitted
/// into its drawable using `CIRenderDestination`.
final class EditorMetalView: MTKView {
    private let ciContext: CIContext
    private let commandQueue: MTLCommandQueue
    private let outputColorSpace: CGColorSpace = ColorSpaces.sRGB

    var image: CIImage? {
        didSet {
            if image != oldValue {
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
        clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
    }

    required init(coder: NSCoder) {
        fatalError("init(coder:) not used")
    }

    override func draw(_ rect: CGRect) {
        guard let drawable = currentDrawable,
              let buffer = commandQueue.makeCommandBuffer() else { return }

        let drawableSize = CGSize(
            width: CGFloat(drawable.texture.width),
            height: CGFloat(drawable.texture.height)
        )

        if let image, image.extent.width > 0, image.extent.height > 0 {
            let scale = min(
                drawableSize.width / image.extent.width,
                drawableSize.height / image.extent.height
            )
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
