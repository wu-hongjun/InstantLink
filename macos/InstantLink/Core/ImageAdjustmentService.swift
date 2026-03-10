import AppKit
import CoreImage
import Foundation

enum ImageAdjustmentService {
    private static let context = CIContext(options: nil)

    static func applyExposure(to image: NSImage, ev: Double) -> NSImage? {
        guard abs(ev) > 0.001,
              let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil),
              let adjusted = applyExposure(to: cgImage, ev: ev) else {
            return abs(ev) > 0.001 ? nil : image
        }

        return NSImage(
            cgImage: adjusted,
            size: NSSize(width: adjusted.width, height: adjusted.height)
        )
    }

    static func applyExposure(to cgImage: CGImage, ev: Double) -> CGImage? {
        guard abs(ev) > 0.001 else { return cgImage }

        let input = CIImage(cgImage: cgImage)
        guard let filter = CIFilter(name: "CIExposureAdjust") else { return nil }
        filter.setValue(input, forKey: kCIInputImageKey)
        filter.setValue(ev, forKey: kCIInputEVKey)

        guard let output = filter.outputImage else { return nil }
        return context.createCGImage(output, from: input.extent)
    }
}
