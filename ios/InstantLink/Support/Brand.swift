import SwiftUI

// InstantLink brand tokens and mark. Palette source: brand/palette.md.
// Safelight amber-red #E0552B is the single brand accent (also the AccentColor
// asset that tints controls). It is a BRAND colour, not a status colour —
// success/ready stays green, warnings/errors stay their semantic hues.
//
// Copyright © 2026 InstantLink.

extension Color {
    /// Safelight amber-red — the single brand accent. Mirrors the AccentColor asset.
    static let brandAccent = Color(red: 0xE0 / 255, green: 0x55 / 255, blue: 0x2B / 255)
    /// Warm photographic near-black (the instant-photo frame on light).
    static let brandInk = Color(red: 0x1A / 255, green: 0x16 / 255, blue: 0x13 / 255)
    /// The dark "photo" area inside the frame.
    static let brandWindow = Color(red: 0x14 / 255, green: 0x11 / 255, blue: 0x0E / 255)
    /// Warm film-bone ivory (light surfaces).
    static let brandBone = Color(red: 0xF1 / 255, green: 0xEA / 255, blue: 0xDA / 255)
}

/// The InstantLink mark: a flat instant-photo frame (Instax proportion, thick
/// bottom lip) with a camera aperture cut into the photo window. Vectored from
/// brand/instantlink-mark.svg (512×512 viewBox, light variant) so it stays
/// crisp at any size and reads on light surfaces.
struct BrandMark: View {
    var size: CGFloat = 44

    var body: some View {
        Canvas { context, canvasSize in
            let s = canvasSize.width / 512

            // Instant-photo frame (ink) + photo window (bone), leaving the lip.
            context.fill(
                Path(roundedRect: CGRect(x: 118, y: 86, width: 276, height: 340).scaled(s), cornerRadius: 32 * s),
                with: .color(.brandInk)
            )
            context.fill(
                Path(roundedRect: CGRect(x: 150, y: 118, width: 212, height: 212).scaled(s), cornerRadius: 18 * s),
                with: .color(.brandBone)
            )

            // Aperture: amber lens + a negative-space iris (bone blades + hex).
            let cx = 256.0, cy = 224.0, r = 64.0, rOpen = 64.0 * 0.383, phi = 40.0
            context.fill(
                Path(ellipseIn: CGRect(x: (cx - r) * s, y: (cy - r) * s, width: 2 * r * s, height: 2 * r * s)),
                with: .color(.brandAccent)
            )
            func pt(_ radius: Double, _ deg: Double) -> CGPoint {
                let a = deg * .pi / 180
                return CGPoint(x: (cx + radius * cos(a)) * s, y: (cy + radius * sin(a)) * s)
            }
            var hex = Path()
            for k in 0..<6 {
                let p = pt(rOpen, Double(k) * 60)
                if k == 0 { hex.move(to: p) } else { hex.addLine(to: p) }
            }
            hex.closeSubpath()
            for k in 0..<6 {
                var blade = Path()
                blade.move(to: pt(rOpen, Double(k) * 60))
                blade.addLine(to: pt(r, Double(k) * 60 + phi))
                context.stroke(blade, with: .color(.brandBone), style: StrokeStyle(lineWidth: 7 * s, lineCap: .round))
            }
            context.fill(hex, with: .color(.brandBone))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

private extension CGRect {
    func scaled(_ scale: CGFloat) -> CGRect {
        CGRect(x: minX * scale, y: minY * scale, width: width * scale, height: height * scale)
    }
}
