import AppKit
import Foundation
import UniformTypeIdentifiers

/// UTTypes accepted by InstantLink's image drop surfaces (main preview + editor).
///
/// `.fileURL` covers Finder-style drags where a real file path exists.
/// `.image` plus the concrete image UTTypes are required for Apple's Photos
/// app and most web browsers — they promise image *data*, not a path, because
/// the source isn't on disk in the form the drop expects. Without these the
/// drop is silently rejected.
let imageDropTypes: [UTType] = [.fileURL, .image, .jpeg, .png, .heic, .tiff]

/// Hand an `NSItemProvider` to InstantLink's image queue.
///
/// File-URL providers go straight through (preserves the source path so EXIF
/// orientation, capture date, and GPS survive). Image-data providers are
/// materialised into a temp file via `loadFileRepresentation` so the rest of
/// the queue pipeline — which is URL-based — keeps working unchanged.
///
/// The temp file lives in `FileManager.default.temporaryDirectory`; macOS
/// purges it when the directory is cleaned, which is fine because the queue
/// copies the bytes it needs synchronously inside `addImages`.
@MainActor
func handleImageDrop(providers: [NSItemProvider], into viewModel: ViewModel) -> Bool {
    guard !providers.isEmpty else { return false }
    var accepted = false
    for provider in providers {
        if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            accepted = true
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                guard let url else { return }
                DispatchQueue.main.async { viewModel.addImages(from: [url]) }
            }
            continue
        }

        let imageTypeID = provider.registeredTypeIdentifiers.first { id in
            guard let type = UTType(id) else { return false }
            return type.conforms(to: .image)
        }
        guard let imageTypeID else { continue }
        accepted = true
        provider.loadFileRepresentation(forTypeIdentifier: imageTypeID) { url, _ in
            guard let url else { return }
            // The system-provided URL is only valid inside this closure, so
            // copy to a location we control before bouncing back to the main
            // queue. Preserve the source extension so the downstream JPEG /
            // HEIC / PNG decode picks the right path.
            let ext = url.pathExtension.isEmpty ? "jpg" : url.pathExtension
            let dest = FileManager.default.temporaryDirectory
                .appendingPathComponent("instantlink-drop-\(UUID().uuidString)")
                .appendingPathExtension(ext)
            do {
                try FileManager.default.copyItem(at: url, to: dest)
            } catch {
                return
            }
            DispatchQueue.main.async { viewModel.addImages(from: [dest]) }
        }
    }
    return accepted
}
