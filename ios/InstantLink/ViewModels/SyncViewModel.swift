import SwiftUI
import UIKit

// MARK: - View Model

/// Orchestrates onboarding and the foreground sync loop (plan 050 phase B).
///
/// Sync is pull-based and foreground-only in v1: while the app is active it
/// polls the Bridge queue every few seconds and drains it — download → save to
/// Photos → ack → remember the item id. Backgrounding cancels the loop.
@MainActor
final class SyncViewModel: ObservableObject {
    static let pollInterval: Duration = .seconds(4)
    static let discoveryTimeout: TimeInterval = 10

    enum OnboardingStep: Equatable {
        case scanning
        case joiningNetwork
        /// The in-app hotspot join is unavailable (e.g. free personal teams
        /// can't hold the Hotspot Configuration entitlement) or failed — the
        /// user joins the Bridge Wi-Fi in iOS Settings, then resumes.
        case manualJoinNeeded(ssid: String, psk: String?)
        case discovering
        case paired(deviceID: String)
        case failed(String)
    }

    struct Transfer: Identifiable, Equatable {
        enum State: Equatable {
            case waiting
            case downloading
            case saving
            case done
            case failed(String)
        }

        let id: String
        let fileName: String
        let sizeBytes: Int64
        var bytesReceived: Int64 = 0
        var state: State = .waiting

        var fractionComplete: Double {
            guard sizeBytes > 0 else { return 0 }
            return min(1, Double(bytesReceived) / Double(sizeBytes))
        }
    }

    // Pairing / onboarding
    @Published private(set) var pairing: StoredPairing?
    @Published private(set) var onboardingStep: OnboardingStep = .scanning

    // Bridge state
    @Published private(set) var bridgeStatus: BridgeStatus?
    @Published private(set) var isBridgeReachable = false

    // Sync state
    @Published private(set) var transfers: [Transfer] = []
    @Published private(set) var syncedCount: Int
    @Published private(set) var isSyncing = false
    @Published private(set) var lastError: String?

    var isPaired: Bool { pairing != nil }

    private let store: PairingStore
    private let hotspotJoiner = HotspotJoiner()
    private let browser = BridgeBrowser()
    private var client: SyncClient?
    private var pollTask: Task<Void, Never>?
    /// Parsed pairing held across the manual-join detour so the pipeline can
    /// resume at discovery once the user has joined the network themselves.
    private var pendingInfo: PairingInfo?

    init(store: PairingStore = PairingStore()) {
        self.store = store
        self.pairing = store.load()
        self.syncedCount = store.syncedItemIDs.count
        if let pairing {
            client = SyncClient(host: pairing.host, port: pairing.port, token: pairing.token)
        }
    }

    // MARK: - Onboarding

    /// Full pairing pipeline for a scanned QR payload:
    /// parse → join hotspot (when the QR carries credentials) → discover via
    /// Bonjour with the QR host as fallback → verify the token against
    /// `/v1/status` → persist. The published `pairing` flips only in
    /// `finishOnboarding()` so the "Paired" confirmation screen is visible;
    /// the pairing itself is already on disk by then.
    func completePairing(scannedCode: String) async {
        let info: PairingInfo
        do {
            info = try PairingInfo.parse(scannedCode)
        } catch {
            onboardingStep = .failed(error.localizedDescription)
            return
        }
        pendingInfo = info

        if let ssid = info.ssid, let psk = info.psk {
            onboardingStep = .joiningNetwork
            do {
                try await hotspotJoiner.join(ssid: ssid, passphrase: psk)
            } catch {
                // NEHotspotConfiguration is entitlement-gated (unavailable on
                // free personal teams) and can fail for other reasons; either
                // way the network itself is fine — hand the join to the user
                // and resume the pipeline afterwards.
                onboardingStep = .manualJoinNeeded(ssid: ssid, psk: info.psk)
                return
            }
        }

        await discoverAndVerify(info)
    }

    /// Called from the manual-join screen once the user has joined the
    /// Bridge Wi-Fi in iOS Settings; resumes the pipeline at discovery.
    func continueAfterManualJoin() async {
        guard let info = pendingInfo else {
            onboardingStep = .scanning
            return
        }
        await discoverAndVerify(info)
    }

    private func discoverAndVerify(_ info: PairingInfo) async {
        do {
            onboardingStep = .discovering
            let resolved = await browser.discover(
                deviceID: info.deviceID,
                timeout: Self.discoveryTimeout
            )
            let candidate = SyncClient(
                host: resolved?.host ?? info.host,
                port: resolved?.port ?? info.port,
                token: info.token
            )
            let status = try await Self.confirmStatus(with: candidate)

            try store.save(info)
            client = candidate
            bridgeStatus = status
            isBridgeReachable = true
            pendingInfo = nil
            onboardingStep = .paired(deviceID: info.deviceID)
        } catch {
            onboardingStep = .failed(error.localizedDescription)
        }
    }

    /// Called from the "Start syncing" confirmation; publishes the persisted
    /// pairing (which swaps the root view over to SyncView) and starts polling.
    func finishOnboarding() {
        pairing = store.load()
        onboardingStep = .scanning
        startAutoSync()
    }

    /// Returns to the scanner after a failed attempt.
    func restartOnboarding() {
        pendingInfo = nil
        onboardingStep = .scanning
    }

    /// Right after a hotspot join, DHCP on the Bridge network can take a few
    /// seconds to settle — retry the status probe with a growing backoff
    /// before declaring the pairing dead.
    private static func confirmStatus(
        with client: SyncClient,
        attempts: Int = 4
    ) async throws -> BridgeStatus {
        var lastError: Error = SyncClientError.invalidResponse
        for attempt in 0..<attempts {
            do {
                return try await client.status()
            } catch SyncClientError.unauthorized {
                throw SyncClientError.unauthorized // Retrying won't fix a bad token.
            } catch {
                lastError = error
                try? await Task.sleep(for: .seconds(Double(attempt + 1)))
            }
        }
        throw lastError
    }

    // MARK: - Lifecycle

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .active:
            startAutoSync()
        default:
            pauseAutoSync() // Foreground-only in v1 (plan 050) — no background claims.
        }
    }

    func startAutoSync() {
        guard isPaired, pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.syncOnce()
                try? await Task.sleep(for: Self.pollInterval)
            }
        }
    }

    func pauseAutoSync() {
        pollTask?.cancel()
        pollTask = nil
        UIApplication.shared.isIdleTimerDisabled = false
    }

    func syncNow() {
        Task { await syncOnce() }
    }

    // MARK: - Sync pass

    /// One status → queue → download/save/ack pass. Re-entrancy is guarded so
    /// "Sync now" during an auto-poll is a no-op.
    func syncOnce() async {
        guard isPaired, !isSyncing else { return }
        isSyncing = true
        defer { isSyncing = false }

        guard let client = await reachableClient() else {
            isBridgeReachable = false
            return
        }
        isBridgeReachable = true

        do {
            let pending = try await client.queue().filter { !store.isSynced($0.itemID) }
            lastError = nil
            guard !pending.isEmpty else { return }

            // Keep the screen (and Wi-Fi) alive during active transfers.
            UIApplication.shared.isIdleTimerDisabled = true
            defer { UIApplication.shared.isIdleTimerDisabled = false }

            for item in pending {
                guard !Task.isCancelled else { return }
                await transferItem(item, using: client)
            }
            bridgeStatus = try? await client.status()
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Probes the stored host first; if unreachable, re-browses Bonjour in
    /// case the Bridge's address changed (Same Wi-Fi mode with DHCP).
    private func reachableClient() async -> SyncClient? {
        guard let pairing else { return nil }
        if let client, let status = try? await client.status() {
            bridgeStatus = status
            return client
        }
        if let found = await browser.discover(deviceID: pairing.deviceID, timeout: 5) {
            let fresh = SyncClient(host: found.host, port: found.port, token: pairing.token)
            if let status = try? await fresh.status() {
                client = fresh
                bridgeStatus = status
                return fresh
            }
        }
        return nil
    }

    private func transferItem(_ item: PendingPhoto, using client: SyncClient) async {
        upsertTransfer(for: item)
        let stagingURL = Self.stagingURL(for: item)
        do {
            updateTransfer(item.itemID) { $0.state = .downloading }
            try await client.downloadPhoto(item, to: stagingURL) { [weak self] received in
                Task { @MainActor in
                    self?.updateTransfer(item.itemID) { $0.bytesReceived = received }
                }
            }

            updateTransfer(item.itemID) { $0.state = .saving }
            try await PhotoSaver.save(fileURL: stagingURL, fileName: item.fileName)
            try await client.acknowledge(item.itemID)

            try? FileManager.default.removeItem(at: stagingURL)
            store.markSynced(item.itemID)
            syncedCount = store.syncedItemIDs.count
            updateTransfer(item.itemID) {
                $0.bytesReceived = item.sizeBytes
                $0.state = .done
            }
        } catch is CancellationError {
            // Partial file stays on disk; the next pass resumes it via Range.
            updateTransfer(item.itemID) { $0.state = .waiting }
        } catch SyncClientError.checksumMismatch {
            // Corrupt bytes — do not resume from them.
            print("sync.transfer_checksum_mismatch file=\(item.fileName)")
            try? FileManager.default.removeItem(at: stagingURL)
            updateTransfer(item.itemID) { $0.state = .failed("Integrity check failed; will retry") }
        } catch {
            print("sync.transfer_failed file=\(item.fileName) error=\(String(describing: error))")
            updateTransfer(item.itemID) { $0.state = .failed(error.localizedDescription) }
        }
    }

    // MARK: - Forget / re-pair

    func forgetBridge() {
        pauseAutoSync()
        if let ssid = pairing?.ssid {
            hotspotJoiner.forget(ssid: ssid)
        }
        store.forget()
        pairing = nil
        client = nil
        bridgeStatus = nil
        transfers = []
        syncedCount = 0
        isBridgeReachable = false
        lastError = nil
        onboardingStep = .scanning
    }

    // MARK: - Transfer bookkeeping

    private func upsertTransfer(for item: PendingPhoto) {
        guard !transfers.contains(where: { $0.id == item.itemID }) else { return }
        transfers.insert(
            Transfer(id: item.itemID, fileName: item.fileName, sizeBytes: item.sizeBytes),
            at: 0
        )
    }

    private func updateTransfer(_ id: String, _ mutate: (inout Transfer) -> Void) {
        guard let index = transfers.firstIndex(where: { $0.id == id }) else { return }
        mutate(&transfers[index])
    }

    /// Partial downloads live in tmp under a per-item name so an interrupted
    /// transfer can resume across sync passes (cleared by the OS eventually).
    private static func stagingURL(for item: PendingPhoto) -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("sync-staging", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let fileExtension = (item.fileName as NSString).pathExtension
        var url = directory.appendingPathComponent(item.itemID)
        if !fileExtension.isEmpty {
            url.appendPathExtension(fileExtension)
        }
        return url
    }
}
