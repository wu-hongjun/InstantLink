import CoreGraphics
import Foundation

/// Crop / geometry state for the Photos-style Crop tab (plan 048 PR #2).
///
/// Frame is normalized [0…1] against the post-transform image extent
/// (rotate90 + flip + straighten + perspective applied first). The crop frame
/// auto-clamps to the inscribed rectangle of that transformed content.
struct CropState: Equatable, Codable {

    /// Aspect-ratio constraint applied to the crop frame.
    ///
    /// Swift's synthesized `Codable` for enum cases needs valid identifiers, so
    /// numeric ratios are encoded as `r16x9`-style names.
    enum Aspect: String, Codable, CaseIterable {
        case original
        case freeform
        case square
        case r16x9
        case r10x8
        case r7x5
        case r4x3
        case r5x3
        case r3x2
        case custom
        case printerMini
        case printerSquare
        case printerWide

        /// Logical width × height ratio in landscape orientation.
        /// `original`, `freeform`, and `custom` return `nil` — they don't carry
        /// a fixed ratio that the picker can compute from the case alone.
        var landscapeRatio: CGSize? {
            switch self {
            case .original, .freeform, .custom: return nil
            case .square:        return CGSize(width: 1, height: 1)
            case .r16x9:         return CGSize(width: 16, height: 9)
            case .r10x8:         return CGSize(width: 10, height: 8)
            case .r7x5:          return CGSize(width: 7, height: 5)
            case .r4x3:          return CGSize(width: 4, height: 3)
            case .r5x3:          return CGSize(width: 5, height: 3)
            case .r3x2:          return CGSize(width: 3, height: 2)
            case .printerMini:   return CGSize(width: 4, height: 3)
            case .printerSquare: return CGSize(width: 1, height: 1)
            case .printerWide:   return CGSize(width: 3, height: 2)
            }
        }
    }

    enum Orientation: String, Codable { case landscape, portrait }

    var aspect: Aspect = .freeform
    var orientation: Orientation = .landscape
    /// Numerator / denominator entered for `Aspect.custom`. Treated as
    /// `width × height` in the current orientation.
    var customAspect: CGSize = CGSize(width: 1, height: 1)

    /// Straighten rotation in degrees, −45…+45.
    var straightenDegrees: Double = 0
    /// Vertical (top/bottom) keystone, −1…+1.
    var verticalSkew: Double = 0
    /// Horizontal (left/right) keystone, −1…+1.
    var horizontalSkew: Double = 0
    var flipHorizontal: Bool = false
    var flipVertical: Bool = false
    /// Lossless 90° rotation count, 0…3 (CCW).
    var rotate90Quarter: Int = 0
    /// Normalized crop rectangle in post-transform coordinates.
    var frame: CGRect = CGRect(x: 0, y: 0, width: 1, height: 1)

    static let neutral = CropState()

    /// Effective width/height ratio after orientation swap. `nil` for
    /// `original`, `freeform`, and invalid custom entries.
    var effectiveRatio: CGSize? {
        let base: CGSize?
        if aspect == .custom {
            base = customAspect.width > 0 && customAspect.height > 0 ? customAspect : nil
        } else {
            base = aspect.landscapeRatio
        }
        guard let ratio = base else { return nil }
        switch orientation {
        case .landscape: return ratio
        case .portrait:  return CGSize(width: ratio.height, height: ratio.width)
        }
    }
}
