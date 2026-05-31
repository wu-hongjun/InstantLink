import CryptoKit
import Foundation
import os.log

// Plan 038 polish (2026-05-30): we moved off macOS Keychain because
// every ad-hoc-signed rebuild of InstantLink.app triggers a "allow
// access?" prompt on every Keychain read — terrible UX. The Ed25519
// signing key now lives in this 0600 file alongside the display
// metadata; same threat model as ~/.ssh/id_ed25519. Old Keychain
// entries from prior releases become inert; the USB auto-trust path
// silently re-registers the Mac on next probe of /v1/hello.

/// Canonical on-disk path for the Bridge client identity store.
enum BridgeClientStorePaths {
    static func defaultFileURL() -> URL {
        let support = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return support
            .appendingPathComponent("InstantLink", isDirectory: true)
            .appendingPathComponent("bridge_clients.json", isDirectory: false)
    }
}

enum BridgeClientFileStoreError: Error, Equatable {
    case decodeFailed
    case invalidRecord
    case ioError(String)
}

/// Display metadata for a paired Bridge. Mirrors the per-device record on
/// disk minus the signing key. The struct previously lived in the deleted
/// `BridgeKeychain.swift`; consolidated here so the store and its consumers
/// share a single definition.
struct BridgeIdentity: Equatable {
    let deviceID: String
    let displayName: String
    let pairedAt: Date
    let clientID: String
    let clientName: String
}

/// Single source of truth for per-Bridge client identity persistence.
///
/// Schema (JSON, top-level object keyed by `device_id`):
/// ```json
/// {
///   "<device_id>": {
///     "client_id": "<uuid>",
///     "client_name": "<hostname or chosen>",
///     "display_name": "<human bridge name>",
///     "paired_at": "2026-05-30T17:59:00Z",
///     "signing_key_pkcs8_base64url": "<ed25519 private key, base64url, no padding>"
///   }
/// }
/// ```
///
/// File is written atomically with 0600 perms; parent directory is created with 0700.
final class BridgeClientFileStore: BridgeClientKeyStore {
    private let path: URL
    private let queue = DispatchQueue(label: "com.instantlink.bridge.client-file-store")
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(path: URL = BridgeClientStorePaths.defaultFileURL()) {
        self.path = path
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    // MARK: - BridgeClientKeyStore (signing key surface)

    func loadIdentity(for bridgeID: String) throws -> BridgeSigningIdentity? {
        let records = try readRecords()
        guard let record = records[bridgeID] else { return nil }
        return try record.signingIdentity(bridgeID: bridgeID)
    }

    func createIdentity(for bridgeID: String, clientName: String) throws -> BridgeSigningIdentity {
        try BridgeSigningIdentity.generate(
            bridgeID: bridgeID,
            clientName: clientName,
            algorithm: BridgeManagementAuth.productionSigningAlgorithm
        )
    }

    func saveIdentity(_ identity: BridgeSigningIdentity, for bridgeID: String) throws {
        try mutateRecords { records in
            var record = records[bridgeID] ?? BridgeClientRecord(
                clientID: identity.clientID,
                clientName: identity.clientName,
                displayName: bridgeID,
                pairedAt: Date(),
                signingKeyBase64URL: BridgeManagementAuth.base64URLEncoded(identity.privateKeyRawRepresentation)
            )
            record.clientID = identity.clientID
            record.clientName = identity.clientName
            record.signingKeyBase64URL = BridgeManagementAuth.base64URLEncoded(identity.privateKeyRawRepresentation)
            records[bridgeID] = record
        }
    }

    func deleteIdentity(for bridgeID: String) throws {
        try mutateRecords { records in
            records.removeValue(forKey: bridgeID)
        }
    }

    // MARK: - Display metadata surface (replaces BridgeKeychain)

    func saveIdentity(_ identity: BridgeIdentity, privateKey: Curve25519.Signing.PrivateKey) throws {
        try mutateRecords { records in
            records[identity.deviceID] = BridgeClientRecord(
                clientID: identity.clientID,
                clientName: identity.clientName,
                displayName: identity.displayName,
                pairedAt: identity.pairedAt,
                signingKeyBase64URL: BridgeManagementAuth.base64URLEncoded(privateKey.rawRepresentation)
            )
        }
    }

    func loadIdentity(deviceID: String) throws -> (BridgeIdentity, Curve25519.Signing.PrivateKey)? {
        let records = try readRecords()
        guard let record = records[deviceID] else { return nil }
        let identity = BridgeIdentity(
            deviceID: deviceID,
            displayName: record.displayName,
            pairedAt: record.pairedAt,
            clientID: record.clientID,
            clientName: record.clientName
        )
        let key: Curve25519.Signing.PrivateKey
        do {
            key = try Curve25519.Signing.PrivateKey(rawRepresentation: try record.signingKeyBytes())
        } catch {
            throw BridgeClientFileStoreError.invalidRecord
        }
        return (identity, key)
    }

    func deleteIdentity(deviceID: String) throws {
        try mutateRecords { records in
            records.removeValue(forKey: deviceID)
        }
    }

    func listIdentities() throws -> [BridgeIdentity] {
        let records = try readRecords()
        return records.map { deviceID, record in
            BridgeIdentity(
                deviceID: deviceID,
                displayName: record.displayName,
                pairedAt: record.pairedAt,
                clientID: record.clientID,
                clientName: record.clientName
            )
        }
    }

    // MARK: - I/O

    private func readRecords() throws -> [String: BridgeClientRecord] {
        try queue.sync {
            try readRecordsLocked()
        }
    }

    private func readRecordsLocked() throws -> [String: BridgeClientRecord] {
        guard FileManager.default.fileExists(atPath: path.path) else { return [:] }
        let data: Data
        do {
            data = try Data(contentsOf: path)
        } catch {
            throw BridgeClientFileStoreError.ioError(error.localizedDescription)
        }
        if data.isEmpty { return [:] }
        do {
            return try decoder.decode([String: BridgeClientRecord].self, from: data)
        } catch {
            // Self-heal on corrupted JSON: a malformed bridge_clients.json
            // would otherwise lock the user out of every pairing flow
            // (each save/load funnels through this read). Move the broken
            // file aside with a UTC timestamp suffix and start fresh from
            // an empty map; subsequent writes succeed and the USB
            // auto-trust path silently re-registers on next /v1/hello.
            renameCorruptFileLocked(error: error)
            return [:]
        }
    }

    /// Rename a corrupted records file to `bridge_clients.json.broken-<UTC>`
    /// so the user can recover it from disk if they want. Best-effort; we
    /// log loudly via `os_log` and never throw — if the rename fails the
    /// next write will overwrite the broken file anyway, which is still
    /// recoverable behavior.
    private func renameCorruptFileLocked(error: Error) {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let stamp = formatter.string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        let brokenPath = path.deletingLastPathComponent()
            .appendingPathComponent("\(path.lastPathComponent).broken-\(stamp)")
        do {
            try FileManager.default.moveItem(at: path, to: brokenPath)
            os_log(
                "BridgeClientFileStore: corrupted JSON at %{public}@ — renamed to %{public}@ (reason: %{public}@). Starting fresh; pair the Bridge again.",
                log: .default,
                type: .error,
                path.path,
                brokenPath.path,
                error.localizedDescription
            )
        } catch {
            os_log(
                "BridgeClientFileStore: corrupted JSON at %{public}@ — rename failed (reason: %{public}@). Next write will overwrite.",
                log: .default,
                type: .error,
                path.path,
                error.localizedDescription
            )
        }
    }

    private func mutateRecords(_ body: (inout [String: BridgeClientRecord]) -> Void) throws {
        try queue.sync {
            var records = try readRecordsLocked()
            body(&records)
            try writeRecordsLocked(records)
        }
    }

    private func writeRecordsLocked(_ records: [String: BridgeClientRecord]) throws {
        try ensureParentDirectoryLocked()
        let data: Data
        do {
            data = try encoder.encode(records)
        } catch {
            throw BridgeClientFileStoreError.ioError("encode failed: \(error.localizedDescription)")
        }
        try atomicWriteLocked(data: data)
    }

    private func ensureParentDirectoryLocked() throws {
        let parent = path.deletingLastPathComponent()
        let fm = FileManager.default
        if !fm.fileExists(atPath: parent.path) {
            do {
                try fm.createDirectory(
                    at: parent,
                    withIntermediateDirectories: true,
                    attributes: [.posixPermissions: 0o700]
                )
            } catch {
                throw BridgeClientFileStoreError.ioError("mkdir failed: \(error.localizedDescription)")
            }
        }
    }

    /// Atomic write: write to `*.tmp` with 0600 perms, then replace the
    /// destination. On failure mid-write, the destination file is unchanged.
    private func atomicWriteLocked(data: Data) throws {
        let tmp = path.appendingPathExtension("tmp")
        let fm = FileManager.default
        if fm.fileExists(atPath: tmp.path) {
            try? fm.removeItem(at: tmp)
        }
        do {
            try data.write(to: tmp, options: .atomic)
            try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: tmp.path)
        } catch {
            try? fm.removeItem(at: tmp)
            throw BridgeClientFileStoreError.ioError("write tmp failed: \(error.localizedDescription)")
        }

        do {
            if fm.fileExists(atPath: path.path) {
                _ = try fm.replaceItemAt(path, withItemAt: tmp)
            } else {
                try fm.moveItem(at: tmp, to: path)
            }
            // replaceItemAt on macOS may preserve original perms; reassert 0600.
            try? fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        } catch {
            try? fm.removeItem(at: tmp)
            throw BridgeClientFileStoreError.ioError("atomic replace failed: \(error.localizedDescription)")
        }
    }
}

// MARK: - On-disk record

private struct BridgeClientRecord: Codable, Equatable {
    var clientID: String
    var clientName: String
    var displayName: String
    var pairedAt: Date
    var signingKeyBase64URL: String

    enum CodingKeys: String, CodingKey {
        case clientID = "client_id"
        case clientName = "client_name"
        case displayName = "display_name"
        case pairedAt = "paired_at"
        case signingKeyBase64URL = "signing_key_pkcs8_base64url"
    }

    func signingKeyBytes() throws -> Data {
        guard let bytes = base64URLDecoded(signingKeyBase64URL) else {
            throw BridgeClientFileStoreError.invalidRecord
        }
        return bytes
    }

    func signingIdentity(bridgeID: String) throws -> BridgeSigningIdentity {
        let raw = try signingKeyBytes()
        // Reconstruct the public key from the persisted private key bytes so the
        // identity round-trips with the same canonical public key the bridge
        // expects in pairing requests / signed headers.
        let publicKey: String
        do {
            let key = try Curve25519.Signing.PrivateKey(rawRepresentation: raw)
            publicKey = BridgeManagementAuth.base64URLEncoded(key.publicKey.rawRepresentation)
        } catch {
            throw BridgeClientFileStoreError.invalidRecord
        }
        return BridgeSigningIdentity(
            bridgeID: bridgeID,
            clientID: clientID,
            clientName: clientName,
            algorithm: .ed25519,
            publicKey: publicKey,
            privateKeyRawRepresentation: raw
        )
    }
}

private func base64URLDecoded(_ string: String) -> Data? {
    var s = string
        .replacingOccurrences(of: "-", with: "+")
        .replacingOccurrences(of: "_", with: "/")
    let pad = s.count % 4
    if pad > 0 {
        s += String(repeating: "=", count: 4 - pad)
    }
    return Data(base64Encoded: s)
}
