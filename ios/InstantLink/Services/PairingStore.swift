import Foundation
import Security

/// A persisted pairing, reassembled from UserDefaults + Keychain.
struct StoredPairing: Equatable {
    let deviceID: String
    let host: String
    let port: Int
    let token: String
    let ssid: String?
}

/// Persists the pairing across launches: the bearer token lives in the
/// Keychain (device-only, after first unlock); device/host/port/ssid and the
/// set of already-synced item ids live in UserDefaults.
final class PairingStore {
    private enum Key {
        static let deviceID = "pairing.deviceID"
        static let host = "pairing.host"
        static let port = "pairing.port"
        static let ssid = "pairing.ssid"
        static let syncedItemIDs = "sync.syncedItemIDs"
    }

    private static let keychainService = "com.instantlink.ios.pair-token"

    enum KeychainError: LocalizedError {
        case unexpectedStatus(OSStatus)

        var errorDescription: String? {
            if case .unexpectedStatus(let status) = self {
                return "Could not store the pairing token (Keychain error \(status))."
            }
            return nil
        }
    }

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    // MARK: - Pairing

    func load() -> StoredPairing? {
        guard let deviceID = defaults.string(forKey: Key.deviceID),
              let host = defaults.string(forKey: Key.host),
              let token = readToken(for: deviceID)
        else { return nil }
        let storedPort = defaults.integer(forKey: Key.port)
        return StoredPairing(
            deviceID: deviceID,
            host: host,
            port: storedPort == 0 ? PairingInfo.defaultPort : storedPort,
            token: token,
            ssid: defaults.string(forKey: Key.ssid)
        )
    }

    func save(_ info: PairingInfo) throws {
        try writeToken(info.token, for: info.deviceID)
        defaults.set(info.deviceID, forKey: Key.deviceID)
        defaults.set(info.host, forKey: Key.host)
        defaults.set(info.port, forKey: Key.port)
        if let ssid = info.ssid {
            defaults.set(ssid, forKey: Key.ssid)
        } else {
            defaults.removeObject(forKey: Key.ssid)
        }
    }

    /// Removes the pairing and the synced-id history. Does not touch the
    /// Photos library or the NEHotspotConfiguration (the caller owns those).
    func forget() {
        if let deviceID = defaults.string(forKey: Key.deviceID) {
            deleteToken(for: deviceID)
        }
        for key in [Key.deviceID, Key.host, Key.port, Key.ssid, Key.syncedItemIDs] {
            defaults.removeObject(forKey: key)
        }
        syncedItemIDs = []
    }

    // MARK: - Synced item ids

    /// Item ids already saved to Photos and acked; re-offered queue entries
    /// with these ids are skipped.
    private(set) lazy var syncedItemIDs: Set<String> =
        Set(defaults.stringArray(forKey: Key.syncedItemIDs) ?? [])

    func isSynced(_ itemID: String) -> Bool {
        syncedItemIDs.contains(itemID)
    }

    func markSynced(_ itemID: String) {
        syncedItemIDs.insert(itemID)
        defaults.set(Array(syncedItemIDs).sorted(), forKey: Key.syncedItemIDs)
    }

    // MARK: - Keychain

    private func keychainQuery(for deviceID: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.keychainService,
            kSecAttrAccount as String: deviceID,
        ]
    }

    private func readToken(for deviceID: String) -> String? {
        var query = keychainQuery(for: deviceID)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func writeToken(_ token: String, for deviceID: String) throws {
        deleteToken(for: deviceID)
        var attributes = keychainQuery(for: deviceID)
        attributes[kSecValueData as String] = Data(token.utf8)
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.unexpectedStatus(status)
        }
    }

    private func deleteToken(for deviceID: String) {
        SecItemDelete(keychainQuery(for: deviceID) as CFDictionary)
    }
}
