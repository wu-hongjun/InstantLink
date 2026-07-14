import CryptoKit
import Foundation

enum SyncClientError: LocalizedError {
    case unauthorized
    case httpStatus(Int)
    case invalidResponse
    case checksumMismatch(expected: String, actual: String)

    var errorDescription: String? {
        switch self {
        case .unauthorized:
            return "The Bridge rejected the pairing token. Re-pair from Settings."
        case .httpStatus(let code):
            return "The Bridge returned HTTP \(code)."
        case .invalidResponse:
            return "The Bridge sent an unexpected response."
        case .checksumMismatch:
            return "The downloaded photo failed its integrity check."
        }
    }
}

/// URLSession client for the Bridge sync HTTP API on :8721.
///
/// Every request carries `Authorization: Bearer <pair-token>`. Transport is
/// plain HTTP in v1 — the WPA2 hotspot provides L2 encryption; TLS with a
/// pinned self-signed certificate is a v1.5 hardening item (plan 050).
final class SyncClient {
    let baseURL: URL
    private let token: String
    private let session: URLSession
    private let decoder: JSONDecoder

    private static let writeChunkSize = 64 * 1024

    init(host: String, port: Int, token: String) {
        var components = URLComponents()
        components.scheme = "http"
        components.host = host
        components.port = port
        components.path = ""
        guard let url = components.url else {
            preconditionFailure("Unrepresentable Bridge address \(host):\(port)")
        }
        self.baseURL = url
        self.token = token

        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 10
        configuration.timeoutIntervalForResource = 600
        configuration.waitsForConnectivity = false
        self.session = URLSession(configuration: configuration)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970 // received_at is epoch seconds
        self.decoder = decoder
    }

    // MARK: - Endpoints

    /// `GET /v1/status` — identity, outbox depth; doubles as a token check.
    func status() async throws -> BridgeStatus {
        try await get("v1/status")
    }

    /// `GET /v1/queue` — pending items, oldest first.
    func queue() async throws -> [PendingPhoto] {
        let response: QueueResponse = try await get("v1/queue")
        return response.items
    }

    /// `POST /v1/photos/{id}/ack` — confirms the save; the Bridge deletes its
    /// spool file.
    func acknowledge(_ itemID: String) async throws {
        let request = request("v1/photos/\(itemID)/ack", method: "POST")
        let (_, response) = try await session.data(for: request)
        try Self.check(response)
    }

    /// `GET /v1/photos/{id}` — streams the file to `destination`.
    ///
    /// If a partial file already exists at `destination` (from an interrupted
    /// earlier attempt) a `Range` request resumes from its end; a 200 reply
    /// means the Bridge ignored the range, so the download restarts cleanly.
    /// Verifies the queue entry's `sha256` over the completed file.
    func downloadPhoto(
        _ item: PendingPhoto,
        to destination: URL,
        progress: @escaping @Sendable (Int64) -> Void
    ) async throws {
        let fileManager = FileManager.default

        var offset: Int64 = 0
        if let attributes = try? fileManager.attributesOfItem(atPath: destination.path),
           let size = attributes[.size] as? Int64 {
            offset = size
        }

        var request = request("v1/photos/\(item.itemID)")
        if offset > 0 {
            request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range")
        }

        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw SyncClientError.invalidResponse
        }
        switch http.statusCode {
        case 200:
            // Full body: either no partial existed or the range was ignored.
            offset = 0
            try? fileManager.removeItem(at: destination)
        case 206:
            break // Appending to the existing partial.
        case 401, 403:
            throw SyncClientError.unauthorized
        default:
            throw SyncClientError.httpStatus(http.statusCode)
        }

        if !fileManager.fileExists(atPath: destination.path) {
            fileManager.createFile(atPath: destination.path, contents: nil)
        }

        var received = offset
        do {
            let handle = try FileHandle(forWritingTo: destination)
            defer { try? handle.close() }
            try handle.seekToEnd()

            var buffer = Data()
            buffer.reserveCapacity(Self.writeChunkSize)
            for try await byte in bytes {
                buffer.append(byte)
                if buffer.count >= Self.writeChunkSize {
                    try handle.write(contentsOf: buffer)
                    received += Int64(buffer.count)
                    buffer.removeAll(keepingCapacity: true)
                    progress(received)
                }
            }
            if !buffer.isEmpty {
                try handle.write(contentsOf: buffer)
                received += Int64(buffer.count)
                progress(received)
            }
        }

        try Self.verifyChecksum(of: destination, expected: item.sha256)
    }

    // MARK: - Plumbing

    private func request(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func get<Response: Decodable>(_ path: String) async throws -> Response {
        let (data, response) = try await session.data(for: request(path))
        try Self.check(response)
        return try decoder.decode(Response.self, from: data)
    }

    private static func check(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw SyncClientError.invalidResponse
        }
        switch http.statusCode {
        case 200...299:
            return
        case 401, 403:
            throw SyncClientError.unauthorized
        default:
            throw SyncClientError.httpStatus(http.statusCode)
        }
    }

    private static func verifyChecksum(of fileURL: URL, expected: String) throws {
        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }

        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        let actual = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard actual == expected.lowercased() else {
            throw SyncClientError.checksumMismatch(expected: expected.lowercased(), actual: actual)
        }
    }
}
