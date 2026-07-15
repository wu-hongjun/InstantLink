import Foundation
import Photos
import UniformTypeIdentifiers

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

    /// Photos infers the resource type from the file extension, and Sony
    /// cameras write HEIF as `.HIF` — an extension iOS does not map to any
    /// image type, which makes `addResource` reject the file outright. Map
    /// the known camera extensions explicitly and fall back to system UTI
    /// lookup for everything else.
    static func inferredType(forFileName fileName: String) -> UTType? {
        let ext = (fileName as NSString).pathExtension.lowercased()
        guard !ext.isEmpty else { return nil }
        switch ext {
        case "hif":
            return .heif
        case "arw":
            // Sony RAW; Photos accepts it as a raw image resource.
            return UTType("com.sony.arw-raw-image") ?? .rawImage
        default:
            // UTType(filenameExtension:conformingTo:) *mints* a dynamic
            // (dyn.*) type for unknown extensions instead of returning nil;
            // Photos rejects those at save time, so only declared types count.
            guard let type = UTType(filenameExtension: ext, conformingTo: .image),
                  type.isDeclared
            else { return nil }
            return type
        }
    }

    /// Adds the file at `fileURL` as a new photo asset. The original camera
    /// filename is preserved on the asset resource. `creationDate` is left
    /// unset on purpose: Photos derives it from the image's own EXIF capture
    /// time, which is more accurate than the Bridge's `received_at`.
    static func save(fileURL: URL, fileName: String) async throws {
        try await ensureAuthorized()
        let uniformType = inferredType(forFileName: fileName)
        try await PHPhotoLibrary.shared().performChanges {
            let creation = PHAssetCreationRequest.forAsset()
            let options = PHAssetResourceCreationOptions()
            options.originalFilename = fileName
            if let uniformType {
                options.uniformTypeIdentifier = uniformType.identifier
            }
            creation.addResource(with: .photo, fileURL: fileURL, options: options)
        }
    }
}
