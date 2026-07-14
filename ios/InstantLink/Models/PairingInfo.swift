import Foundation

/// The payload of the pairing QR shown on the Bridge LCD (plan 050).
///
/// URL shape:
///
///     instantlink://pair?v=1&device=IB-XXXX&host=192.168.8.1&port=8721
///         &token=<hex>[&ssid=<ssid>&psk=<8 digits>]
///
/// `ssid`/`psk` are present only when the Bridge runs its own hotspot. Their
/// absence means "Same Wi-Fi" mode: the phone is expected to already be on the
/// Bridge's network and the join step is skipped.
struct PairingInfo: Equatable {
    static let scheme = "instantlink"
    static let pairHost = "pair"
    static let supportedVersion = 1
    static let defaultPort = 8721

    let version: Int
    let deviceID: String
    let host: String
    let port: Int
    let token: String
    let ssid: String?
    let psk: String?

    /// True when the QR carried hotspot credentials and the iOS app should
    /// join that network before discovery.
    var needsHotspotJoin: Bool { ssid != nil }

    enum ParseError: LocalizedError, Equatable {
        case notAPairingURL
        case unsupportedVersion(Int)
        case missingField(String)
        case invalidToken
        case invalidPSK

        var errorDescription: String? {
            switch self {
            case .notAPairingURL:
                return "This QR code is not an InstantLink pairing code."
            case .unsupportedVersion(let version):
                return "Pairing code version \(version) is not supported — update the iOS app."
            case .missingField(let name):
                return "The pairing code is missing its '\(name)' field."
            case .invalidToken:
                return "The pairing token in the QR code is malformed."
            case .invalidPSK:
                return "The network password in the QR code is malformed."
            }
        }
    }

    /// Parses and validates a scanned QR payload.
    static func parse(_ string: String) throws -> PairingInfo {
        guard let components = URLComponents(string: string),
              components.scheme?.lowercased() == scheme,
              components.host?.lowercased() == pairHost
        else { throw ParseError.notAPairingURL }

        var fields: [String: String] = [:]
        for item in components.queryItems ?? [] {
            if let value = item.value, !value.isEmpty { fields[item.name] = value }
        }

        guard let versionString = fields["v"], let version = Int(versionString) else {
            throw ParseError.missingField("v")
        }
        guard version == supportedVersion else {
            throw ParseError.unsupportedVersion(version)
        }
        guard let deviceID = fields["device"] else { throw ParseError.missingField("device") }
        guard let host = fields["host"] else { throw ParseError.missingField("host") }
        guard let token = fields["token"] else { throw ParseError.missingField("token") }
        guard !token.isEmpty, token.allSatisfy(\.isHexDigit) else {
            throw ParseError.invalidToken
        }
        let port = fields["port"].flatMap(Int.init) ?? defaultPort

        let ssid = fields["ssid"]
        let psk = fields["psk"]
        if ssid != nil {
            // Provisioning generates an 8-digit WPA2 PSK (like hotspot.psk).
            guard let psk, psk.count == 8, psk.allSatisfy(\.isNumber) else {
                throw ParseError.invalidPSK
            }
        }

        return PairingInfo(
            version: version,
            deviceID: deviceID,
            host: host,
            port: port,
            token: token,
            ssid: ssid,
            psk: ssid == nil ? nil : psk
        )
    }
}
