private final class FakePrinterConnectionFFI: PrinterConnectionFFIBoundary {
    var supportsConnectionStageCallbacks: Bool = false
    var scanResultsQueue: [[String]] = []
    var connectResults: [String: Bool] = [:]
    var statusResult: PrinterConnectionFFIStatus?
    var modelResult: String? = "Instax Mini Link 3"

    private(set) var disconnectCalls = 0
    private(set) var connectCalls: [(String, Int)] = []
    private(set) var scanCalls: [Int] = []

    func scanPrinters(duration: Int) async -> [String] {
        scanCalls.append(duration)
        return scanResultsQueue.isEmpty ? [] : scanResultsQueue.removeFirst()
    }

    func connectNamedPrinter(_ device: String, duration: Int) async -> Bool {
        connectCalls.append((device, duration))
        return connectResults[device] ?? false
    }

    func connectNamedPrinter(
        _ device: String,
        duration: Int,
        progress: @escaping @Sendable (ConnectionStageUpdate) -> Void
    ) async -> Bool {
        connectCalls.append((device, duration))
        return connectResults[device] ?? false
    }

    func disconnectPrinter() async {
        disconnectCalls += 1
    }

    func fetchConnectionStatus() async -> PrinterConnectionFFIStatus? {
        statusResult
    }

    func fetchConnectedPrinterModel() async -> String? {
        modelResult
    }
}

@MainActor
final class PrinterConnectionCoordinatorTests {
    private func makeProfile(_ id: String, model: String = "Instax Mini Link 3") -> PrinterProfile {
        PrinterProfile(
            bleIdentifier: id,
            serialNumber: PrinterProfile.parseSerialNumber(from: id),
            detectedModel: model
        )
    }

    func testTargetedReconnectSuccessUpdatesConnectedSnapshot() async throws {
        let ffi = FakePrinterConnectionFFI()
        ffi.connectResults["INSTAX-11111111"] = true
        ffi.statusResult = PrinterConnectionFFIStatus(battery: 72, filmRemaining: 5, isCharging: false, printCount: 12)

        let coordinator = PrinterConnectionCoordinator(
            ffi: ffi,
            initialSnapshot: PrinterConnectionSnapshot(selectedPrinter: "INSTAX-11111111"),
            initialProfiles: ["INSTAX-11111111": self.makeProfile("INSTAX-11111111")]
        )

        coordinator.startPairingLoop()
        let connected = await waitUntil {
            coordinator.snapshot.isConnected
        }
        try expectTrue(connected, "Expected reconnect to establish a connected snapshot")

        try expectEqual(ffi.connectCalls.first?.0, "INSTAX-11111111")
        try expectTrue(coordinator.snapshot.isConnected)
        try expectEqual(coordinator.snapshot.printerName, "INSTAX-11111111")
        try expectEqual(coordinator.snapshot.printerModel, "Instax Mini Link 3")
        try expectEqual(coordinator.snapshot.filmRemaining, 5)
        try expectEqual(coordinator.snapshot.pairingRecoveryMode, .none)
    }

    func testFailedReconnectFallsBackToRecoveryScan() async throws {
        let ffi = FakePrinterConnectionFFI()
        ffi.connectResults["INSTAX-22222222"] = false
        ffi.scanResultsQueue = [["INSTAX-22222222", "INSTAX-33333333"]]

        let coordinator = PrinterConnectionCoordinator(
            ffi: ffi,
            initialSnapshot: PrinterConnectionSnapshot(selectedPrinter: "INSTAX-22222222"),
            initialProfiles: ["INSTAX-22222222": self.makeProfile("INSTAX-22222222")]
        )

        coordinator.startPairingLoop()
        let recovered = await waitUntil {
            coordinator.snapshot.pairingRecoveryMode == .reconnectFallback
        }
        try expectTrue(recovered, "Expected reconnect failure to enter recovery mode")

        try expectFalse(coordinator.snapshot.isPairing)
        try expectEqual(coordinator.snapshot.pairingRecoveryTarget, "INSTAX-22222222")
        try expectEqual(coordinator.snapshot.selectedPrinter, "INSTAX-22222222")
        try expectEqual(coordinator.snapshot.availablePrinters, ["INSTAX-22222222", "INSTAX-33333333"])
        try expectEqual(coordinator.snapshot.nearbyPrinters, ["INSTAX-33333333"])
    }

    func testRefreshDropsConnectedStateWhenStatusIsUnavailable() async throws {
        let ffi = FakePrinterConnectionFFI()
        ffi.statusResult = nil
        let coordinator = PrinterConnectionCoordinator(
            ffi: ffi,
            initialSnapshot: PrinterConnectionSnapshot(
                isConnected: true,
                printerName: "INSTAX-44444444",
                printerModel: "Instax Mini Link 3",
                battery: 80,
                isCharging: false,
                filmRemaining: 10,
                printCount: 20
            )
        )

        let refreshed = await coordinator.refresh()

        try expectFalse(refreshed)
        try expectFalse(coordinator.snapshot.isConnected)
        try expectEqual(coordinator.snapshot.pairingPhase, .idle)
    }

    func testDeletingActiveProfileReentersPairingFlow() async throws {
        let ffi = FakePrinterConnectionFFI()
        ffi.scanResultsQueue = [[]]

        let coordinator = PrinterConnectionCoordinator(
            ffi: ffi,
            initialSnapshot: PrinterConnectionSnapshot(
                isConnected: true,
                printerName: "INSTAX-55555555",
                printerModel: "Instax Mini Link 3",
                selectedPrinter: "INSTAX-55555555"
            ),
            initialProfiles: ["INSTAX-55555555": self.makeProfile("INSTAX-55555555")]
        )

        coordinator.deleteProfile("INSTAX-55555555")
        let enteredPairing = await waitUntil {
            coordinator.snapshot.isPairing && ffi.disconnectCalls == 1
        }
        try expectTrue(enteredPairing, "Expected deleting the active profile to enter pairing mode")

        try expectFalse(coordinator.snapshot.isConnected)
        try expectEqual(ffi.disconnectCalls, 1)
        try expectEqual(coordinator.snapshot.selectedPrinter, nil)
        try expectEqual(coordinator.snapshot.pairingRecoveryMode, .none)
    }
}
