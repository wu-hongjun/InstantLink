import CoreGraphics
import CoreImage
import Foundation

/// Geometry pipeline for the Crop tab.
///
/// Composition order (matches Photos — plan 048 PR #2):
/// 1. Lossless 90° rotation (n × π/2)
/// 2. Flip horizontal / vertical
/// 3. Straighten rotation (−45…+45°)
/// 4. Perspective (CIPerspectiveTransform) when V/H skew ≠ 0
/// 5. Crop to the user-chosen normalized rect, denormalized against the
///    post-transform extent and clamped to it.
enum CropPipeline {

    /// Maximum keystone offset, expressed as a fraction of the corresponding
    /// edge length. ±1 slider value pulls a corner in by this much.
    private static let maxKeystoneFraction: CGFloat = 0.3

    static func apply(_ image: CIImage, _ state: CropState) -> CIImage {
        let source = image
        let sourceExtent = source.extent
        guard sourceExtent.width > 0, sourceExtent.height > 0 else { return source }

        // Step 1+2+3: collapse rotate90 + flip + straighten into a single affine.
        let affine = composeAffineTransform(state: state, extent: sourceExtent)
        var working = source.transformed(by: affine)

        // Step 4: optional perspective.
        if state.verticalSkew != 0 || state.horizontalSkew != 0 {
            working = applyPerspective(working, state: state)
        }

        // Step 5: crop to the user frame.
        let extent = working.extent
        guard extent.width > 0, extent.height > 0 else { return working }
        let cropRect = denormalize(state.frame, into: extent)
        if cropRect.width <= 0 || cropRect.height <= 0 { return working }
        return working.cropped(to: cropRect)
    }

    // MARK: - Affine composition

    /// Builds the single affine transform that applies rotate-90 quarters,
    /// horizontal/vertical flips, and the straighten rotation around the
    /// center of the source image, returning a transform with origin at (0,0).
    private static func composeAffineTransform(state: CropState, extent: CGRect) -> CGAffineTransform {
        let w = extent.width
        let h = extent.height
        let cx = extent.midX
        let cy = extent.midY

        // Start centered at origin.
        var t = CGAffineTransform(translationX: -cx, y: -cy)

        // Spec order (research §"Order of operations"): rotate-90 first, then
        // flip, then straighten. Swapping flip/rotate-90 changes which axis
        // gets mirrored when both are active (e.g. Flip-H after Rotate-90 CCW
        // yields a different result than the reverse), so this order matters.
        let quarters = ((state.rotate90Quarter % 4) + 4) % 4
        if quarters != 0 {
            let angle = CGFloat(quarters) * (.pi / 2)
            t = t.concatenating(CGAffineTransform(rotationAngle: angle))
        }

        if state.flipHorizontal {
            t = t.concatenating(CGAffineTransform(scaleX: -1, y: 1))
        }
        if state.flipVertical {
            t = t.concatenating(CGAffineTransform(scaleX: 1, y: -1))
        }

        if state.straightenDegrees != 0 {
            let radians = CGFloat(state.straightenDegrees) * (.pi / 180)
            t = t.concatenating(CGAffineTransform(rotationAngle: radians))
        }

        // Determine the post-rotation bounding-box dimensions so we can
        // translate the result back into the positive quadrant.
        let outSize = boundingSize(w: w, h: h, quarters: quarters, straightenDeg: state.straightenDegrees)
        t = t.concatenating(CGAffineTransform(translationX: outSize.width / 2, y: outSize.height / 2))
        return t
    }

    private static func boundingSize(w: CGFloat, h: CGFloat, quarters: Int, straightenDeg: Double) -> CGSize {
        let (rw, rh): (CGFloat, CGFloat)
        if quarters % 2 == 1 {
            rw = h; rh = w
        } else {
            rw = w; rh = h
        }
        if straightenDeg == 0 {
            return CGSize(width: rw, height: rh)
        }
        let theta = abs(CGFloat(straightenDeg) * (.pi / 180))
        let c = cos(theta)
        let s = sin(theta)
        return CGSize(width: rw * c + rh * s, height: rw * s + rh * c)
    }

    // MARK: - Perspective

    /// Apply a keystone transform driven by the V / H skew sliders. The four
    /// corners are pulled inward by a fraction of the corresponding edge.
    ///
    /// Sign convention:
    /// - `verticalSkew > 0`: narrow the top → forward-leaning building stands
    ///   upright.
    /// - `verticalSkew < 0`: narrow the bottom.
    /// - `horizontalSkew > 0`: narrow the right edge.
    /// - `horizontalSkew < 0`: narrow the left edge.
    private static func applyPerspective(_ image: CIImage, state: CropState) -> CIImage {
        let extent = image.extent
        let w = extent.width
        let h = extent.height
        let x0 = extent.minX
        let y0 = extent.minY

        let v = CGFloat(max(-1.0, min(1.0, state.verticalSkew))) * maxKeystoneFraction
        let h2 = CGFloat(max(-1.0, min(1.0, state.horizontalSkew))) * maxKeystoneFraction

        // Inset amounts per edge.
        let topInset    = max(0, v) * w     // v > 0 narrows top
        let bottomInset = max(0, -v) * w    // v < 0 narrows bottom
        let leftInset   = max(0, -h2) * h   // h < 0 narrows left
        let rightInset  = max(0, h2) * h    // h > 0 narrows right

        let topLeft     = CIVector(x: x0 + topInset,        y: y0 + h - leftInset)
        let topRight    = CIVector(x: x0 + w - topInset,    y: y0 + h - rightInset)
        let bottomLeft  = CIVector(x: x0 + bottomInset,     y: y0 + leftInset)
        let bottomRight = CIVector(x: x0 + w - bottomInset, y: y0 + rightInset)

        let warped = image.applyingFilter("CIPerspectiveTransform", parameters: [
            "inputTopLeft":     topLeft,
            "inputTopRight":    topRight,
            "inputBottomLeft":  bottomLeft,
            "inputBottomRight": bottomRight,
        ])
        return warped
    }

    // MARK: - Normalization helpers

    /// Convert the normalized crop rect (origin top-left, range [0,1]) into
    /// CIImage coordinates (origin bottom-left). Clamps to the inscribed
    /// extent.
    private static func denormalize(_ frame: CGRect, into extent: CGRect) -> CGRect {
        let clamped = CGRect(
            x: max(0, min(1, frame.minX)),
            y: max(0, min(1, frame.minY)),
            width: max(0, min(1, frame.width)),
            height: max(0, min(1, frame.height))
        )
        let w = clamped.width * extent.width
        let h = clamped.height * extent.height
        let x = extent.minX + clamped.minX * extent.width
        // Flip Y: SwiftUI frame uses top-left origin; CI uses bottom-left.
        let y = extent.minY + (1 - clamped.minY - clamped.height) * extent.height
        return CGRect(x: x, y: y, width: w, height: h)
    }
}
