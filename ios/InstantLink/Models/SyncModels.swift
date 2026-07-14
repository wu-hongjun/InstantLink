import Foundation

// JSON shapes for the Bridge sync HTTP API on :8721 (plan 050, phase A).
//
// Field names match the phase A implementation in
// bridge/src/instantlink_bridge/sync/ (server.py `_handle_status` /
// `_handle_queue`, models.py `OutboxItem`). The Bridge serialises snake_case;
// unknown extra keys (e.g. `source_remote_ip`) are ignored by Decodable.

/// `GET /v1/status` — Bridge identity and outbox depth. Also used as a
/// liveness/token check.
///
/// Body: `{"device": "IB-XXXX", "proto": 1, "outbox_depth": 3}`
struct BridgeStatus: Decodable, Equatable {
    let deviceID: String
    let proto: Int
    let outboxDepth: Int

    enum CodingKeys: String, CodingKey {
        case deviceID = "device"
        case proto
        case outboxDepth = "outbox_depth"
    }
}

/// `GET /v1/queue` — envelope for the pending-item list.
struct QueueResponse: Decodable {
    let items: [PendingPhoto]
}

/// A single pending photo in the Bridge's sync outbox (`OutboxItem`).
struct PendingPhoto: Decodable, Identifiable, Equatable {
    let itemID: String
    /// Original upload file name; duplicates allowed (spool is keyed by id).
    let fileName: String
    let sizeBytes: Int64
    /// Lowercase hex SHA-256 of the file bytes; verified after download.
    let sha256: String
    /// When the Bridge received the upload (epoch seconds on the wire;
    /// decoded via `.secondsSince1970`). Capture time comes from the photo's
    /// own EXIF, which Photos reads at save time.
    let receivedAt: Date

    var id: String { itemID }

    enum CodingKeys: String, CodingKey {
        case itemID = "item_id"
        case fileName = "file_name"
        case sizeBytes = "size_bytes"
        case sha256
        case receivedAt = "received_at"
    }
}
