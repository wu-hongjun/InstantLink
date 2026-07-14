import Foundation
import Photos

/// Saves downloaded originals into the Photos library with add-only access.
struct PhotoSaver {
    enum PhotoSaverError: LocalizedError {
        case notAuthorized

        var errorDescription: String? {
            "InstantLink needs permission to add photos to your library. Enable it in Settings ▸ Privacy ▸ Photos."
        }
    }

    /// Prompts for `.addOnly` authorization on first use.
    static func ensureAuthorized() async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized else {
            throw PhotoSaverError.notAuthorized
        }
    }

    /// Adds the file at `fileURL` as a new photo asset. The original camera
    /// filename is preserved on the asset resource. `creationDate` is left
    /// unset on purpose: Photos derives it from the image's own EXIF capture
    /// time, which is more accurate than the Bridge's `received_at`.
    static func save(fileURL: URL, fileName: String) async throws {
        try await ensureAuthorized()
        try await PHPhotoLibrary.shared().performChanges {
            let creation = PHAssetCreationRequest.forAsset()
            let options = PHAssetResourceCreationOptions()
            options.originalFilename = fileName
            creation.addResource(with: .photo, fileURL: fileURL, options: options)
        }
    }
}
