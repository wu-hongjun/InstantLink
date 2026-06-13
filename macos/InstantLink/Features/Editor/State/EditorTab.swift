import SwiftUI

/// Top-level editor mode, one per top tab bar entry.
enum EditorTab: String, CaseIterable, Codable {
    case adjust
    case filters
    case crop
    case annotate

    var localizedTitle: LocalizedStringKey {
        switch self {
        case .adjust:   return LocalizedStringKey("editor_tab_adjust")
        case .filters:  return LocalizedStringKey("editor_tab_filters")
        case .crop:     return LocalizedStringKey("editor_tab_crop")
        case .annotate: return LocalizedStringKey("editor_tab_annotate")
        }
    }
}
