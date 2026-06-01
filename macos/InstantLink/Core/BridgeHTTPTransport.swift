import Foundation

enum BridgeHTTPTransportError: Error, Equatable {
    case invalidResponse
    case invalidURL(String)
    case httpStatus(Int)
}

final class BridgeHTTPTransport: BridgeTransport {
    static let uploadFilenameHeader = "X-Upload-Filename"

    private struct PackageRequest: Encodable {
        var package: BridgeUpdatePackage
    }

    private struct RollbackRequest: Encodable {
        var reason: String
    }

    private struct BackupRestoreRequest: Encodable {
        var backupID: String

        enum CodingKeys: String, CodingKey {
            case backupID = "backup_id"
        }
    }

    private struct BackupCreateRequest: Encodable {
        var passphrase: String
    }

    private struct BackupRestoreWithPassphraseRequest: Encodable {
        var backupID: String
        var passphrase: String

        enum CodingKeys: String, CodingKey {
            case backupID = "backup_id"
            case passphrase
        }
    }

    private let baseURL: URL
    private let session: URLSession
    private let keyStore: BridgeClientKeyStore
    private let clientName: String
    private let now: () -> Date
    private let nonce: () -> String
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    // Plan 040: per-device cache of the bridge's wall-clock epoch so
    // signed requests can target the bridge's clock rather than the
    // host's. The Pi has no RTC and no internet egress in default
    // headless mode, so its clock can sit arbitrarily off real wall
    // time — see ``BridgeServerClockCache``.
    private let clockCache: BridgeServerClockCache
    private let monotonicNow: () -> TimeInterval

    init(
        baseURL: URL,
        session: URLSession = .shared,
        keyStore: BridgeClientKeyStore = BridgeClientFileStore(),
        clientName: String = BridgeHTTPTransport.defaultClientName(),
        now: @escaping () -> Date = Date.init,
        nonce: @escaping () -> String = BridgeManagementAuth.makeNonce,
        clockCache: BridgeServerClockCache = BridgeServerClockCache(),
        monotonicNow: @escaping () -> TimeInterval = bridgeMonotonicNow
    ) {
        self.baseURL = baseURL
        self.session = session
        self.keyStore = keyStore
        self.clientName = clientName
        self.now = now
        self.nonce = nonce
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
        self.clockCache = clockCache
        self.monotonicNow = monotonicNow
    }

    func discover() async throws -> [BridgeDevice] {
        let envelope = try await send(
            try makeRequest(method: "GET", path: "/v1/hello")
        )
        var device = try envelope.requireDevice()
        if device.endpointURL == nil {
            device.endpointURL = baseURL
        }
        return [device]
    }

    func pairingStatus(device: BridgeDevice) async throws -> BridgePairingStatus {
        let envelope = try await send(
            try makeRequest(method: "GET", path: "/v1/pairing/status", device: device)
        )
        return try envelope.requirePairingStatus()
    }

    func completePairing(
        device: BridgeDevice,
        confirmationCode: String,
        clientName: String
    ) async throws -> BridgePairingCompletion {
        let resolvedClientName = clientName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? self.clientName
            : clientName
        let identity = try keyStore.loadIdentity(for: device.deviceID) ?? keyStore.createIdentity(
            for: device.deviceID,
            clientName: resolvedClientName
        )
        let pairingRequest = BridgePairingCompleteRequest(
            clientID: identity.clientID,
            clientName: identity.clientName,
            publicKey: identity.publicKey,
            publicKeyAlgorithm: identity.pairingRequestPublicKeyAlgorithm,
            confirmationCode: confirmationCode,
            expectedDeviceID: device.deviceID,
            expectedManagementPublicKeyFingerprint: device.managementPublicKeyFingerprint
        )
        let envelope = try await send(
            try makeRequest(
                method: "POST",
                path: "/v1/pairing/complete",
                body: encoder.encode(pairingRequest),
                device: device
            )
        )
        let completion = try envelope.requirePairingCompletion()
        try keyStore.saveIdentity(identity, for: device.deviceID)
        return completion
    }

    func usbAutoTrust(
        device: BridgeDevice,
        clientName: String
    ) async throws -> BridgePairingCompletion {
        let resolvedClientName = clientName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? self.clientName
            : clientName
        let identity = try keyStore.loadIdentity(for: device.deviceID) ?? keyStore.createIdentity(
            for: device.deviceID,
            clientName: resolvedClientName
        )
        let autoTrustRequest = BridgeUSBAutoTrustRequest(
            clientID: identity.clientID,
            clientName: identity.clientName,
            publicKey: identity.publicKey,
            publicKeyAlgorithm: identity.pairingRequestPublicKeyAlgorithm,
            expectedDeviceID: device.deviceID
        )
        let envelope = try await send(
            try makeRequest(
                method: "POST",
                path: "/v1/pairing/usb_auto_trust",
                body: encoder.encode(autoTrustRequest),
                device: device
            )
        )
        let completion = try envelope.requirePairingCompletion()
        try keyStore.saveIdentity(identity, for: device.deviceID)
        return completion
    }

    func forgetLocalAuth(device: BridgeDevice) async throws {
        try keyStore.deleteIdentity(for: device.deviceID)
    }

    func status(device: BridgeDevice) async throws -> BridgeStatus {
        let envelope = try await sendSigned(method: "GET", path: "/v1/status", device: device)
        return try envelope.requireStatus()
    }

    func getConfig(device: BridgeDevice) async throws -> BridgeConfig {
        let envelope = try await sendSigned(method: "GET", path: "/v1/config", device: device)
        return try envelope.requireConfig()
    }

    func getAdjustmentsSchema(device: BridgeDevice) async throws -> BridgeConfigSchema {
        let envelope = try await sendSigned(
            method: "GET",
            path: "/v1/config/schema/adjustments",
            device: device
        )
        return try envelope.requireSchema()
    }

    func putConfig(device: BridgeDevice, diff: [String: Any]) async throws -> BridgeConfig {
        let body = try JSONSerialization.data(
            withJSONObject: ["config": diff],
            options: [.sortedKeys]
        )
        do {
            let envelope = try await sendSigned(
                method: "PUT",
                path: "/v1/config",
                body: body,
                device: device
            )
            return try envelope.requireConfig()
        } catch let error as BridgeAPIError where error.code == "config_validation_failed" {
            throw Self.makeValidationError(from: error)
        }
    }

    private static func makeValidationError(from error: BridgeAPIError) -> BridgeConfigValidationError {
        var fieldErrors: [String: String] = [:]
        if case .object(let detailObject) = error.payload.details["field_errors"] {
            for (key, value) in detailObject {
                if case .string(let message) = value {
                    fieldErrors[key] = message
                }
            }
        } else {
            for (key, value) in error.payload.details {
                if case .string(let message) = value {
                    fieldErrors[key] = message
                }
            }
        }
        return BridgeConfigValidationError(
            fieldErrors: fieldErrors,
            message: error.payload.message
        )
    }

    func preflightUpdate(device: BridgeDevice, package: BridgeUpdatePackage) async throws -> BridgeUpdatePreflight {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/update/preflight",
            body: encoder.encode(PackageRequest(package: package)),
            device: device
        )
        return try envelope.requirePreflight()
    }

    func startUpdate(device: BridgeDevice, package: BridgeUpdatePackage) async throws -> BridgeUpdateState {
        let preflight = try await preflightUpdate(device: device, package: package)
        guard preflight.allowed else {
            throw BridgeTransportError.updatePreflightFailed
        }
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/update/install",
            body: encoder.encode(PackageRequest(package: package)),
            device: device
        )
        return try envelope.requireUpdateState()
    }

    func updateStatus(device: BridgeDevice, operationID: String) async throws -> BridgeUpdateState {
        let envelope = try await sendSigned(
            method: "GET",
            path: "/v1/update/status",
            queryItems: [URLQueryItem(name: "operation_id", value: operationID)],
            device: device
        )
        return try envelope.requireUpdateState()
    }

    func updateEvents(device: BridgeDevice, operationID: String) async throws -> AsyncThrowingStream<BridgeUpdateEvent, Error> {
        let envelope = try await sendSigned(
            method: "GET",
            path: "/v1/events",
            queryItems: [URLQueryItem(name: "operation_id", value: operationID)],
            device: device
        )
        let event = try envelope.requireUpdateEvent()
        return AsyncThrowingStream { continuation in
            continuation.yield(event)
            continuation.finish()
        }
    }

    func uploadUpdate(device: BridgeDevice, package: BridgeUpdatePackage) async throws -> BridgeUploadResult {
        let data = try Data(contentsOf: package.archiveURL)
        let filename = package.archiveURL.lastPathComponent
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/update/upload",
            body: data,
            contentType: "application/octet-stream",
            extraHeaders: [BridgeHTTPTransport.uploadFilenameHeader: filename],
            device: device
        )
        return try envelope.requireUpload()
    }

    func markUpdateGood(device: BridgeDevice) async throws -> BridgeUpdateState {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/update/mark-good",
            device: device
        )
        return try envelope.requireUpdateState()
    }

    func rollbackUpdate(device: BridgeDevice, reason: String) async throws -> BridgeUpdateState {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/update/rollback",
            body: encoder.encode(RollbackRequest(reason: reason)),
            device: device
        )
        return try envelope.requireUpdateState()
    }

    func createBackup(device: BridgeDevice) async throws -> BridgeBackupResult {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/backup/create",
            device: device
        )
        return try envelope.requireBackup()
    }

    func restoreBackup(device: BridgeDevice, backupID: String) async throws -> BridgeBackupRestoreResult {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/backup/restore",
            body: encoder.encode(BackupRestoreRequest(backupID: backupID)),
            device: device
        )
        return try envelope.requireBackupRestore()
    }

    func createBackup(device: BridgeDevice, passphrase: String) async throws -> BridgeBackupResult {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/backup/create",
            body: encoder.encode(BackupCreateRequest(passphrase: passphrase)),
            device: device
        )
        return try envelope.requireBackup()
    }

    func restoreBackup(
        device: BridgeDevice,
        backupID: String,
        passphrase: String
    ) async throws -> BridgeBackupRestoreResult {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/backup/restore",
            body: encoder.encode(
                BackupRestoreWithPassphraseRequest(backupID: backupID, passphrase: passphrase)
            ),
            device: device
        )
        return try envelope.requireBackupRestore()
    }

    // MARK: Phase E — diagnostics + recovery

    func streamLogs(
        device: BridgeDevice,
        level: BridgeLogLevel
    ) -> AsyncThrowingStream<BridgeLogEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let levelQuery = level == .info
                        ? "all"
                        : level.rawValue
                    // SSE is a long-lived connection that the
                    // ``sendSigned`` retry path cannot wrap, so we
                    // pre-anchor against ``/v1/time`` if the cache is
                    // empty and on a 401 with a clock-skew code we
                    // refresh once and re-open. This keeps the log
                    // viewer usable on a cold-booted bridge with an
                    // arbitrarily stale clock.
                    let timestamp = await self.currentSigningTimestamp(for: device)
                    let request = try self.makeRequest(
                        method: "GET",
                        path: "/v1/logs/stream",
                        queryItems: [URLQueryItem(name: "level", value: levelQuery)],
                        body: Data(),
                        contentType: "application/json",
                        extraHeaders: ["Accept": "text/event-stream"],
                        device: device,
                        signedFor: device,
                        timestamp: timestamp
                    )
                    var (bytes, response) = try await self.session.bytes(for: request)
                    if let http = response as? HTTPURLResponse, http.statusCode == 401 {
                        // Re-anchor against ``/v1/time`` and try once
                        // more. The SSE response body is plain text and
                        // does not carry the bridge's typed
                        // ``error_code``, so we cannot distinguish a
                        // clock-skew 401 from a genuine auth 401 at
                        // this layer — retrying once is cheap and
                        // covers the cold-boot bridge case; a second
                        // 401 is treated as real auth failure below.
                        await self.clockCache.invalidate(deviceID: device.deviceID)
                        let refreshed = try await self.refreshServerEpoch(for: device)
                        let retryRequest = try self.makeRequest(
                            method: "GET",
                            path: "/v1/logs/stream",
                            queryItems: [URLQueryItem(name: "level", value: levelQuery)],
                            body: Data(),
                            contentType: "application/json",
                            extraHeaders: ["Accept": "text/event-stream"],
                            device: device,
                            signedFor: device,
                            timestamp: refreshed
                        )
                        (bytes, response) = try await self.session.bytes(for: retryRequest)
                    }
                    guard let http = response as? HTTPURLResponse else {
                        throw BridgeHTTPTransportError.invalidResponse
                    }
                    if http.statusCode == 401 {
                        let envelope = BridgeErrorPayload(message: "Bridge access requires pairing.")
                        throw BridgeAPIError(
                            requestID: http.value(forHTTPHeaderField: "X-Request-Id") ?? "unknown",
                            code: .authRequired,
                            payload: envelope
                        )
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        throw BridgeHTTPTransportError.httpStatus(http.statusCode)
                    }

                    // SSE: data lines (data: <json>) followed by a blank
                    // line. Other line shapes (id:, event:, retry:, comments
                    // starting with `:`) are ignored.
                    let decoder = JSONDecoder()
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard line.hasPrefix("data: ") else { continue }
                        let payload = String(line.dropFirst("data: ".count))
                        guard let data = payload.data(using: .utf8) else { continue }
                        if let event = try? decoder.decode(BridgeLogEvent.self, from: data) {
                            continuation.yield(event)
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    func createSupportBundle(device: BridgeDevice) async throws -> BridgeSupportBundleResult {
        let envelope = try await sendSigned(
            method: "POST",
            path: "/v1/support-bundle/create",
            device: device
        )
        try envelope.requireOK()
        guard let supportBundle = envelope.supportBundle else {
            throw BridgeAPIError.missingPayload(
                requestID: envelope.requestID,
                payloadName: "support_bundle"
            )
        }
        return supportBundle
    }

    func restartManagement(device: BridgeDevice) async throws {
        do {
            let envelope = try await sendSigned(
                method: "POST",
                path: "/v1/management/restart",
                device: device
            )
            try envelope.requireOK()
        } catch let error as BridgeHTTPTransportError {
            if case .httpStatus(404) = error {
                // Older bridges don't expose the restart route. Surface a
                // typed error so the recovery UI can fall back to "ask the
                // user to power-cycle the bridge".
                throw BridgeTransportError.managementRestartFailed("Bridge does not support the restart route.")
            }
            throw error
        }
    }

    func helloProbe(endpoint: URL) async throws -> BridgeDevice {
        let url = try makeURL(base: endpoint, path: "/v1/hello", queryItems: [])
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(UUID().uuidString, forHTTPHeaderField: BridgeManagementAuth.requestIDHeader)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BridgeHTTPTransportError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw BridgeHTTPTransportError.httpStatus(http.statusCode)
        }
        let envelope = try decoder.decode(BridgeAPIEnvelope.self, from: data)
        var device = try envelope.requireDevice()
        if device.endpointURL == nil {
            device.endpointURL = endpoint
        }
        return device
    }

    private func makeRequest(
        method: String,
        path: String,
        queryItems: [URLQueryItem] = [],
        body: Data = Data(),
        contentType: String = "application/json",
        extraHeaders: [String: String] = [:],
        device: BridgeDevice? = nil,
        signedFor signedDevice: BridgeDevice? = nil,
        timestamp: Int? = nil
    ) throws -> URLRequest {
        let endpoint = signedDevice?.endpointURL ?? device?.endpointURL ?? baseURL
        let url = try makeURL(base: endpoint, path: path, queryItems: queryItems)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(UUID().uuidString, forHTTPHeaderField: BridgeManagementAuth.requestIDHeader)
        for (name, value) in extraHeaders {
            request.setValue(value, forHTTPHeaderField: name)
        }
        if !body.isEmpty {
            request.httpBody = body
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }

        if let signedDevice {
            guard let identity = try keyStore.loadIdentity(for: signedDevice.deviceID) else {
                throw BridgeTransportError.localAuthNotFound(signedDevice.deviceID)
            }
            // ``timestamp`` is normally supplied by ``sendSigned`` after a
            // ``BridgeServerClockCache`` lookup; the fallback to the host's
            // wall clock matters only on the very first signed call before
            // any sample has been recorded.
            let resolvedTimestamp = timestamp ?? Int(now().timeIntervalSince1970)
            let headers = try BridgeManagementAuth.signedHeaders(
                identity: identity,
                method: method,
                path: canonicalPath(for: url),
                body: body,
                timestamp: resolvedTimestamp,
                nonce: nonce()
            )
            for (name, value) in headers {
                request.setValue(value, forHTTPHeaderField: name)
            }
        }

        return request
    }

    // MARK: - Plan 040 — server-anchored timestamps

    /// Fetch the bridge's current wall-clock epoch and record it in the
    /// cache anchored against the host's monotonic clock.
    ///
    /// Used by ``sendSigned`` to re-anchor after a ``timestamp_future`` /
    /// ``stale`` rejection, and is the only place the unsigned ``/v1/time``
    /// route is consumed.
    private func refreshServerEpoch(for device: BridgeDevice) async throws -> Int {
        let url = try makeURL(base: device.endpointURL ?? baseURL, path: "/v1/time", queryItems: [])
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(UUID().uuidString, forHTTPHeaderField: BridgeManagementAuth.requestIDHeader)
        let envelope = try await send(request)
        try envelope.requireOK()
        guard let epoch = envelope.epoch else {
            throw BridgeAPIError.missingPayload(requestID: envelope.requestID, payloadName: "epoch")
        }
        let monotonic = monotonicNow()
        await clockCache.record(
            deviceID: device.deviceID,
            serverEpoch: epoch,
            monotonicNow: monotonic
        )
        return epoch
    }

    /// Return the timestamp to sign with for ``device``.
    ///
    /// First call returns the host's wall clock (cache empty) so the happy
    /// path never pays an extra round-trip. After a ``timestamp_future`` /
    /// ``stale`` rejection the cache is populated and subsequent calls
    /// return the bridge-anchored time instead.
    private func currentSigningTimestamp(for device: BridgeDevice) async -> Int {
        if let cached = await clockCache.serverEpoch(
            forDeviceID: device.deviceID,
            monotonicNow: monotonicNow()
        ) {
            return cached
        }
        return Int(now().timeIntervalSince1970)
    }

    /// Sign + send a request and, on a clock-skew rejection, re-anchor
    /// against ``/v1/time`` and retry once.
    ///
    /// The retry is single-shot: a second clock-skew failure surfaces the
    /// error rather than spinning, so a genuinely broken bridge clock or
    /// a stuck retry loop stays visible. Non-clock errors are propagated
    /// unchanged.
    private func sendSigned(
        method: String,
        path: String,
        queryItems: [URLQueryItem] = [],
        body: Data = Data(),
        contentType: String = "application/json",
        extraHeaders: [String: String] = [:],
        device: BridgeDevice
    ) async throws -> BridgeAPIEnvelope {
        let firstTimestamp = await currentSigningTimestamp(for: device)
        do {
            return try await send(
                try makeRequest(
                    method: method,
                    path: path,
                    queryItems: queryItems,
                    body: body,
                    contentType: contentType,
                    extraHeaders: extraHeaders,
                    signedFor: device,
                    timestamp: firstTimestamp
                )
            )
        } catch let apiError as BridgeAPIError where Self.isClockSkewError(apiError) {
            await clockCache.invalidate(deviceID: device.deviceID)
            let refreshed = try await refreshServerEpoch(for: device)
            return try await send(
                try makeRequest(
                    method: method,
                    path: path,
                    queryItems: queryItems,
                    body: body,
                    contentType: contentType,
                    extraHeaders: extraHeaders,
                    signedFor: device,
                    timestamp: refreshed
                )
            )
        }
    }

    private static func isClockSkewError(_ error: BridgeAPIError) -> Bool {
        error.code == .timestampFuture || error.code == .timestampStale
    }

    private func send(_ request: URLRequest) async throws -> BridgeAPIEnvelope {
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw BridgeHTTPTransportError.invalidResponse
        }

        if let envelope = try? decoder.decode(BridgeAPIEnvelope.self, from: data) {
            if (200..<300).contains(httpResponse.statusCode) {
                return envelope
            }
            try envelope.requireOK()
        }

        throw BridgeHTTPTransportError.httpStatus(httpResponse.statusCode)
    }

    private func makeURL(
        base: URL,
        path: String,
        queryItems: [URLQueryItem]
    ) throws -> URL {
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw BridgeHTTPTransportError.invalidURL(base.absoluteString)
        }
        let basePath = components.percentEncodedPath.trimmingTrailingSlash()
        let normalizedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        components.percentEncodedPath = "\(basePath)/\(normalizedPath)"
        components.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components.url else {
            throw BridgeHTTPTransportError.invalidURL(base.absoluteString)
        }
        return url
    }

    private func canonicalPath(for url: URL) -> String {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url.path
        }
        if let query = components.percentEncodedQuery, !query.isEmpty {
            return "\(components.percentEncodedPath)?\(query)"
        }
        return components.percentEncodedPath
    }

    private static func defaultClientName() -> String {
        let hostName = Host.current().localizedName ?? ProcessInfo.processInfo.hostName
        return hostName.isEmpty ? "InstantLink Mac" : hostName
    }
}

private extension String {
    func trimmingTrailingSlash() -> String {
        guard hasSuffix("/") else { return self }
        return String(dropLast()).trimmingTrailingSlash()
    }
}
