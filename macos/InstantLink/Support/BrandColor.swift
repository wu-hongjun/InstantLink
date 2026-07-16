import AppKit
import SwiftUI

extension Color {
    /// The single InstantLink brand / interactive tint — safelight amber-red
    /// `#E0552B` (see `brand/palette.md`). Used across the app's chrome:
    /// pairing/connect, settings, primary actions, selection, and progress.
    /// It is a BRAND colour, not a status colour — success/connected stays
    /// green. The image editor keeps the system accent for Photos parity.
    ///
    /// Slightly brightened in dark appearance so it stays legible on dark
    /// surfaces while reading as the same hue.
    static let brandAccent = Color(nsColor: NSColor(name: nil) { appearance in
        let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        return isDark
            ? NSColor(srgbRed: 0xF0 / 255.0, green: 0x6A / 255.0, blue: 0x3E / 255.0, alpha: 1.0)
            : NSColor(srgbRed: 0xE0 / 255.0, green: 0x55 / 255.0, blue: 0x2B / 255.0, alpha: 1.0)
    })
}
