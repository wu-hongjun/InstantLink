import Foundation
import NetworkExtension

/// Joins the Bridge's WPA2 hotspot via NEHotspotConfiguration.
///
/// The configuration is persistent (`joinOnce = false`) so re-opening the iOS
/// app near the Bridge reconnects without re-scanning the QR. Requires the
/// `com.apple.developer.networking.HotspotConfiguration` entitlement.
///
/// The Bridge hotspot has no internet. App-initiated joins are supposed to
/// tolerate captive-less networks, but iOS has been known to drop aggressive
/// no-internet networks anyway — this is the first item on the on-device test
/// checklist in ios/README.md.
struct HotspotJoiner {
    enum JoinError: LocalizedError {
        case userDenied
        case system(Error)

        var errorDescription: String? {
            switch self {
            case .userDenied:
                return "Joining the Bridge network was declined."
            case .system(let error):
                return error.localizedDescription
            }
        }
    }

    /// Applies the hotspot configuration and waits for the system to finish.
    /// "Already associated" counts as success.
    func join(ssid: String, passphrase: String) async throws {
        let configuration = NEHotspotConfiguration(ssid: ssid, passphrase: passphrase, isWEP: false)
        configuration.joinOnce = false

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            NEHotspotConfigurationManager.shared.apply(configuration) { error in
                guard let error else {
                    return continuation.resume()
                }
                let nsError = error as NSError
                if nsError.domain == NEHotspotConfigurationErrorDomain {
                    switch NEHotspotConfigurationError(rawValue: nsError.code) {
                    case .alreadyAssociated:
                        return continuation.resume() // Already on the Bridge network.
                    case .userDenied:
                        return continuation.resume(throwing: JoinError.userDenied)
                    default:
                        break
                    }
                }
                continuation.resume(throwing: JoinError.system(error))
            }
        }
    }

    /// Removes the persisted configuration (used by "Forget this Bridge").
    func forget(ssid: String) {
        NEHotspotConfigurationManager.shared.removeConfiguration(forSSID: ssid)
    }
}
