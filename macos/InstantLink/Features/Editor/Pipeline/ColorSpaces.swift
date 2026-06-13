import CoreGraphics
import CoreImage

/// Color-space conversion helpers used to bracket sub-pipelines that need to
/// run in sRGB-gamma vs the editor's working linear sRGB space.
enum ColorSpaces {
    static let linearSRGB: CGColorSpace = CGColorSpace(name: CGColorSpace.extendedLinearSRGB)
        ?? CGColorSpaceCreateDeviceRGB()

    static let sRGB: CGColorSpace = CGColorSpace(name: CGColorSpace.sRGB)
        ?? CGColorSpaceCreateDeviceRGB()

    /// Reinterpret an image as if it lived in linear sRGB.
    static func toLinear(_ image: CIImage) -> CIImage {
        image.matchedFromWorkingSpace(to: linearSRGB) ?? image
    }

    /// Reinterpret an image as if it lived in sRGB-gamma.
    static func toSRGB(_ image: CIImage) -> CIImage {
        image.matchedFromWorkingSpace(to: sRGB) ?? image
    }
}
