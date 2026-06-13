import CoreGraphics
import Foundation

/// Crop / geometry state. PR #1 ships only the neutral identity; PR #2 fills in
/// aspect, straighten, perspective, flip, rotate, and frame fields.
struct CropState: Equatable, Codable {
    static let neutral = CropState()
}
