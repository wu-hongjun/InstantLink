import CryptoKit
import Foundation
import os

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

    /// - Parameter protocolClasses: test hook — `URLProtocol` stubs installed
    ///   on the session configuration; nil in production.
    init(host: String, port: Int, token: String, protocolClasses: [AnyClass]? = nil) {
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
        if let protocolClasses {
            configuration.protocolClasses = protocolClasses
        }
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
    /// The body streams to disk in whole `Data` chunks via a per-task
    /// delegate — no per-byte `AsyncBytes` iteration, which was far too slow
    /// for 100 MP camera files. Verifies the queue entry's `sha256` over the
    /// completed file (streamed in 1 MiB chunks).
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

        let delegate = ChunkedDownloadDelegate()
        let task = session.dataTask(with: request)
        task.delegate = delegate

        let http = try await delegate.start(task)
        switch http.statusCode {
        case 200:
            // Full body: either no partial existed or the range was ignored.
            offset = 0
            try? fileManager.removeItem(at: destination)
        case 206:
            break // Appending to the existing partial.
        case 401, 403:
            task.cancel()
            throw SyncClientError.unauthorized
        default:
            task.cancel()
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

            for try await chunk in delegate.chunks {
                try handle.write(contentsOf: chunk)
                received += Int64(chunk.count)
                delegate.consumed(byteCount: chunk.count)
                progress(received)
            }
        }

        // A cancelled sync pass ends the chunk stream without throwing; bail
        // out before the checksum pass so the partial survives for a Range
        // resume on the next pass.
        try Task.checkCancellation()

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

// MARK: - Chunked download plumbing

/// Per-task URLSession delegate exposing a data task's body as an
/// `AsyncThrowingStream` of whole `Data` chunks.
///
/// Watermark backpressure keeps memory bounded: the task suspends when the
/// consumer trails the network by `highWaterMark` buffered bytes and resumes
/// once the consumer drains to half of that. `URLSessionTask.suspend()` /
/// `.resume()` are always called while holding the state lock so the two
/// sides cannot interleave into a stuck double-suspend.
private final class ChunkedDownloadDelegate: NSObject, URLSessionDataDelegate {
    private static let highWaterMark = 4 << 20 // 4 MiB buffered ahead of the file writer

    private struct State {
        var task: URLSessionDataTask?
        var responseContinuation: CheckedContinuation<HTTPURLResponse, Error>?
        var chunkContinuation: AsyncThrowingStream<Data, Error>.Continuation?
        var bufferedBytes = 0
        var isSuspended = false
    }

    private let state: OSAllocatedUnfairLock<State>

    /// Body chunks in arrival order. Finishes when the task completes and
    /// throws the task's error on failure. Abandoning iteration (including
    /// consumer-side cancellation) cancels the underlying task.
    let chunks: AsyncThrowingStream<Data, Error>

    override init() {
        var continuation: AsyncThrowingStream<Data, Error>.Continuation!
        self.chunks = AsyncThrowingStream { continuation = $0 }
        let state = OSAllocatedUnfairLock(initialState: State(chunkContinuation: continuation))
        self.state = state
        super.init()
        continuation.onTermination = { _ in
            // Cancelling an already-finished task is a no-op.
            state.withLock { $0.task }?.cancel()
        }
    }

    /// Resumes `task` and suspends until its HTTP response header arrives.
    func start(_ task: URLSessionDataTask) async throws -> HTTPURLResponse {
        try await withCheckedThrowingContinuation { continuation in
            state.withLock {
                $0.task = task
                $0.responseContinuation = continuation
            }
            task.resume()
        }
    }

    /// The consumer calls this after handling a chunk so backpressure can
    /// track how far it trails the network.
    func consumed(byteCount: Int) {
        state.withLock { state in
            state.bufferedBytes -= byteCount
            guard state.isSuspended, state.bufferedBytes <= Self.highWaterMark / 2 else { return }
            state.isSuspended = false
            state.task?.resume()
        }
    }

    // MARK: URLSessionDataDelegate

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        let continuation = state.withLock { state -> CheckedContinuation<HTTPURLResponse, Error>? in
            defer { state.responseContinuation = nil }
            return state.responseContinuation
        }
        guard let http = response as? HTTPURLResponse else {
            continuation?.resume(throwing: SyncClientError.invalidResponse)
            completionHandler(.cancel)
            return
        }
        continuation?.resume(returning: http)
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        state.withLock { state in
            state.bufferedBytes += data.count
            state.chunkContinuation?.yield(data)
            guard state.bufferedBytes >= Self.highWaterMark, !state.isSuspended else { return }
            state.isSuspended = true
            dataTask.suspend()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let (responseContinuation, chunkContinuation) = state.withLock { state in
            defer {
                state.responseContinuation = nil
                state.chunkContinuation = nil
            }
            return (state.responseContinuation, state.chunkContinuation)
        }
        // Still pending only when the task died before its header arrived
        // (connection refused, early cancel, ...).
        responseContinuation?.resume(throwing: error ?? SyncClientError.invalidResponse)
        if let error {
            chunkContinuation?.finish(throwing: error)
        } else {
            chunkContinuation?.finish()
        }
    }
}
