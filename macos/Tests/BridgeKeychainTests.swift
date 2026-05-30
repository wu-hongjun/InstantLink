import CryptoKit
import Foundation

final class BridgeKeychainTests {
    private func makeIdentity(deviceID: String = "IB-TEST") -> BridgeIdentity {
        BridgeIdentity(
            deviceID: deviceID,
            displayName: "InstantLink Bridge \(deviceID)",
            pairedAt: Date(timeIntervalSince1970: 1_700_000_000),
            clientID: "macbook",
            clientName: "Test Mac"
        )
    }

    func testSaveAndLoadIdentityRoundTrip() throws {
        let keychain = BridgeKeychain(backend: InMemoryBridgeKeychainBackend())
        let identity = makeIdentity()
        let key = Curve25519.Signing.PrivateKey()
        try keychain.saveIdentity(identity, privateKey: key)

        let loaded = try keychain.loadIdentity(deviceID: identity.deviceID)
        try expectTrue(loaded != nil)
        try expectEqual(loaded!.0, identity)
        try expectEqual(loaded!.1.rawRepresentation, key.rawRepresentation)
    }

    func testDeleteIdentityRemovesEntry() throws {
        let keychain = BridgeKeychain(backend: InMemoryBridgeKeychainBackend())
        let identity = makeIdentity()
        try keychain.saveIdentity(identity, privateKey: .init())
        try keychain.deleteIdentity(deviceID: identity.deviceID)
        let result = try keychain.loadIdentity(deviceID: identity.deviceID)
        try expectNil(result)
    }

    func testListIdentitiesReturnsAllSavedDevices() throws {
        let keychain = BridgeKeychain(backend: InMemoryBridgeKeychainBackend())
        let a = makeIdentity(deviceID: "IB-AAA")
        let b = makeIdentity(deviceID: "IB-BBB")
        try keychain.saveIdentity(a, privateKey: .init())
        try keychain.saveIdentity(b, privateKey: .init())

        let identities = try keychain.listIdentities()
        let ids = Set(identities.map(\.deviceID))
        try expectEqual(ids, Set(["IB-AAA", "IB-BBB"]))
    }

    func testLoadMissingIdentityReturnsNil() throws {
        let keychain = BridgeKeychain(backend: InMemoryBridgeKeychainBackend())
        let result = try keychain.loadIdentity(deviceID: "IB-NEVER-SEEN")
        try expectNil(result)
    }
}
