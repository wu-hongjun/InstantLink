import XCTest
@testable import InstantLink

final class PairingStoreTests: XCTestCase {
    private static let suiteName = "com.instantlink.ios.tests.PairingStoreTests"
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        defaults = try XCTUnwrap(UserDefaults(suiteName: Self.suiteName))
        defaults.removePersistentDomain(forName: Self.suiteName)
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: Self.suiteName)
    }

    // MARK: - Synced-id persistence

    func testSyncedIDsRoundTripAcrossInstances() {
        let store = PairingStore(defaults: defaults)
        store.markSynced("item-a")
        store.markSynced("item-b")
        store.markSynced("item-a") // Duplicate is a no-op.

        XCTAssertEqual(store.syncedItemIDs, ["item-a", "item-b"])
        XCTAssertTrue(store.isSynced("item-a"))
        XCTAssertFalse(store.isSynced("item-c"))

        // A fresh instance on the same defaults sees the same history.
        let reloaded = PairingStore(defaults: defaults)
        XCTAssertEqual(reloaded.syncedItemIDs, ["item-a", "item-b"])
        XCTAssertTrue(reloaded.isSynced("item-b"))
    }

    func testSyncedIDsPruneOldestBeyondCap() {
        let store = PairingStore(defaults: defaults)
        let overflow = 25
        let total = PairingStore.maxSyncedItemIDs + overflow
        for index in 0..<total {
            store.markSynced("item-\(index)")
        }

        XCTAssertEqual(store.syncedItemIDs.count, PairingStore.maxSyncedItemIDs)
        // Oldest ids fall out first (insertion order)...
        XCTAssertFalse(store.isSynced("item-0"))
        XCTAssertFalse(store.isSynced("item-\(overflow - 1)"))
        // ...and everything newer survives.
        XCTAssertTrue(store.isSynced("item-\(overflow)"))
        XCTAssertTrue(store.isSynced("item-\(total - 1)"))

        // The pruned, insertion-ordered set is what persists.
        let reloaded = PairingStore(defaults: defaults)
        XCTAssertEqual(reloaded.syncedItemIDs.count, PairingStore.maxSyncedItemIDs)
        XCTAssertFalse(reloaded.isSynced("item-\(overflow - 1)"))
        XCTAssertTrue(reloaded.isSynced("item-\(overflow)"))
    }

    // MARK: - Pairing round trip (keychain-dependent)

    /// Skipped when the Keychain is unavailable to the test host — the token
    /// half of a pairing lives in the Keychain, and some CI/simulator
    /// configurations refuse SecItemAdd from test bundles.
    func testSaveLoadForgetRoundTrip() throws {
        let token = "0123456789abcdef0123456789abcdef"
        let store = PairingStore(defaults: defaults)
        let info = try PairingInfo.parse(
            "instantlink://pair?v=1&device=IB-TEST&host=192.168.8.1&port=8721"
                + "&token=\(token)&ssid=InstantLink-TEST&psk=12345678"
        )

        do {
            try store.save(info)
        } catch is PairingStore.KeychainError {
            throw XCTSkip("Keychain unavailable in this test environment; skipping save/load round trip.")
        }
        // Ensure the keychain entry never outlives the test.
        defer { store.forget() }

        let loaded = try XCTUnwrap(store.load())
        XCTAssertEqual(
            loaded,
            StoredPairing(
                deviceID: "IB-TEST",
                host: "192.168.8.1",
                port: 8721,
                token: token,
                ssid: "InstantLink-TEST"
            )
        )

        store.markSynced("item-a")
        store.forget()
        XCTAssertNil(store.load())
        XCTAssertTrue(store.syncedItemIDs.isEmpty)

        let reloaded = PairingStore(defaults: defaults)
        XCTAssertNil(reloaded.load())
        XCTAssertTrue(reloaded.syncedItemIDs.isEmpty)
    }
}
