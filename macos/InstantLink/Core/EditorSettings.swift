import Foundation

/// Persistent editor preferences. Backed by `UserDefaults`. PR #1 ships only
/// the `useNewEditor` experimental flag; PRs #2 – #14 may add more fields here.
struct EditorSettings: Codable, Equatable {
    static let storageKey = "editorSettings"

    /// When true, the App opens images in the new Photos-style editor shell;
    /// otherwise the legacy `ImageEditorView` is presented unchanged.
    var useNewEditor: Bool = false

    static func load() -> Self {
        if let data = UserDefaults.standard.data(forKey: storageKey),
           let decoded = try? JSONDecoder().decode(Self.self, from: data) {
            return decoded
        }
        return Self()
    }

    func save() {
        if let data = try? JSONEncoder().encode(self) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }
}

let initialEditorSettings = EditorSettings.load()
