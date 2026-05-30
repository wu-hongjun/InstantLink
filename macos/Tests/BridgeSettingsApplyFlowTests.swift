import Foundation

@MainActor
final class BridgeSettingsApplyFlowTests {
    private func makeDevice() -> BridgeDevice {
        BridgeDevice(
            deviceID: "IB-APPLY",
            displayName: "InstantLink Bridge",
            softwareVersion: "0.1.20",
            apiVersion: "v1",
            managementPublicKeyFingerprint: nil,
            pairingOpen: false,
            networkLabels: ["USB IP"],
            endpointURL: URL(string: "http://192.168.7.1:8742"),
            isPaired: true
        )
    }

    private func makeTransport(
        device: BridgeDevice,
        config: BridgeConfig
    ) async -> InMemoryBridgeTransport {
        let status = BridgeStatus(
            deviceID: device.deviceID,
            displayName: device.displayName,
            bridgeVersion: device.softwareVersion,
            apiVersion: device.apiVersion,
            readiness: .ready,
            activeUploadMode: .bridgeWiFi
        )
        let transport = InMemoryBridgeTransport(
            devices: [device],
            statuses: [device.deviceID: status]
        )
        await transport.setConfig(config, for: device.deviceID)
        return transport
    }

    func testApplyHappyPath() async throws {
        let device = makeDevice()
        let transport = await makeTransport(device: device, config: .defaults)
        let draft = BridgeSettingsDraft()
        let loaded = try await transport.getConfig(device: device)
        draft.load(loaded)
        draft.draft?.printer.quality = 80
        try expectTrue(draft.validate())
        let diff = draft.diff()
        draft.beginApplying()
        let updated = try await transport.putConfig(device: device, diff: diff)
        draft.recordApplySuccess(updated)
        try expectEqual(draft.loaded?.printer.quality, 80)
        try expectFalse(draft.isDirty)
        switch draft.applyState {
        case .succeeded:
            break
        default:
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected succeeded state")
        }
    }

    func testApplyValidationErrorSurfacesFieldErrors() async throws {
        let device = makeDevice()
        let transport = await makeTransport(device: device, config: .defaults)
        await transport.setConfigValidationError(
            ["printer.quality": "JPEG quality must be 1..100."],
            for: device.deviceID
        )

        let draft = BridgeSettingsDraft()
        let loaded = try await transport.getConfig(device: device)
        draft.load(loaded)
        draft.draft?.printer.quality = 50
        try expectTrue(draft.validate())
        let diff = draft.diff()
        draft.beginApplying()
        do {
            _ = try await transport.putConfig(device: device, diff: diff)
            throw MacTestFailure(
                file: #filePath,
                line: #line,
                message: "Expected validation error"
            )
        } catch let error as BridgeConfigValidationError {
            draft.recordApplyFailure(message: error.message, fieldErrors: error.fieldErrors)
        }
        try expectEqual(draft.fieldErrors[.printerJPEGQuality], "JPEG quality must be 1..100.")
        switch draft.applyState {
        case .failed:
            break
        default:
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected failed state")
        }
    }

    func testApplyNetworkErrorShowsManagementUnavailable() async throws {
        let device = makeDevice()
        let transport = await makeTransport(device: device, config: .defaults)
        let draft = BridgeSettingsDraft()
        let loaded = try await transport.getConfig(device: device)
        draft.load(loaded)
        draft.draft?.printer.quality = 90
        // Force the transport into an error state by forgetting auth.
        try await transport.forgetLocalAuth(device: device)
        draft.beginApplying()
        do {
            _ = try await transport.putConfig(device: device, diff: draft.diff())
            throw MacTestFailure(
                file: #filePath,
                line: #line,
                message: "Expected network error"
            )
        } catch {
            draft.recordApplyFailure(message: "Management service unavailable")
        }
        switch draft.applyState {
        case .failed(let message):
            try expectEqual(message, "Management service unavailable")
        default:
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected failed state")
        }
    }

    func testApplySkippedWhenClientValidationFails() async throws {
        let device = makeDevice()
        let transport = await makeTransport(device: device, config: .defaults)
        let draft = BridgeSettingsDraft()
        let loaded = try await transport.getConfig(device: device)
        draft.load(loaded)
        draft.draft?.printer.quality = 0
        let valid = draft.validate()
        try expectFalse(valid)
        // putConfig must NOT be called when client validation fails.
        let calls = await transport.putConfigCalls
        try expectEqual(calls, 0)
    }

    func testApplyDoesNotMutateLoadedOnFailure() async throws {
        let device = makeDevice()
        let transport = await makeTransport(device: device, config: .defaults)
        await transport.setConfigValidationError(
            ["printer.quality": "bad"],
            for: device.deviceID
        )
        let draft = BridgeSettingsDraft()
        let loaded = try await transport.getConfig(device: device)
        draft.load(loaded)
        draft.draft?.printer.quality = 50
        draft.beginApplying()
        do {
            _ = try await transport.putConfig(device: device, diff: draft.diff())
        } catch let error as BridgeConfigValidationError {
            draft.recordApplyFailure(message: error.message, fieldErrors: error.fieldErrors)
        }
        try expectEqual(draft.loaded?.printer.quality, 100)
    }

    func testApplyAcceptsServerCounterproposal() async throws {
        // Pre-load the bridge with one config; PUT a different one. The
        // in-memory transport returns the freshly-applied config (no clamp
        // here), and the draft should refresh its loaded snapshot to match
        // exactly what the server returned.
        let device = makeDevice()
        let transport = await makeTransport(device: device, config: .defaults)
        let draft = BridgeSettingsDraft()
        let loaded = try await transport.getConfig(device: device)
        draft.load(loaded)
        draft.draft?.adjustments.watermarkText = "Server sees this"
        try expectTrue(draft.validate())
        draft.beginApplying()
        let updated = try await transport.putConfig(device: device, diff: draft.diff())
        draft.recordApplySuccess(updated)
        try expectEqual(draft.loaded?.adjustments.watermarkText, "Server sees this")
    }
}
