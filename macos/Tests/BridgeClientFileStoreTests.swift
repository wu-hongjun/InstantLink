import CryptoKit
import Foundation

final class BridgeClientFileStoreTests {
    private func makeTmpPath() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("InstantLink")
            .appendingPathComponent("bridge_clients.json")
    }

    private func cleanup(_ url: URL) {
        // Remove the file and the parent test directory we created.
        try? FileManager.default.removeItem(at: url)
        try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
    }

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
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        let identity = makeIdentity()
        let key = Curve25519.Signing.PrivateKey()
        try store.saveIdentity(identity, privateKey: key)

        let loaded = try store.loadIdentity(deviceID: identity.deviceID)
        try expectTrue(loaded != nil)
        try expectEqual(loaded!.0, identity)
        try expectEqual(loaded!.1.rawRepresentation, key.rawRepresentation)
    }

    func testDeleteIdentityRemovesEntry() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        let identity = makeIdentity()
        try store.saveIdentity(identity, privateKey: .init())
        try store.deleteIdentity(deviceID: identity.deviceID)
        let result = try store.loadIdentity(deviceID: identity.deviceID)
        try expectNil(result)
    }

    func testListIdentitiesReturnsAllSaved() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        let a = makeIdentity(deviceID: "IB-AAA")
        let b = makeIdentity(deviceID: "IB-BBB")
        try store.saveIdentity(a, privateKey: .init())
        try store.saveIdentity(b, privateKey: .init())

        let identities = try store.listIdentities()
        let ids = Set(identities.map(\.deviceID))
        try expectEqual(ids, Set(["IB-AAA", "IB-BBB"]))
    }

    func testLoadMissingIdentityReturnsNil() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        let result = try store.loadIdentity(deviceID: "IB-NEVER-SEEN")
        try expectNil(result)
    }

    func testCreatesParentDirectoryWhenMissing() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let parent = path.deletingLastPathComponent()
        // Sanity: parent must not exist before save.
        try expectFalse(FileManager.default.fileExists(atPath: parent.path))

        let store = BridgeClientFileStore(path: path)
        try store.saveIdentity(makeIdentity(), privateKey: .init())

        try expectTrue(FileManager.default.fileExists(atPath: parent.path))
        let attrs = try FileManager.default.attributesOfItem(atPath: parent.path)
        let perms = (attrs[.posixPermissions] as? NSNumber)?.intValue ?? 0
        try expectEqual(perms & 0o777, 0o700)
    }

    func testFileHas0600Permissions() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        try store.saveIdentity(makeIdentity(), privateKey: .init())
        try expectTrue(FileManager.default.fileExists(atPath: path.path))

        let attrs = try FileManager.default.attributesOfItem(atPath: path.path)
        let perms = (attrs[.posixPermissions] as? NSNumber)?.intValue ?? 0
        try expectEqual(perms & 0o777, 0o600)
    }

    func testAtomicWriteIsTornWriteSafe() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        // First successful save establishes a baseline file.
        try store.saveIdentity(makeIdentity(deviceID: "IB-FIRST"), privateKey: .init())
        let baseline = try Data(contentsOf: path)
        try expectTrue(!baseline.isEmpty)

        // Make the destination read-only so the atomic replace step throws.
        // The implementation must surface the error AND leave the existing
        // payload intact (no truncation, no half-written file).
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o400],
            ofItemAtPath: path.path
        )
        // Also lock the parent so neither move-into-place nor replace can
        // succeed; on macOS, a 0o500 parent disallows write/unlink.
        let parent = path.deletingLastPathComponent()
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o500],
            ofItemAtPath: parent.path
        )

        var threw = false
        do {
            try store.saveIdentity(makeIdentity(deviceID: "IB-SECOND"), privateKey: .init())
        } catch {
            threw = true
        }
        try expectTrue(threw)

        // Restore permissions so we can compare and clean up.
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: parent.path
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: path.path
        )

        let after = try Data(contentsOf: path)
        try expectEqual(after, baseline)
    }

    func testSigningKeyRoundTripsAsBase64URL() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        let key = Curve25519.Signing.PrivateKey()
        try store.saveIdentity(makeIdentity(), privateKey: key)

        guard let loaded = try store.loadIdentity(deviceID: "IB-TEST") else {
            throw MacTestFailure(file: #filePath, line: #line, message: "expected stored identity")
        }
        let payload = Data("hello-bridge".utf8)
        let signature = try loaded.1.signature(for: payload)
        try expectTrue(key.publicKey.isValidSignature(signature, for: payload))
    }

    func testReadSelfHealsOnCorruptedJSON() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }
        let store = BridgeClientFileStore(path: path)

        // Save a known-good record so the parent directory exists.
        let identity = makeIdentity(deviceID: "IB-GOOD")
        let key = Curve25519.Signing.PrivateKey()
        try store.saveIdentity(identity, privateKey: key)

        // Corrupt the file on disk with garbage bytes.
        try Data("garbage-not-json".utf8).write(to: path, options: [.atomic])

        // Listing must now silently return [] (self-heal) instead of throwing.
        let reopened = BridgeClientFileStore(path: path)
        let identities = try reopened.listIdentities()
        try expectEqual(identities.count, 0)

        // The broken file must have been moved aside with a `.broken-` suffix.
        let parent = path.deletingLastPathComponent()
        let entries = try FileManager.default
            .contentsOfDirectory(atPath: parent.path)
        let brokenEntries = entries.filter {
            $0.hasPrefix("\(path.lastPathComponent).broken-")
        }
        try expectTrue(!brokenEntries.isEmpty)

        // Subsequent saves must succeed against the fresh map.
        let next = makeIdentity(deviceID: "IB-NEW")
        try reopened.saveIdentity(next, privateKey: .init())
        let loaded = try reopened.loadIdentity(deviceID: next.deviceID)
        try expectTrue(loaded != nil)
        try expectEqual(loaded!.0, next)
    }

    func testPersistsAcrossInstanceReloads() throws {
        let path = makeTmpPath()
        defer { cleanup(path) }

        let identity = makeIdentity(deviceID: "IB-PERSIST")
        let key = Curve25519.Signing.PrivateKey()
        do {
            let store = BridgeClientFileStore(path: path)
            try store.saveIdentity(identity, privateKey: key)
        }

        let reopened = BridgeClientFileStore(path: path)
        let loaded = try reopened.loadIdentity(deviceID: identity.deviceID)
        try expectTrue(loaded != nil)
        try expectEqual(loaded!.0, identity)
        try expectEqual(loaded!.1.rawRepresentation, key.rawRepresentation)
    }
}
