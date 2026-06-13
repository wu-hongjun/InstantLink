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
            .onEnded { _ in endDrag() }
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
            .onEnded { _ in endDrag() }
    }

    /// Common end-of-drag handler. Records the drag-end timestamp so the grid
    /// stays visible for a brief fade-out window, then schedules a clearing
    /// pass so SwiftUI re-evaluates `shouldShowGrid` after the window elapses.
    private func endDrag() {
        isDragging = false
        dragOrigin = nil
        let endedAt = Date()
        lastDragEndedAt = endedAt
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.41) {
            // Only clear if no new drag has started in the meantime.
            if lastDragEndedAt == endedAt {
                lastDragEndedAt = nil
            }
        }
    }

    /// Move the active handle (and the perpendicular axes for corners),
    /// clamp to the unit square with a minimum size, then enforce the
    /// active aspect-ratio lock if one is selected.
    private func resize(from original: CGRect, handle: Handle, dx: CGFloat, dy: CGFloat) -> CGRect {
        var minX = original.minX
        var minY = original.minY
        var maxX = original.maxX
        var maxY = original.maxY
        switch handle {
        case .topLeft:     minX += dx; minY += dy
        case .topRight:    maxX += dx; minY += dy
        case .bottomLeft:  minX += dx; maxY += dy
        case .bottomRight: maxX += dx; maxY += dy
        case .top:         minY += dy
        case .bottom:      maxY += dy
        case .left:        minX += dx
        case .right:       maxX += dx
        }
        let minSize: CGFloat = 0.05
        minX = max(0, min(maxX - minSize, minX))
        minY = max(0, min(maxY - minSize, minY))
        maxX = min(1, max(minX + minSize, maxX))
        maxY = min(1, max(minY + minSize, maxY))
        let raw = CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)

        guard let lock = state.crop.effectiveRatio,
              lock.width > 0, lock.height > 0 else {
            return raw
        }
        return applyAspectLock(rect: raw, handle: handle, ratio: lock.width / lock.height)
    }

    /// Constrain `rect` to the given width-to-height `ratio`, anchored so the
    /// side opposite the dragged handle stays in place. Shrinks (preserving
    /// ratio) if clamping would push the rect outside the unit square.
    private func applyAspectLock(rect: CGRect, handle: Handle, ratio: CGFloat) -> CGRect {
        let widthDriven: Bool
        switch handle {
        case .top, .bottom:
            // User moved a horizontal edge → height changed → derive width.
            widthDriven = false
        case .left, .right:
            // User moved a vertical edge → width changed → derive height.
            widthDriven = true
        case .topLeft, .topRight, .bottomLeft, .bottomRight:
            // Corner: pick the axis that needs less correction (the rect's
            // current ratio decides which axis is "too long").
            widthDriven = (rect.width / rect.height) > ratio
        }

        var w = rect.width
        var h = rect.height
        if widthDriven {
            h = w / ratio
        } else {
            w = h * ratio
        }

        var minX = rect.minX
        var minY = rect.minY
        switch handle {
        case .topLeft:     minX = rect.maxX - w; minY = rect.maxY - h
        case .topRight:    minY = rect.maxY - h
        case .bottomLeft:  minX = rect.maxX - w
        case .bottomRight: break
        case .top:         minX = rect.midX - w / 2; minY = rect.maxY - h
        case .bottom:      minX = rect.midX - w / 2
        case .left:        minX = rect.maxX - w; minY = rect.midY - h / 2
        case .right:       minY = rect.midY - h / 2
        }

        var result = CGRect(x: minX, y: minY, width: w, height: h)
        // Clamp to the unit square while preserving the aspect ratio: when an
        // edge falls outside, shrink along the dominant axis and re-derive the
        // other from `ratio`.
        if result.minX < 0 {
            result.origin.x = 0
        }
        if result.minY < 0 {
            result.origin.y = 0
        }
        if result.maxX > 1 {
            result.size.width = 1 - result.minX
            result.size.height = result.size.width / ratio
        }
        if result.maxY > 1 {
            result.size.height = 1 - result.minY
            result.size.width = result.size.height * ratio
        }
        return result
    }

    enum Handle: CaseIterable {
        case topLeft, top, topRight
        case left, right
        case bottomLeft, bottom, bottomRight
    }
}
