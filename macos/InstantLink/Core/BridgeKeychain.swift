import CryptoKit
import Foundation
import Security

/// Per-Bridge signing identity stored in the macOS Keychain.
///
/// `BridgeIdentity` is the lightweight envelope; the private key bytes are
/// embedded alongside it in the keychain blob and loaded only when needed.
struct BridgeIdentity: Codable, Equatable {
    var deviceID: String
    var displayName: String
    var pairedAt: Date
    var clientID: String
    var clientName: String

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case displayName = "display_name"
        case pairedAt = "paired_at"
        case clientID = "client_id"
        case clientName = "client_name"
    }
}

/// Persisted record envelope stored in the keychain. Private signing material
/// lives separately in `KeychainBridgeClientKeyStore` (see `BridgeAuth.swift`)
/// because the HTTP transport owns the signing lifecycle. This wrapper persists
/// only display-facing metadata + the optional public key bytes used for
/// fingerprint comparisons on reconnect.
private struct BridgeIdentityRecord: Codable {
    var identity: BridgeIdentity
    var privateKeyRaw: Data

    enum CodingKeys: String, CodingKey {
        case identity
        case privateKeyRaw = "private_key_raw"
    }
}

enum BridgeKeychainError: Error, Equatable {
    case osStatus(OSStatus)
    case invalidRecord
}

/// Pluggable backend so unit tests can substitute an in-memory store.
protocol BridgeKeychainBackend {
    func save(_ data: Data, account: String) throws
    func load(account: String) throws -> Data?
    func delete(account: String) throws
    func listAccounts() throws -> [String]
}

/// Production backend talking to the macOS Keychain via `Security.framework`.
final class SystemBridgeKeychainBackend: BridgeKeychainBackend {
    private let service: String

    init(service: String) {
        self.service = service
    }

    func save(_ data: Data, account: String) throws {
        var lookup: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]

        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]

        let updateStatus = SecItemUpdate(lookup as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw BridgeKeychainError.osStatus(updateStatus)
        }

        lookup.merge(attributes) { _, new in new }
        let addStatus = SecItemAdd(lookup as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw BridgeKeychainError.osStatus(addStatus)
        }
    }

    func load(account: String) throws -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw BridgeKeychainError.osStatus(status) }
        guard let data = item as? Data else { throw BridgeKeychainError.invalidRecord }
        return data
    }

    func delete(account: String) throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw BridgeKeychainError.osStatus(status)
        }
    }

    func listAccounts() throws -> [String] {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]
        var items: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &items)
        if status == errSecItemNotFound { return [] }
        guard status == errSecSuccess else { throw BridgeKeychainError.osStatus(status) }
        guard let array = items as? [[String: Any]] else { return [] }
        return array.compactMap { $0[kSecAttrAccount as String] as? String }
    }
}

/// In-memory backend used by tests to avoid touching the real keychain.
final class InMemoryBridgeKeychainBackend: BridgeKeychainBackend {
    private var storage: [String: Data] = [:]

    init() {}

    func save(_ data: Data, account: String) throws {
        storage[account] = data
    }

    func load(account: String) throws -> Data? {
        storage[account]
    }

    func delete(account: String) throws {
        storage.removeValue(forKey: account)
    }

    func listAccounts() throws -> [String] {
        Array(storage.keys)
    }
}

/// High-level Keychain wrapper for Bridge identities.
final class BridgeKeychain {
    private let backend: BridgeKeychainBackend
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(backend: BridgeKeychainBackend = SystemBridgeKeychainBackend(service: "com.instantlink.bridge")) {
        self.backend = backend
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
    }

    func saveIdentity(_ identity: BridgeIdentity, privateKey: Curve25519.Signing.PrivateKey) throws {
        let record = BridgeIdentityRecord(
            identity: identity,
            privateKeyRaw: privateKey.rawRepresentation
        )
        let data = try encoder.encode(record)
        try backend.save(data, account: identity.deviceID)
    }

    func loadIdentity(deviceID: String) throws -> (BridgeIdentity, Curve25519.Signing.PrivateKey)? {
        guard let data = try backend.load(account: deviceID) else { return nil }
        let record: BridgeIdentityRecord
        do {
            record = try decoder.decode(BridgeIdentityRecord.self, from: data)
        } catch {
            throw BridgeKeychainError.invalidRecord
        }
        let key: Curve25519.Signing.PrivateKey
        do {
            key = try Curve25519.Signing.PrivateKey(rawRepresentation: record.privateKeyRaw)
        } catch {
            throw BridgeKeychainError.invalidRecord
        }
        return (record.identity, key)
    }

    func deleteIdentity(deviceID: String) throws {
        try backend.delete(account: deviceID)
    }

    func listIdentities() throws -> [BridgeIdentity] {
        let accounts = try backend.listAccounts()
        var identities: [BridgeIdentity] = []
        for account in accounts {
            guard let data = try backend.load(account: account) else { continue }
            if let record = try? decoder.decode(BridgeIdentityRecord.self, from: data) {
                identities.append(record.identity)
            }
        }
        return identities
    }
}
