import CoreGraphics
import SwiftUI

/// SwiftUI canvas that edits one channel of `AdjustmentState.Curves` as a
/// monotone cubic Hermite spline. Plan 048 PR #5.
///
/// Interactions:
/// - Drag a knot to move it (endpoints constrained to their edge).
/// - Drag a knot far off the canvas to delete it (endpoints excepted).
/// - Click on the empty curve area to add a knot at that input value.
/// - Maximum 16 knots per channel (matches Photoshop's cap).
struct CurvePointEditor: View {
    /// Binding to the channel's knot array (`.master` / `.red` / `.green` /
    /// `.blue` in `AdjustmentState.Curves`).
    @Binding var points: [CGPoint]
    /// Stroke color for the spline.
    var stroke: Color = .white

    /// Hit radius (in canvas pt) for grabbing a knot. Photos uses ~10 pt;
    /// 14 gives slightly more trackpad slack.
    private let hitRadius: CGFloat = 14
    /// Drag distance off-canvas after which a knot is dropped.
    private let deleteSlack: CGFloat = 28
    /// Maximum knots per channel (Photoshop convention, plan 048).
    private let maxPoints: Int = 16

    @State private var dragIndex: Int?
    @State private var dragOffscreen: Bool = false

    var body: some View {
        GeometryReader { geo in
            ZStack {
                gridCanvas(size: geo.size)
                splineCanvas(size: geo.size)
                pointsCanvas(size: geo.size)
            }
            .contentShape(Rectangle())
            .gesture(dragGesture(in: geo.size))
        }
    }

    // MARK: - Drawing

    private func gridCanvas(size: CGSize) -> some View {
        Canvas { ctx, sz in
            var path = Path()
            // Diagonal reference.
            path.move(to: CGPoint(x: 0, y: sz.height))
            path.addLine(to: CGPoint(x: sz.width, y: 0))
            ctx.stroke(path, with: .color(.white.opacity(0.15)), lineWidth: 1)
            // 4×4 grid.
            for i in 1...3 {
                let xs = sz.width * CGFloat(i) / 4
                let ys = sz.height * CGFloat(i) / 4
                var grid = Path()
                grid.move(to: CGPoint(x: xs, y: 0))
                grid.addLine(to: CGPoint(x: xs, y: sz.height))
                grid.move(to: CGPoint(x: 0, y: ys))
                grid.addLine(to: CGPoint(x: sz.width, y: ys))
                ctx.stroke(grid, with: .color(.white.opacity(0.08)), lineWidth: 1)
            }
        }
        .frame(width: size.width, height: size.height)
    }

    private func splineCanvas(size: CGSize) -> some View {
        let spline = MonotoneSpline(points: points)
        return Canvas { ctx, sz in
            var path = Path()
            let samples = 96
            for i in 0...samples {
                let nx = Double(i) / Double(samples)
                let ny = spline.evaluate(nx)
                let px = CGFloat(nx) * sz.width
                let py = (1 - CGFloat(ny)) * sz.height
                if i == 0 { path.move(to: CGPoint(x: px, y: py)) }
                else      { path.addLine(to: CGPoint(x: px, y: py)) }
            }
            ctx.stroke(path, with: .color(stroke), lineWidth: 1.5)
        }
        .frame(width: size.width, height: size.height)
    }

    private func pointsCanvas(size: CGSize) -> some View {
        Canvas { ctx, sz in
            for (i, p) in points.enumerated() {
                let cx = CGFloat(p.x) * sz.width
                let cy = (1 - CGFloat(p.y)) * sz.height
                let r: CGFloat = (dragIndex == i) ? 5 : 3.5
                let rect = CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2)
                ctx.fill(Path(ellipseIn: rect), with: .color(.white))
                ctx.stroke(Path(ellipseIn: rect), with: .color(.black.opacity(0.6)), lineWidth: 1)
            }
        }
        .frame(width: size.width, height: size.height)
    }

    // MARK: - Gestures

    private func dragGesture(in size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                handleDrag(value: value, size: size, isFirst: dragIndex == nil && value.translation == .zero)
            }
            .onEnded { value in
                handleDragEnd(value: value, size: size)
            }
    }

    private func handleDrag(value: DragGesture.Value, size: CGSize, isFirst: Bool) {
        if dragIndex == nil {
            // First contact: either grab an existing point or add a new one.
            if let idx = hitTest(value.startLocation, size: size) {
                dragIndex = idx
            } else if points.count < maxPoints {
                // Add a new point at the contact's input value, slot it in
                // monotonically.
                let nx = clamp01(Double(value.startLocation.x / size.width))
                let ny = clamp01(1 - Double(value.startLocation.y / size.height))
                insertSorted(CGPoint(x: nx, y: ny))
                dragIndex = points.firstIndex(where: { abs($0.x - nx) < 1e-6 && abs($0.y - ny) < 1e-6 })
            } else {
                return
            }
        }
        guard let idx = dragIndex else { return }

        let canvas = CGRect(origin: .zero, size: size)
        let p = value.location
        let off = !canvas.insetBy(dx: -deleteSlack, dy: -deleteSlack).contains(p)
        dragOffscreen = off && !isEndpoint(idx)

        // Compute the new normalized position.
        var nx = clamp01(Double(p.x / size.width))
        let ny = clamp01(1 - Double(p.y / size.height))

        // Endpoint constraints: bottom-left rides the left edge (x = 0) and
        // can shift along it; top-right rides the right edge (x = 1).
        if idx == 0 {
            nx = 0
        } else if idx == points.count - 1 {
            nx = 1
        } else {
            // Maintain monotone x order against neighbours.
            let leftX = points[idx - 1].x + 1e-3
            let rightX = points[idx + 1].x - 1e-3
            nx = max(Double(leftX), min(Double(rightX), nx))
        }
        points[idx] = CGPoint(x: nx, y: ny)
    }

    private func handleDragEnd(value: DragGesture.Value, size: CGSize) {
        defer {
            dragIndex = nil
            dragOffscreen = false
        }
        guard let idx = dragIndex else { return }
        if dragOffscreen && !isEndpoint(idx) {
            points.remove(at: idx)
        }
    }

    // MARK: - Helpers

    private func hitTest(_ p: CGPoint, size: CGSize) -> Int? {
        var bestIdx: Int? = nil
        var bestDist: CGFloat = hitRadius
        for (i, knot) in points.enumerated() {
            let cx = CGFloat(knot.x) * size.width
            let cy = (1 - CGFloat(knot.y)) * size.height
            let dx = p.x - cx
            let dy = p.y - cy
            let d = sqrt(dx * dx + dy * dy)
            if d <= bestDist {
                bestDist = d
                bestIdx = i
            }
        }
        return bestIdx
    }

    private func isEndpoint(_ idx: Int) -> Bool {
        idx == 0 || idx == points.count - 1
    }

    private func insertSorted(_ p: CGPoint) {
        var inserted = false
        for i in 0..<points.count {
            if p.x < points[i].x {
                points.insert(p, at: i)
                inserted = true
                break
            }
        }
        if !inserted { points.append(p) }
    }

    private func clamp01(_ x: Double) -> Double {
        x < 0 ? 0 : (x > 1 ? 1 : x)
    }
}
