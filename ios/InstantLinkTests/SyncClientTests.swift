import CryptoKit
import XCTest
import os
@testable import InstantLink

/// Exercises SyncClient against the Bridge HTTP contract
/// (bridge/src/instantlink_bridge/sync/server.py) via a URLProtocol stub —
/// no network, simulator-safe.
final class SyncClientTests: XCTestCase {
    private let token = "0123456789abcdef0123456789abcdef"
    private var client: SyncClient!
    private var stagingDirectory: URL!

    override func setUpWithError() throws {
        StubURLProtocol.handler = nil
        client = SyncClient(
            host: "192.168.8.1",
            port: 8721,
            token: token,
            protocolClasses: [StubURLProtocol.self]
        )
        stagingDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("SyncClientTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: stagingDirectory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        StubURLProtocol.handler = nil
        try? FileManager.default.removeItem(at: stagingDirectory)
    }

    // MARK: - Auth + status

    func testStatusSendsBearerTokenAndDecodes() async throws {
        let expectedAuthorization = "Bearer \(token)"
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/status")
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Authorization"),
                expectedAuthorization
            )
            return (
                Self.response(for: request, status: 200),
                Data(#"{"device": "IB-A1B2", "proto": 1, "outbox_depth": 2}"#.utf8)
            )
        }

        let status = try await client.status()
        XCTAssertEqual(status, BridgeStatus(deviceID: "IB-A1B2", proto: 1, outboxDepth: 2))
    }

    func testUnauthorizedMapsToTypedError() async {
        // Server shape: 401 {"error": "unauthorized"} with WWW-Authenticate.
        StubURLProtocol.handler = { request in
            (
                Self.response(for: request, status: 401, headers: ["WWW-Authenticate": "Bearer"]),
                Data(#"{"error": "unauthorized"}"#.utf8)
            )
        }

        do {
            _ = try await client.status()
            XCTFail("Expected SyncClientError.unauthorized")
        } catch SyncClientError.unauthorized {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    // MARK: - Queue

    func testQueueDecodesServerShape() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/queue")
            let json = """
            {"items": [
              {"item_id": "item-1", "file_name": "DSC00042.JPG", "size_bytes": 42,
               "sha256": "ff", "received_at": 1752480000,
               "source_remote_ip": "192.168.8.20"},
              {"item_id": "item-2", "file_name": "DSC00043.JPG", "size_bytes": 7,
               "sha256": "aa", "received_at": 1752480060,
               "source_remote_ip": "192.168.8.20"}
            ]}
            """
            return (Self.response(for: request, status: 200), Data(json.utf8))
        }

        let items = try await client.queue()
        XCTAssertEqual(items.map(\.itemID), ["item-1", "item-2"])
        XCTAssertEqual(items[0].fileName, "DSC00042.JPG")
        XCTAssertEqual(items[1].receivedAt, Date(timeIntervalSince1970: 1_752_480_060))
    }

    // MARK: - Download

    func testDownloadFreshFileSendsNoRangeAndReportsProgress() async throws {
        let body = Self.patternData(count: 300_000)
        let destination = stagingDirectory.appendingPathComponent("fresh.jpg")
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/photos/item-1")
            XCTAssertNil(request.value(forHTTPHeaderField: "Range"))
            return (Self.response(for: request, status: 200), body)
        }

        let reported = OSAllocatedUnfairLock(initialState: [Int64]())
        let item = Self.item("item-1", body: body)
        try await client.downloadPhoto(item, to: destination) { received in
            reported.withLock { $0.append(received) }
        }

        XCTAssertEqual(try Data(contentsOf: destination), body)
        let progress = reported.withLock { $0 }
        XCTAssertEqual(progress.last, Int64(body.count))
        XCTAssertEqual(progress, progress.sorted(), "progress must be monotonic")
    }

    func testDownloadResumesPartialWith206Append() async throws {
        let body = Self.patternData(count: 200_000)
        let splitPoint = 80_000
        let destination = stagingDirectory.appendingPathComponent("resume.jpg")
        try body.prefix(splitPoint).write(to: destination)

        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Range"), "bytes=\(splitPoint)-")
            let headers = ["Content-Range": "bytes \(splitPoint)-\(body.count - 1)/\(body.count)"]
            return (
                Self.response(for: request, status: 206, headers: headers),
                body.suffix(from: splitPoint)
            )
        }

        let reported = OSAllocatedUnfairLock(initialState: [Int64]())
        let item = Self.item("item-1", body: body)
        try await client.downloadPhoto(item, to: destination) { received in
            reported.withLock { $0.append(received) }
        }

        XCTAssertEqual(try Data(contentsOf: destination), body)
        // Progress resumes from the partial's size, not from zero.
        let progress = reported.withLock { $0 }
        XCTAssertGreaterThan(try XCTUnwrap(progress.first), Int64(splitPoint))
        XCTAssertEqual(progress.last, Int64(body.count))
    }

    func testDownloadRestartsCleanlyWhenRangeIgnored() async throws {
        let body = Self.patternData(count: 100_000)
        let destination = stagingDirectory.appendingPathComponent("restart.jpg")
        try Data("stale garbage from an aborted attempt".utf8).write(to: destination)

        StubURLProtocol.handler = { request in
            // The client asked to resume, but a 200 means the Bridge ignored
            // the range — the stale partial must be discarded.
            XCTAssertNotNil(request.value(forHTTPHeaderField: "Range"))
            return (Self.response(for: request, status: 200), body)
        }

        let item = Self.item("item-1", body: body)
        try await client.downloadPhoto(item, to: destination) { _ in }

        XCTAssertEqual(try Data(contentsOf: destination), body)
    }

    func testDownloadFailsChecksumOnCorruptBytes() async {
        let body = Self.patternData(count: 50_000)
        let destination = stagingDirectory.appendingPathComponent("corrupt.jpg")
        StubURLProtocol.handler = { request in
            (Self.response(for: request, status: 200), body)
        }

        // Expected digest is for different content.
        let item = PendingPhoto(
            itemID: "item-1",
            fileName: "DSC00042.JPG",
            sizeBytes: Int64(body.count),
            sha256: Self.sha256Hex(Data("something else entirely".utf8)),
            receivedAt: Date()
        )

        do {
            try await client.downloadPhoto(item, to: destination) { _ in }
            XCTFail("Expected SyncClientError.checksumMismatch")
        } catch SyncClientError.checksumMismatch(let expected, let actual) {
            XCTAssertEqual(actual, Self.sha256Hex(body))
            XCTAssertNotEqual(expected, actual)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testDownloadUnauthorizedMapsToTypedError() async {
        StubURLProtocol.handler = { request in
            (Self.response(for: request, status: 401), Data(#"{"error": "unauthorized"}"#.utf8))
        }

        let destination = stagingDirectory.appendingPathComponent("denied.jpg")
        do {
            try await client.downloadPhoto(Self.item("item-1", body: Data()), to: destination) { _ in }
            XCTFail("Expected SyncClientError.unauthorized")
        } catch SyncClientError.unauthorized {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    // MARK: - Ack

    func testAckPostsAndSucceeds() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/v1/photos/item-9/ack")
            return (Self.response(for: request, status: 200), Data(#"{"ok": true}"#.utf8))
        }

        try await client.acknowledge("item-9")
    }

    func testAckUnknownItemSurfaces404() async {
        StubURLProtocol.handler = { request in
            (
                Self.response(for: request, status: 404),
                Data(#"{"error": "unknown_item", "item_id": "nope"}"#.utf8)
            )
        }

        do {
            try await client.acknowledge("nope")
            XCTFail("Expected SyncClientError.httpStatus(404)")
        } catch SyncClientError.httpStatus(404) {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    // MARK: - Helpers

    private static func item(_ itemID: String, body: Data) -> PendingPhoto {
        PendingPhoto(
            itemID: itemID,
            fileName: "DSC00042.JPG",
            sizeBytes: Int64(body.count),
            sha256: sha256Hex(body),
            receivedAt: Date(timeIntervalSince1970: 1_752_480_000)
        )
    }

    private static func response(
        for request: URLRequest,
        status: Int,
        headers: [String: String]? = nil
    ) -> HTTPURLResponse {
        HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: headers
        )!
    }

    private static func patternData(count: Int) -> Data {
        Data((0..<count).map { UInt8($0 % 251) })
    }

    private static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - URLProtocol stub

/// Serves canned responses in-process. Tests run serially in one process, so
/// a static handler is sufficient.
private final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            if !data.isEmpty {
                // Deliver in slices so the client's chunked read path sees
                // more than one data callback.
                let sliceSize = 64 * 1024
                var index = data.startIndex
                while index < data.endIndex {
                    let end = data.index(index, offsetBy: sliceSize, limitedBy: data.endIndex)
                        ?? data.endIndex
                    client?.urlProtocol(self, didLoad: data[index..<end])
                    index = end
                }
            }
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
