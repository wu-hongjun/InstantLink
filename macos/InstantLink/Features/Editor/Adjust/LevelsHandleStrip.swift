import AppKit
import CoreGraphics
import SwiftUI

/// 5 bottom handles + 2 top handles on a horizontal histogram strip — plan
/// 048 PR #5 Levels.
///
/// Bottom handles (left → right): Black point, Shadows, Mid (gamma),
/// Highlights, White point. Top handles: output Black, output White.
/// Option-drag a bottom handle pairs the top counterpart so both move
/// together (Photos behaviour).
struct LevelsHandleStrip: View {
    @Binding var channel: AdjustmentState.Levels.ChannelLevels

    @State private var dragKind: HandleKind?
    @State private var paired: Bool = false

    private enum HandleKind: Hashable {
        case bottomBlack, bottomShadow, bottomMid, bottomHighlight, bottomWhite
        case topBlack, topWhite
        var isBottom: Bool {
            switch self {
            case .bottomBlack, .bottomShadow, .bottomMid, .bottomHighlight, .bottomWhite: return true
            default: return false
            }
        }
    }

    private let topRowH: CGFloat = 14
    private let bodyH: CGFloat = 56
    private let bottomRowH: CGFloat = 14

    var body: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                topHandles(width: geo.size.width)
                    .frame(height: topRowH)
                bodySurface
                    .frame(height: bodyH)
                bottomHandles(width: geo.size.width)
                    .frame(height: bottomRowH)
            }
            .contentShape(Rectangle())
            .gesture(dragGesture(in: geo.size))
        }
        .frame(height: topRowH + bodyH + bottomRowH)
    }

    // MARK: - Drawing

    private var bodySurface: some View {
        RoundedRectangle(cornerRadius: 4)
            .stroke(Color.white.opacity(0.12), lineWidth: 1)
            .background(
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color.black.opacity(0.08))
            )
    }

    private func topHandles(width: CGFloat) -> some View {
        Canvas { ctx, sz in
            drawHandle(ctx: ctx, x: CGFloat(channel.blackOut) * sz.width, y: sz.height - 1, pointingUp: false, color: .black, active: dragKind == .topBlack)
            drawHandle(ctx: ctx, x: CGFloat(channel.whiteOut) * sz.width, y: sz.height - 1, pointingUp: false, color: .white, active: dragKind == .topWhite)
        }
    }

    private func bottomHandles(width: CGFloat) -> some View {
        Canvas { ctx, sz in
            drawHandle(ctx: ctx, x: CGFloat(channel.blackIn)    * sz.width, y: 1, pointingUp: true, color: .black, active: dragKind == .bottomBlack)
            drawHandle(ctx: ctx, x: CGFloat(channel.shadows)    * sz.width, y: 1, pointingUp: true, color: Color(white: 0.3), active: dragKind == .bottomShadow)
            drawHandle(ctx: ctx, x: CGFloat(gammaToX(channel.gamma, blackIn: channel.blackIn, whiteIn: channel.whiteIn)) * sz.width, y: 1, pointingUp: true, color: Color(white: 0.6), active: dragKind == .bottomMid)
            drawHandle(ctx: ctx, x: CGFloat(channel.highlights) * sz.width, y: 1, pointingUp: true, color: Color(white: 0.85), active: dragKind == .bottomHighlight)
            drawHandle(ctx: ctx, x: CGFloat(channel.whiteIn)    * sz.width, y: 1, pointingUp: true, color: .white, active: dragKind == .bottomWhite)
        }
    }

    private func drawHandle(ctx: GraphicsContext, x: CGFloat, y: CGFloat, pointingUp: Bool, color: Color, active: Bool) {
        let w: CGFloat = active ? 11 : 9
        let h: CGFloat = active ? 11 : 9
        var path = Path()
        if pointingUp {
            path.move(to: CGPoint(x: x - w / 2, y: y + h))
            path.addLine(to: CGPoint(x: x + w / 2, y: y + h))
            path.addLine(to: CGPoint(x: x, y: y))
            path.closeSubpath()
        } else {
            path.move(to: CGPoint(x: x - w / 2, y: y - h))
            path.addLine(to: CGPoint(x: x + w / 2, y: y - h))
            path.addLine(to: CGPoint(x: x, y: y))
            path.closeSubpath()
        }
        ctx.fill(path, with: .color(color))
        ctx.stroke(path, with: .color(.white.opacity(0.7)), lineWidth: 1)
    }

    // MARK: - Drag

    private func dragGesture(in size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                handleDrag(value: value, size: size)
            }
            .onEnded { _ in
                dragKind = nil
                paired = false
                snapToNeighbours()
            }
    }

    private func handleDrag(value: DragGesture.Value, size: CGSize) {
        if dragKind == nil {
            dragKind = pickHandle(at: value.startLocation, size: size)
            paired = NSEvent.modifierFlags.contains(.option)
        }
        guard let kind = dragKind else { return }

        let n = clamp01(Double(value.location.x / size.width))
        switch kind {
        case .bottomBlack:
            channel.blackIn = min(n, channel.whiteIn - 1e-3)
            if paired { channel.blackOut = clamp01(channel.blackIn) }
        case .bottomShadow:
            channel.shadows = clamp(n, lower: channel.blackIn, upper: channel.whiteIn)
        case .bottomMid:
            // Mid handle position maps to gamma. Centre = 1.0.
            let position = clamp(n, lower: channel.blackIn + 1e-3, upper: channel.whiteIn - 1e-3)
            channel.gamma = gammaFromX(position, blackIn: channel.blackIn, whiteIn: channel.whiteIn)
        case .bottomHighlight:
            channel.highlights = clamp(n, lower: channel.blackIn, upper: channel.whiteIn)
        case .bottomWhite:
            channel.whiteIn = max(n, channel.blackIn + 1e-3)
            if paired { channel.whiteOut = clamp01(channel.whiteIn) }
        case .topBlack:
            channel.blackOut = min(n, channel.whiteOut - 1e-3)
        case .topWhite:
            channel.whiteOut = max(n, channel.blackOut + 1e-3)
        }
    }

    private func pickHandle(at p: CGPoint, size: CGSize) -> HandleKind? {
        let topRowMax = topRowH
        let bottomRowMin = size.height - bottomRowH
        let isTop = p.y < topRowMax
        let isBottom = p.y > bottomRowMin
        let candidates: [(HandleKind, CGFloat)]
        if isTop {
            candidates = [
                (.topBlack, CGFloat(channel.blackOut) * size.width),
                (.topWhite, CGFloat(channel.whiteOut) * size.width),
            ]
        } else if isBottom {
            candidates = [
                (.bottomBlack,    CGFloat(channel.blackIn)    * size.width),
                (.bottomShadow,   CGFloat(channel.shadows)    * size.width),
                (.bottomMid,      CGFloat(gammaToX(channel.gamma, blackIn: channel.blackIn, whiteIn: channel.whiteIn)) * size.width),
                (.bottomHighlight, CGFloat(channel.highlights) * size.width),
                (.bottomWhite,    CGFloat(channel.whiteIn)    * size.width),
            ]
        } else {
            return nil
        }
        var best: (HandleKind, CGFloat)? = nil
        for c in candidates {
            let d = abs(p.x - c.1)
            if best == nil || d < best!.1 { best = (c.0, d) }
        }
        guard let (kind, dist) = best, dist <= 16 else { return nil }
        return kind
    }

    private func snapToNeighbours() {
        // 5% snap behaviour: if shadows handle ends within 5% of black point,
        // pin it; same for highlights ↔ white point. Pure UX nicety.
        let tolerance: Double = 0.05
        if abs(channel.shadows - channel.blackIn) < tolerance {
            channel.shadows = channel.blackIn
        }
        if abs(channel.highlights - channel.whiteIn) < tolerance {
            channel.highlights = channel.whiteIn
        }
    }

    // MARK: - Gamma ↔ x mapping
    //
    // The mid handle's screen position is the input value `t` whose Levels
    // transfer maps to 0.5. With pure gamma `t^(1/gamma) = 0.5`, so
    // `gamma = ln(t) / ln(0.5)`. The handle's domain is the active input
    // range `[blackIn, whiteIn]`.
    private func gammaToX(_ gamma: Double, blackIn: Double, whiteIn: Double) -> Double {
        let g = max(0.1, min(9.99, gamma))
        let t = pow(0.5, g)
        return blackIn + t * (whiteIn - blackIn)
    }

    private func gammaFromX(_ x: Double, blackIn: Double, whiteIn: Double) -> Double {
        let span = max(1e-3, whiteIn - blackIn)
        var t = (x - blackIn) / span
        t = max(1e-3, min(0.999, t))
        let g = log(t) / log(0.5)
        return max(0.1, min(9.99, g))
    }

    private func clamp01(_ x: Double) -> Double { x < 0 ? 0 : (x > 1 ? 1 : x) }
    private func clamp(_ x: Double, lower: Double, upper: Double) -> Double {
        max(lower, min(upper, x))
    }
}
