import Combine
import Foundation
import simd

/// Observable coordinator for the editor's shared eyedropper UX.
///
/// Owned by `EditorViewState` (one per editor instance). White Balance
/// (PR #12), Curves black/mid/white points (PR #5), Selective Color wells
/// (PR #10), and Red Eye manual mode (PR #11) all activate the same overlay
/// by calling `start(_:onSample:)`. The overlay then intercepts the next
/// canvas click, samples a 3×3 px average from the pre-WB preview image,
/// and pipes the result back via `consume(_:)`.
///
/// Only one active mode at a time — `start` overwrites any previous handler.
@MainActor
final class EyedropperManager: ObservableObject {
    /// Discriminator for the live sampling target. New cases land with their
    /// owning PR (Curves, Selective Color, Red Eye); WB owns the first two
    /// cases shipped with PR #12.
    enum ActiveMode: Equatable {
        case wbNeutral
        case wbSkin
        case curvesBlack
        case curvesMid
        case curvesWhite
        case selectiveColorWell(Int)
        case redEyeManual
    }

    @Published var active: ActiveMode?

    private var onSample: ((SampledRGB) -> Void)?

    /// Begin a sampling session. The supplied closure runs on the main actor
    /// once `consume(_:)` fires.
    func start(_ mode: ActiveMode, onSample: @escaping (SampledRGB) -> Void) {
        self.active = mode
        self.onSample = onSample
    }

    /// Hand a sampled RGBA value to the active section. Clears `active` so
    /// the overlay tears down and a subsequent canvas click is no longer
    /// intercepted.
    func consume(_ rgba: SIMD4<Float>) {
        let sample = SampledRGB(
            red: Double(rgba.x),
            green: Double(rgba.y),
            blue: Double(rgba.z)
        )
        onSample?(sample)
        active = nil
        onSample = nil
    }

    /// Abort the active session without delivering a sample (e.g. Escape key
    /// or the user clicks the same eyedropper button again).
    func cancel() {
        active = nil
        onSample = nil
    }
}
