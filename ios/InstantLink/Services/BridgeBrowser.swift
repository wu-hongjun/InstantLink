import Foundation
import Network
import os

/// A Bridge advertisement resolved to a concrete host/port for URLSession.
struct ResolvedBridge: Equatable {
    let deviceID: String?
    let host: String
    let port: Int
}

/// Discovers the Bridge's `_instantlink._tcp` Bonjour service with NWBrowser.
///
/// The Bridge advertises TXT records `device` (e.g. `IB-XXXX`) and `proto`
/// (bridge sync/server.py). Discovery works both on the Bridge hotspot and in
/// Same Wi-Fi mode; callers fall back to the host baked into the pairing QR
/// when browsing times out.
final class BridgeBrowser {
    static let serviceType = "_instantlink._tcp"

    /// Browses for up to `timeout` seconds and returns the first advertisement
    /// matching `deviceID` (any advertisement when `deviceID` is nil), resolved
    /// to a host and port. Returns nil on timeout or browse failure.
    func discover(deviceID: String?, timeout: TimeInterval = 10) async -> ResolvedBridge? {
        for await result in browseResults(timeout: timeout) {
            if let deviceID,
               let advertised = Self.txtDeviceID(of: result),
               advertised != deviceID {
                continue // Some other Bridge on the network.
            }
            if let resolved = await resolve(result) {
                return resolved
            }
        }
        return nil
    }

    /// Raw browse results as an async stream; finishes after `timeout` seconds
    /// or when the browser fails. Results may repeat across change callbacks —
    /// consumers take the first acceptable one.
    func browseResults(timeout: TimeInterval) -> AsyncStream<NWBrowser.Result> {
        AsyncStream { continuation in
            let parameters = NWParameters()
            parameters.includePeerToPeer = true
            let browser = NWBrowser(
                for: .bonjourWithTXTRecord(type: Self.serviceType, domain: nil),
                using: parameters
            )
            browser.browseResultsChangedHandler = { results, _ in
                for result in results {
                    continuation.yield(result)
                }
            }
            browser.stateUpdateHandler = { state in
                if case .failed = state {
                    continuation.finish()
                }
            }
            browser.start(queue: .global(qos: .userInitiated))

            let timeoutTask = Task {
                try? await Task.sleep(for: .seconds(timeout))
                continuation.finish()
            }
            continuation.onTermination = { _ in
                timeoutTask.cancel()
                browser.cancel()
            }
        }
    }

    // MARK: - Resolution

    /// Bonjour results carry a service endpoint, not an address. URLSession
    /// needs host:port, so open a throwaway TCP connection and read the
    /// resolved remote endpoint off its path.
    private func resolve(_ result: NWBrowser.Result) async -> ResolvedBridge? {
        let deviceID = Self.txtDeviceID(of: result)
        return await withCheckedContinuation { continuation in
            let connection = NWConnection(to: result.endpoint, using: .tcp)
            // stateUpdateHandler calls are serialised on the connection queue,
            // but the compiler can't prove that — a lock keeps the
            // single-resume guard valid under Swift 6 strict concurrency.
            let didResume = OSAllocatedUnfairLock(initialState: false)
            connection.stateUpdateHandler = { state in
                let complete: (ResolvedBridge?) -> Void = { value in
                    let alreadyResumed = didResume.withLock { resumed in
                        defer { resumed = true }
                        return resumed
                    }
                    guard !alreadyResumed else { return }
                    connection.cancel()
                    continuation.resume(returning: value)
                }
                switch state {
                case .ready:
                    if case .hostPort(let host, let port)? = connection.currentPath?.remoteEndpoint {
                        complete(ResolvedBridge(
                            deviceID: deviceID,
                            host: Self.hostString(host),
                            port: Int(port.rawValue)
                        ))
                    } else {
                        complete(nil)
                    }
                case .failed, .cancelled:
                    complete(nil)
                default:
                    break
                }
            }
            connection.start(queue: DispatchQueue(label: "BridgeBrowser.resolve"))
        }
    }

    private static func txtDeviceID(of result: NWBrowser.Result) -> String? {
        guard case .bonjour(let txtRecord) = result.metadata else { return nil }
        return txtRecord.dictionary["device"]
    }

    private static func hostString(_ host: NWEndpoint.Host) -> String {
        let raw: String
        switch host {
        case .ipv4(let address):
            raw = "\(address)"
        case .ipv6(let address):
            raw = "\(address)"
        case .name(let name, _):
            raw = name
        @unknown default:
            raw = "\(host)"
        }
        // Strip any interface scope suffix (e.g. "fe80::1%en0").
        return raw.split(separator: "%").first.map(String.init) ?? raw
    }
}
