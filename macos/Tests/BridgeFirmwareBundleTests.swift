import Foundation
import CryptoKit

final class BridgeFirmwareBundleTests {
    func testPackageLoadsBundledFirmwareMetadata() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        let archiveURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.1.0-linux-aarch64.tar.gz")
        let manifestURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.1.0-linux-aarch64.manifest.json")
        let manifestSignatureURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.1.0-linux-aarch64.manifest.sig")
        let checksumURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.1.0-linux-aarch64.tar.gz.sha256")

        try Data("archive".utf8).write(to: archiveURL)
        try Data("{\"schema_version\":1}\n".utf8).write(to: manifestURL)
        try Data("{\"signature\":\"manifest\"}\n".utf8).write(to: manifestSignatureURL)
        try Data("abc  archive\n".utf8).write(to: checksumURL)
        let archiveSHA = try sha256Hex(archiveURL)
        let manifestSHA = try sha256Hex(manifestURL)
        let checksumSHA = try sha256Hex(checksumURL)
        try Data(
            """
            {
              "schema_version": 1,
              "package_kind": "instantlink_bridge_firmware",
              "bridge_version": "0.1.0",
              "target": "linux-aarch64",
              "archive_name": "\(archiveURL.lastPathComponent)",
              "archive_sha256": "\(archiveSHA)",
              "manifest_name": "\(manifestURL.lastPathComponent)",
              "manifest_sha256": "\(manifestSHA)",
              "checksum_name": "\(checksumURL.lastPathComponent)",
              "checksum_sha256": "\(checksumSHA)"
            }
            """.utf8
        ).write(to: directory.appendingPathComponent("latest.json"))
        try Data("{\"signature\":\"latest\"}\n".utf8)
            .write(to: directory.appendingPathComponent("latest.json.sig"))

        guard let package = BridgeFirmwareBundleService.package(in: directory) else {
            throw MacTestFailure(
                file: #filePath,
                line: #line,
                message: "Expected bundled firmware package metadata to load"
            )
        }

        try expectEqual(package.version, "0.1.0")
        try expectEqual(package.target, "linux-aarch64")
        try expectEqual(package.archiveURL.lastPathComponent, archiveURL.lastPathComponent)
        try expectEqual(package.archiveSHA256, archiveSHA)
        try expectEqual(package.manifestURL.lastPathComponent, manifestURL.lastPathComponent)
        try expectEqual(package.manifestSHA256, manifestSHA)
        try expectEqual(package.manifestSignatureURL.lastPathComponent, manifestSignatureURL.lastPathComponent)
        try expectEqual(package.checksumURL.lastPathComponent, checksumURL.lastPathComponent)
    }

    func testPackageReturnsNilWhenSidecarsAreMissing() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        try Data(
            """
            {
              "bridge_version": "0.1.0",
              "target": "linux-aarch64",
              "archive_name": "missing.tar.gz",
              "archive_sha256": "archive-sha",
              "manifest_name": "missing.manifest.json",
              "manifest_sha256": "manifest-sha",
              "checksum_name": "missing.tar.gz.sha256"
            }
            """.utf8
        ).write(to: directory.appendingPathComponent("latest.json"))

        try expectNil(BridgeFirmwareBundleService.package(in: directory))
    }

    func testPackageMapsToBridgeUpdatePackage() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        let archiveURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.2.0-linux-aarch64.tar.gz")
        let manifestURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.2.0-linux-aarch64.manifest.json")
        let manifestSignatureURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.2.0-linux-aarch64.manifest.sig")
        let checksumURL = directory.appendingPathComponent("InstantLinkBridgeFirmware-v0.2.0-linux-aarch64.tar.gz.sha256")

        try Data("archive".utf8).write(to: archiveURL)
        try Data("{\"schema_version\":1}\n".utf8).write(to: manifestURL)
        try Data("{\"signature\":\"manifest\"}\n".utf8).write(to: manifestSignatureURL)
        try Data("abc  archive\n".utf8).write(to: checksumURL)
        let archiveSHA = try sha256Hex(archiveURL)
        let manifestSHA = try sha256Hex(manifestURL)
        let checksumSHA = try sha256Hex(checksumURL)
        try Data(
            """
            {
              "schema_version": 1,
              "package_kind": "instantlink_bridge_firmware",
              "bridge_version": "0.2.0",
              "target": "linux-aarch64",
              "archive_name": "\(archiveURL.lastPathComponent)",
              "archive_sha256": "\(archiveSHA)",
              "manifest_name": "\(manifestURL.lastPathComponent)",
              "manifest_sha256": "\(manifestSHA)",
              "checksum_name": "\(checksumURL.lastPathComponent)",
              "checksum_sha256": "\(checksumSHA)"
            }
            """.utf8
        ).write(to: directory.appendingPathComponent("latest.json"))
        try Data("{\"signature\":\"latest\"}\n".utf8)
            .write(to: directory.appendingPathComponent("latest.json.sig"))

        guard let firmwarePackage = BridgeFirmwareBundleService.package(in: directory) else {
            throw MacTestFailure(
                file: #filePath,
                line: #line,
                message: "Expected bundled firmware package metadata to load"
            )
        }

        let updatePackage = firmwarePackage.updatePackage

        try expectEqual(updatePackage.packageKind, "instantlink_bridge_firmware")
        try expectEqual(updatePackage.version, "0.2.0")
        try expectEqual(updatePackage.target, "linux-aarch64")
        try expectEqual(updatePackage.archiveURL, archiveURL)
        try expectEqual(updatePackage.archiveSHA256, archiveSHA)
        try expectEqual(updatePackage.manifestURL, manifestURL)
        try expectEqual(updatePackage.manifestSHA256, manifestSHA)
        try expectEqual(updatePackage.checksumURL, checksumURL)
        try expectEqual(updatePackage.manifestSignatureURL, manifestSignatureURL)
    }

    func testPackageHashesEmptyAndChunkBoundaryArchives() throws {
        let chunkSize = 1024 * 1024
        for size in [0, 1, 63, 64, 65, chunkSize - 1, chunkSize, chunkSize + 1, chunkSize * 3 + 37] {
            var archive = Data((0..<size).map { UInt8(($0 * 31 + 7) % 251) })
            if !archive.isEmpty { archive[archive.count - 1] = 0xff }
            let directory = try makePackageDirectory(archive: archive)
            defer { try? FileManager.default.removeItem(at: directory) }

            let package = BridgeFirmwareBundleService.package(in: directory)
            let expected = SHA256.hash(data: archive).map { String(format: "%02x", $0) }.joined()
            try expectEqual(package?.archiveSHA256, expected, "Archive length \(size)")
        }
    }

    func testPackageRevalidatesEveryArtifactAfterReplacement() throws {
        for name in ["firmware.tar.gz", "firmware.manifest.json", "firmware.tar.gz.sha256"] {
            let directory = try makePackageDirectory(archive: Data(repeating: 0xa5, count: 1024 * 1024 + 17))
            defer { try? FileManager.default.removeItem(at: directory) }
            let artifact = directory.appendingPathComponent(name)
            let original = try Data(contentsOf: artifact)
            let attributes = try FileManager.default.attributesOfItem(atPath: artifact.path)
            let initial = BridgeFirmwareBundleService.package(in: directory)
            try expectTrue(initial != nil)

            var tampered = original
            tampered[tampered.count - 1] ^= 1
            try tampered.write(to: artifact, options: .atomic)
            // Same path, byte count and modification date must still trigger a full hash.
            if let modified = attributes[.modificationDate] {
                try FileManager.default.setAttributes([.modificationDate: modified], ofItemAtPath: artifact.path)
            }
            try expectNil(BridgeFirmwareBundleService.package(in: directory), "Tampered \(name)")
            try original.write(to: artifact, options: .atomic)
            try expectEqual(BridgeFirmwareBundleService.package(in: directory), initial)
        }
    }

    func testPackageRejectsMissingAndUnreadableArtifacts() throws {
        let names = [
            "firmware.tar.gz", "firmware.manifest.json", "firmware.tar.gz.sha256",
            "firmware.manifest.sig", "latest.json.sig",
        ]
        for name in names {
            let directory = try makePackageDirectory(archive: Data("archive".utf8))
            defer { try? FileManager.default.removeItem(at: directory) }
            try expectTrue(BridgeFirmwareBundleService.package(in: directory) != nil)
            try FileManager.default.removeItem(at: directory.appendingPathComponent(name))
            try expectNil(BridgeFirmwareBundleService.package(in: directory), "Missing \(name)")
        }
        for name in names.prefix(3) {
            let directory = try makePackageDirectory(archive: Data("archive".utf8))
            defer { try? FileManager.default.removeItem(at: directory) }
            let artifact = directory.appendingPathComponent(name)
            try FileManager.default.removeItem(at: artifact)
            try FileManager.default.createDirectory(at: artifact, withIntermediateDirectories: false)
            // The path exists and can be opened, but reading its contents must fail closed.
            try expectNil(BridgeFirmwareBundleService.package(in: directory), "Directory artifact \(name)")
        }
        let directory = try makePackageDirectory(archive: Data("archive".utf8))
        defer { try? FileManager.default.removeItem(at: directory) }
        let archive = directory.appendingPathComponent("firmware.tar.gz")
        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: archive.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: archive.path) }
        // Root can read mode-000 files; directory read failures above cover that environment.
        if !FileManager.default.isReadableFile(atPath: archive.path) {
            try expectNil(BridgeFirmwareBundleService.package(in: directory))
        }
    }

    func testPackagePreservesSchemaAndArtifactPathValidation() throws {
        let directory = try makePackageDirectory(archive: Data("archive".utf8))
        defer { try? FileManager.default.removeItem(at: directory) }
        let latestURL = directory.appendingPathComponent("latest.json")
        let latest = try Data(contentsOf: latestURL)
        let metadata = try JSONSerialization.jsonObject(with: latest) as! [String: Any]
        for key in ["archive_name", "manifest_name", "checksum_name"] {
            for unsafeName in ["", ".", "..", "../outside", "/outside", "folder/file", "folder\\file"] {
                var invalid = metadata
                invalid[key] = unsafeName
                try JSONSerialization.data(withJSONObject: invalid).write(to: latestURL)
                try expectNil(BridgeFirmwareBundleService.package(in: directory), "Unsafe \(key): \(unsafeName)")
            }
        }
        for (key, value) in [("schema_version", 2 as Any), ("package_kind", "other" as Any)] {
            var invalid = metadata
            invalid[key] = value
            try JSONSerialization.data(withJSONObject: invalid).write(to: latestURL)
            try expectNil(BridgeFirmwareBundleService.package(in: directory))
        }
        try latest.write(to: latestURL)
        try expectTrue(BridgeFirmwareBundleService.package(in: directory) != nil)
    }

    private func makePackageDirectory(archive: Data) throws -> URL {
        let directory = try makeTemporaryDirectory()
        let archiveURL = directory.appendingPathComponent("firmware.tar.gz")
        let manifestURL = directory.appendingPathComponent("firmware.manifest.json")
        let checksumURL = directory.appendingPathComponent("firmware.tar.gz.sha256")
        try archive.write(to: archiveURL)
        try Data("{\"schema_version\":1}\n".utf8).write(to: manifestURL)
        try Data("checksum\n".utf8).write(to: checksumURL)
        try Data("signature".utf8).write(to: directory.appendingPathComponent("firmware.manifest.sig"))
        try Data("signature".utf8).write(to: directory.appendingPathComponent("latest.json.sig"))
        let metadata: [String: Any] = [
            "schema_version": 1,
            "package_kind": "instantlink_bridge_firmware",
            "bridge_version": "0.1.0",
            "target": "linux-aarch64",
            "archive_name": archiveURL.lastPathComponent,
            "archive_sha256": try sha256Hex(archiveURL),
            "manifest_name": manifestURL.lastPathComponent,
            "manifest_sha256": try sha256Hex(manifestURL),
            "checksum_name": checksumURL.lastPathComponent,
            "checksum_sha256": try sha256Hex(checksumURL),
        ]
        try JSONSerialization.data(withJSONObject: metadata).write(to: directory.appendingPathComponent("latest.json"))
        return directory
    }

    private func makeTemporaryDirectory() throws -> URL {
        let directory = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("InstantLinkBridgeFirmwareTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        return directory
    }

    private func sha256Hex(_ url: URL) throws -> String {
        let data = try Data(contentsOf: url)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
