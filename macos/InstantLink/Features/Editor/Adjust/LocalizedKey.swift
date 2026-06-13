import SwiftUI

/// Helper so the SwiftUI view sites in the Adjust sections can spell
/// `LocalizedStringKey` for `AdjustmentSlider.label` /
/// `AdjustmentSectionHeader.title` without having to import the runtime
/// `NSLocalizedString` lookup. Mirrors the existing `L(_:)` global but
/// returns the SwiftUI key type.
///
/// Hoisted from `LightSection.swift` (PR #3) so every Adjust section file
/// (Color, Vignette, Sharpen, NR, Definition, …) can reuse it.
@inline(__always)
func L_key(_ key: String) -> LocalizedStringKey {
    LocalizedStringKey(key)
}
