import XCTest
@testable import InstantLink

/// Decoding fixtures mirror the Bridge's phase A JSON exactly
/// (bridge/src/instantlink_bridge/sync/server.py `_handle_status` /
/// `_handle_queue`).
final class SyncModelsTests: XCTestCase {
    /// Same configuration as SyncClient: `received_at` is epoch seconds.
    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        return decoder
    }()

    func testDecodesStatus() throws {
        let json = #"{"device": "IB-A1B2", "proto": 1, "outbox_depth": 3}"#
        let status = try decoder.decode(BridgeStatus.self, from: Data(json.utf8))
        XCTAssertEqual(status, BridgeStatus(deviceID: "IB-A1B2", proto: 1, outboxDepth: 3))
    }

    func testDecodesQueueMatchingServerShape() throws {
        let json = """
        {
          "items": [
            {
              "item_id": "0f9a4c2e5b8d47a1",
              "file_name": "DSC00042.JPG",
              "size_bytes": 8388608,
              "sha256": "a3f5c2d47e8b19c6a3f5c2d47e8b19c6a3f5c2d47e8b19c6a3f5c2d47e8b19c6",
              "received_at": 1752480000,
              "source_remote_ip": "192.168.8.20"
            }
          ]
        }
        """
        let response = try decoder.decode(QueueResponse.self, from: Data(json.utf8))
        let item = try XCTUnwrap(response.items.first)
        XCTAssertEqual(response.items.count, 1)
        XCTAssertEqual(item.itemID, "0f9a4c2e5b8d47a1")
        XCTAssertEqual(item.id, item.itemID)
        XCTAssertEqual(item.fileName, "DSC00042.JPG")
        XCTAssertEqual(item.sizeBytes, 8_388_608)
        XCTAssertEqual(
            item.sha256,
            "a3f5c2d47e8b19c6a3f5c2d47e8b19c6a3f5c2d47e8b19c6a3f5c2d47e8b19c6"
        )
        XCTAssertEqual(item.receivedAt, Date(timeIntervalSince1970: 1_752_480_000))
    }

    func testDecodesFractionalEpochSeconds() throws {
        // The Bridge stamps received_at with time.time(), which may carry a
        // fractional part.
        let json = """
        {"item_id": "x", "file_name": "a.jpg", "size_bytes": 1, "sha256": "ff",
         "received_at": 1752480000.25}
        """
        let item = try decoder.decode(PendingPhoto.self, from: Data(json.utf8))
        XCTAssertEqual(item.receivedAt.timeIntervalSince1970, 1_752_480_000.25, accuracy: 0.001)
    }

    func testDecodesEmptyQueue() throws {
        let response = try decoder.decode(QueueResponse.self, from: Data(#"{"items": []}"#.utf8))
        XCTAssertTrue(response.items.isEmpty)
    }

    func testToleratesUnknownFields() throws {
        // A future Bridge may add fields; Decodable must ignore them.
        let statusJSON = """
        {"device": "IB-A1B2", "proto": 1, "outbox_depth": 0,
         "battery_percent": 87, "firmware": "1.2.0"}
        """
        XCTAssertNoThrow(try decoder.decode(BridgeStatus.self, from: Data(statusJSON.utf8)))

        let itemJSON = """
        {"item_id": "x", "file_name": "a.jpg", "size_bytes": 1, "sha256": "ff",
         "received_at": 1752480000, "source_remote_ip": "192.168.8.20",
         "thumbnail_url": "/v1/thumbs/x"}
        """
        XCTAssertNoThrow(try decoder.decode(PendingPhoto.self, from: Data(itemJSON.utf8)))
    }
}
