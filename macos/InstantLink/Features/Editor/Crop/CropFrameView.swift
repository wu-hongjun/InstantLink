import SwiftUI

/// SwiftUI overlay sitting on top of the editor canvas while the Crop tab is
/// active. Draws the 8-handle frame, a dim mask outside the frame, and a
/// transient 3×3 rule-of-thirds grid during drag.
///
/// Coordinates: `state.crop.frame` is normalized [0…1] in post-transform image
/// space. The overlay maps that to canvas pixels via the same aspect-fit math
/// used by the underlying MTKView so the frame visually sits over the image.
struct CropFrameView: View {
    @ObservedObject var state: EditorViewState
    @State private var isDragging = false
    @State private var lastDragEndedAt: Date?
    /// Snapshot of `state.crop.frame` taken at the start of each drag so
    /// movement maths use a stable baseline rather than the in-flight value.
    @State private var dragOrigin: CGRect?

    var body: some View {
        GeometryReader { geo in
            let canvasRect = imageRect(in: geo.size)
            let frameRect = self.frameRect(in: canvasRect)
            ZStack {
                dimOverlay(frameRect: frameRect)
                Rectangle()
                    .strokeBorder(Color.white, lineWidth: 1.2)
                    .frame(width: frameRect.width, height: frameRect.height)
                    .position(x: frameRect.midX, y: frameRect.midY)
                    .gesture(bodyDrag(canvasRect: canvasRect))
                if shouldShowGrid {
                    gridLines
                        .frame(width: frameRect.width, height: frameRect.height)
                        .position(x: frameRect.midX, y: frameRect.midY)
                        .allowsHitTesting(false)
                        .transition(.opacity)
                }
                ForEach(Handle.allCases, id: \.self) { h in
                    Circle()
                        .fill(Color.white)
                        .frame(width: handleSize(h), height: handleSize(h))
                        .position(handlePosition(h, in: frameRect))
                        .gesture(handleDrag(handle: h, canvasRect: canvasRect))
                }
            }
            .contentShape(Rectangle())
            .animation(.easeOut(duration: 0.2), value: shouldShowGrid)
        }
    }

    // MARK: - Geometry helpers

    /// Compute the canvas rectangle that contains the image, matching how the
    /// underlying MTKView aspect-fits its source.
    private func imageRect(in size: CGSize) -> CGRect {
        let extent = state.renderedPreview?.extent ?? state.previewImage?.extent
        guard let extent, extent.width > 0, extent.height > 0,
              size.width > 0, size.height > 0 else {
            return CGRect(origin: .zero, size: size)
        }
        let imageAspect = extent.width / extent.height
        let canvasAspect = size.width / size.height
        if imageAspect > canvasAspect {
            let h = size.width / imageAspect
            return CGRect(x: 0, y: (size.height - h) / 2, width: size.width, height: h)
        } else {
            let w = size.height * imageAspect
            return CGRect(x: (size.width - w) / 2, y: 0, width: w, height: size.height)
        }
    }

    private func frameRect(in canvasRect: CGRect) -> CGRect {
        let frame = state.crop.frame
        return CGRect(
            x: canvasRect.minX + frame.minX * canvasRect.width,
            y: canvasRect.minY + frame.minY * canvasRect.height,
            width: frame.width * canvasRect.width,
            height: frame.height * canvasRect.height
        )
    }

    // MARK: - Overlay components

    private func dimOverlay(frameRect: CGRect) -> some View {
        Color.black.opacity(0.45)
            .mask(
                ZStack {
                    Rectangle()
                    Rectangle()
                        .frame(width: frameRect.width, height: frameRect.height)
                        .position(x: frameRect.midX, y: frameRect.midY)
                        .blendMode(.destinationOut)
                }
                .compositingGroup()
            )
            .allowsHitTesting(false)
    }

    private var gridLines: some View {
        GeometryReader { g in
            let w = g.size.width
            let h = g.size.height
            Path { p in
                p.move(to: CGPoint(x: w / 3, y: 0))
                p.addLine(to: CGPoint(x: w / 3, y: h))
                p.move(to: CGPoint(x: 2 * w / 3, y: 0))
                p.addLine(to: CGPoint(x: 2 * w / 3, y: h))
                p.move(to: CGPoint(x: 0, y: h / 3))
                p.addLine(to: CGPoint(x: w, y: h / 3))
                p.move(to: CGPoint(x: 0, y: 2 * h / 3))
                p.addLine(to: CGPoint(x: w, y: 2 * h / 3))
            }
            .stroke(Color.white.opacity(0.6), lineWidth: 0.8)
        }
    }

    private func handleSize(_ h: Handle) -> CGFloat {
        switch h {
        case .topLeft, .topRight, .bottomLeft, .bottomRight: return 12
        case .top, .bottom, .left, .right: return 10
        }
    }

    private func handlePosition(_ h: Handle, in frame: CGRect) -> CGPoint {
        switch h {
        case .topLeft:     return CGPoint(x: frame.minX, y: frame.minY)
        case .topRight:    return CGPoint(x: frame.maxX, y: frame.minY)
        case .bottomLeft:  return CGPoint(x: frame.minX, y: frame.maxY)
        case .bottomRight: return CGPoint(x: frame.maxX, y: frame.maxY)
        case .top:         return CGPoint(x: frame.midX, y: frame.minY)
        case .bottom:      return CGPoint(x: frame.midX, y: frame.maxY)
        case .left:        return CGPoint(x: frame.minX, y: frame.midY)
        case .right:       return CGPoint(x: frame.maxX, y: frame.midY)
        }
    }

    // MARK: - Gestures

    private var shouldShowGrid: Bool {
        if isDragging { return true }
        guard let when = lastDragEndedAt else { return false }
        return Date().timeIntervalSince(when) < 0.4
    }

    private func bodyDrag(canvasRect: CGRect) -> some Gesture {
        DragGesture(minimumDistance: 2)
            .onChanged { value in
                guard canvasRect.width > 0, canvasRect.height > 0 else { return }
                if dragOrigin == nil { dragOrigin = state.crop.frame }
                guard let origin = dragOrigin else { return }
                isDragging = true
                let dx = value.translation.width / canvasRect.width
                let dy = value.translation.height / canvasRect.height
                var f = origin
                f.origin.x = max(0, min(1 - f.width, origin.minX + dx))
                f.origin.y = max(0, min(1 - f.height, origin.minY + dy))
                state.crop.frame = f
            }
            .onEnded { _ in
                isDragging = false
                lastDragEndedAt = Date()
                dragOrigin = nil
            }
    }

    private func handleDrag(handle: Handle, canvasRect: CGRect) -> some Gesture {
        DragGesture(minimumDistance: 1)
            .onChanged { value in
                guard canvasRect.width > 0, canvasRect.height > 0 else { return }
                if dragOrigin == nil { dragOrigin = state.crop.frame }
                guard let origin = dragOrigin else { return }
                isDragging = true
                let dx = value.translation.width / canvasRect.width
                let dy = value.translation.height / canvasRect.height
                state.crop.frame = resize(from: origin, handle: handle, dx: dx, dy: dy)
            }
            .onEnded { _ in
                isDragging = false
                lastDragEndedAt = Date()
                dragOrigin = nil
            }
    }

    private func resize(from original: CGRect, handle: Handle, dx: CGFloat, dy: CGFloat) -> CGRect {
        var minX = original.minX
        var minY = original.minY
        var maxX = original.maxX
        var maxY = original.maxY
        switch handle {
        case .topLeft:
            minX += dx; minY += dy
        case .topRight:
            maxX += dx; minY += dy
        case .bottomLeft:
            minX += dx; maxY += dy
        case .bottomRight:
            maxX += dx; maxY += dy
        case .top:
            minY += dy
        case .bottom:
            maxY += dy
        case .left:
            minX += dx
        case .right:
            maxX += dx
        }
        let minSize: CGFloat = 0.05
        minX = max(0, min(maxX - minSize, minX))
        minY = max(0, min(maxY - minSize, minY))
        maxX = min(1, max(minX + minSize, maxX))
        maxY = min(1, max(minY + minSize, maxY))
        return CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
    }

    enum Handle: CaseIterable {
        case topLeft, top, topRight
        case left, right
        case bottomLeft, bottom, bottomRight
    }
}
