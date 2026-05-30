import CryptoKit
import Foundation

protocol BridgeClientKeyStore {
    func loadIdentity(for bridgeID: String) throws -> BridgeSigningIdentity?
    func createIdentity(for bridgeID: String, clientName: String) throws -> BridgeSigningIdentity
    func saveIdentity(_ identity: BridgeSigningIdentity, for bridgeID: String) throws
    func deleteIdentity(for bridgeID: String) throws
}

enum BridgeAuthError: Error, Equatable {
    case invalidBodyDigest(String)
}

struct BridgeSigningIdentity: Codable, Equatable {
    var bridgeID: String
    var clientID: String
    var clientName: String
    var algorithm: BridgeClientKeyAlgorithm
    var publicKey: String
    var privateKeyRawRepresentation: Data

    enum CodingKeys: String, CodingKey {
        case bridgeID = "bridge_id"
        case clientID = "client_id"
        case clientName = "client_name"
        case algorithm
        case publicKey = "public_key"
        case privateKeyRawRepresentation = "private_key_raw_representation"
    }

    static func generate(
        bridgeID: String,
        clientName: String,
        algorithm: BridgeClientKeyAlgorithm = .ed25519
    ) throws -> BridgeSigningIdentity {
        let clientID = BridgeManagementAuth.makeClientID()
        switch algorithm {
        case .ed25519:
            let privateKey = Curve25519.Signing.PrivateKey()
            return BridgeSigningIdentity(
                bridgeID: bridgeID,
                clientID: clientID,
                clientName: clientName,
                algorithm: algorithm,
                publicKey: BridgeManagementAuth.base64URLEncoded(privateKey.publicKey.rawRepresentation),
                privateKeyRawRepresentation: privateKey.rawRepresentation
            )
        case .p256SHA256:
            let privateKey = P256.Signing.PrivateKey()
            return BridgeSigningIdentity(
                bridgeID: bridgeID,
                clientID: clientID,
                clientName: clientName,
                algorithm: algorithm,
                publicKey: BridgeManagementAuth.base64URLEncoded(privateKey.publicKey.rawRepresentation),
                privateKeyRawRepresentation: privateKey.rawRepresentation
            )
        }
    }

    func signature(for payload: Data) throws -> Data {
        switch algorithm {
        case .ed25519:
            let privateKey = try Curve25519.Signing.PrivateKey(
                rawRepresentation: privateKeyRawRepresentation
            )
            return try privateKey.signature(for: payload)
        case .p256SHA256:
            let privateKey = try P256.Signing.PrivateKey(
                rawRepresentation: privateKeyRawRepresentation
            )
            return try privateKey.signature(for: payload).derRepresentation
        }
    }

    var pairingRequestPublicKeyAlgorithm: BridgeClientKeyAlgorithm {
        algorithm
    }
}

enum BridgeManagementAuth {
    static let requestSignatureContext = "instantlink-bridge-management-v1"
    static let clientIDHeader = "X-Bridge-Client-Id"
    static let timestampHeader = "X-Bridge-Timestamp"
    static let nonceHeader = "X-Bridge-Nonce"
    static let signatureHeader = "X-Bridge-Signature"
    static let requestIDHeader = "X-Request-Id"

    // The current Bridge manager verifies Ed25519 public keys and 64-byte signatures. The P-256
    // path exists only as a client-side scaffold for future server algorithm negotiation.
    static let productionSigningAlgorithm: BridgeClientKeyAlgorithm = .ed25519

    static func canonicalRequestPayload(
        method: String,
        path: String,
        bodySHA256: String,
        timestamp: Int,
        nonce: String
    ) throws -> Data {
        guard bodySHA256.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil else {
            throw BridgeAuthError.invalidBodyDigest(bodySHA256)
        }
        return Data(
            [
                requestSignatureContext,
                method.uppercased(),
                path,
                bodySHA256,
                String(timestamp),
                nonce,
            ].joined(separator: "\n").utf8
        )
    }

    static func signedHeaders(
        identity: BridgeSigningIdentity,
        method: String,
        path: String,
        body: Data,
        timestamp: Int,
        nonce: String
    ) throws -> [String: String] {
        let bodySHA256 = sha256Hex(body)
        let payload = try canonicalRequestPayload(
            method: method,
            path: path,
            bodySHA256: bodySHA256,
            timestamp: timestamp,
            nonce: nonce
        )
        let signature = try identity.signature(for: payload)
        return [
            clientIDHeader: identity.clientID,
            timestampHeader: String(timestamp),
            nonceHeader: nonce,
            signatureHeader: base64URLEncoded(signature),
        ]
    }

    static func makeNonce() -> String {
        UUID().uuidString
    }

    static func makeClientID() -> String {
        "macos-\(UUID().uuidString.lowercased())"
    }

    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func base64URLEncoded(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

