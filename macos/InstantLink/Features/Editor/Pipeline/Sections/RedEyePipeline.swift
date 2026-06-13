import CoreImage
import CoreGraphics
import Foundation

/// Red-eye sub-pipeline per `docs/research/047-photos-adjust-redeye-wb-curves-levels.md` §Red Eye.
///
/// Each correction is an image-space `(point, radius)` record. We pack the
/// centers into a `[CIVector]` and dispatch them through
/// `CIRedEyeCorrection.inputCenters`.
///
/// Note: `CIRedEyeCorrection` is part of Core Image's auto-adjustment family
/// and is technically under-documented (research §Open uncertainties). It
/// works on shipping macOS via `CIFilter(name:)`, but if Apple ever ships a
/// version that drops the by-name lookup we fall back to identity — PR #17
/// fidelity pass can then swap in a custom `CIKernel` red-channel knockdown.
enum RedEyePipeline {
    static func apply(_ image: CIImage, _ s: AdjustmentState.RedEye) -> CIImage {
        guard s.sectionEnabled, !s.corrections.isEmpty else { return image }
        let centers = s.corrections.map { CIVector(x: $0.point.x, y: $0.point.y) }
        guard let filter = CIFilter(name: "CIRedEyeCorrection") else {
            // CIRedEyeCorrection is currently available on every shipping
            // macOS that we target. If Apple ever drops the by-name lookup,
            // a v2 fallback (custom CIKernel red-channel knockdown) would
            // belong here — tracked outside this plan.
            return image
        }
        filter.setValue(image, forKey: kCIInputImageKey)
        filter.setValue(centers, forKey: "inputCenters")
        return filter.outputImage ?? image
    }
}
