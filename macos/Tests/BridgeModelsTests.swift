import Foundation

final class BridgeModelsTests {
    func testDecodesStableStatusEnvelope() throws {
        let data = Data(
            """
            {
              "schema_version": 1,
              "request_id": "req-status-1",
              "ok": true,
              "status": {
                "device_id": "IB-12345678",
                "display_name": "InstantLink Bridge IB-12345678",
                "bridge_version": "0.1.0",
                "api_version": "1",
                "readiness": "ready",
                "active_upload_mode": "bridge_wifi",
                "uptime_seconds": 42,
                "network": {
                  "mode": "bridge_wifi",
                  "label": "Bridge Wi-Fi",
                  "address": "192.168.8.1",
                  "connected": true
                },
                "printer": {
                  "display_name": "INSTAX-52006924",
                  "model": "Instax Mini Link 3",
                  "film_remaining": 7,
                  "battery_percent": 84,
                  "connected": true,
                  "busy": false
                },
                "update": {
                  "current_version": "0.1.0",
                  "available_version": "0.2.0",
                  "can_update": false,
                  "operation_id": null,
                  "phase": "idle"
                },
                "last_upload": {
                  "filename": "latest.jpg",
                  "received_at": "2026-05-26T12:00:00Z",
                  "printed_at": "2026-05-26T12:00:30Z",
                  "status": "printed"
                }
              }
            }
            """.utf8
        )

        let envelope = try JSONDecoder().decode(BridgeAPIEnvelope.self, from: data)
        let status = try envelope.requireStatus()

        try expectEqual(envelope.schemaVersion, 1)
        try expectEqual(envelope.requestID, "req-status-1")
        try expectEqual(status.deviceID, "IB-12345678")
        try expectEqual(status.readiness, .ready)
        try expectEqual(status.activeUploadMode, .bridgeWiFi)
        try expectEqual(status.network?.label, "Bridge Wi-Fi")
        try expectEqual(status.printer?.filmRemaining, 7)
        try expectEqual(status.update?.availableVersion, "0.2.0")
        try expectEqual(status.lastUpload?.status, "printed")
    }

    func testDecodesAuthRequiredErrorEnvelope() throws {
        let data = Data(
            """
            {
              "schema_version": 1,
              "request_id": "req-auth-1",
              "ok": false,
              "error_code": "auth_required",
              "error": {
                "message": "Bridge access requires pairing",
                "details": {
                  "pairing_window_open": false,
                  "next_step": "open_bridge_access"
                },
                "retry_after_seconds": 90
              }
            }
            """.utf8
        )

        let envelope = try JSONDecoder().decode(BridgeAPIEnvelope.self, from: data)

        do {
            try envelope.requireOK()
            throw MacTestFailure(
                file: #filePath,
                line: #line,
                message: "Expected auth-required envelope to throw"
            )
        } catch let error as BridgeAPIError {
            try expectEqual(error.requestID, "req-auth-1")
            try expectEqual(error.code, .authRequired)
            try expectEqual(error.payload.message, "Bridge access requires pairing")
            try expectEqual(error.payload.details["pairing_window_open"], .bool(false))
            try expectEqual(error.payload.details["next_step"], .string("open_bridge_access"))
            try expectEqual(error.payload.retryAfterSeconds, 90)
        }
    }

    func testDecodesPairingStatusEnvelope() throws {
        let data = Data(
            """
            {
              "schema_version": 1,
              "request_id": "req-pairing-1",
              "ok": true,
              "pairing": {
                "open": true,
                "auth_implemented": true,
                "confirmation_code_required": true,
                "expires_at": 1780500690,
                "expires_in_seconds": 90,
                "paired_client_id": "macbook",
                "authorized_client_count": 1
              }
            }
            """.utf8
        )

        let envelope = try JSONDecoder().decode(BridgeAPIEnvelope.self, from: data)
        let pairing = try envelope.requirePairingStatus()

        try expectTrue(pairing.open)
        try expectTrue(pairing.authImplemented)
        try expectTrue(pairing.confirmationCodeRequired)
        try expectEqual(pairing.expiresAt, 1780500690)
        try expectEqual(pairing.expiresInSeconds, 90)
        try expectEqual(pairing.pairedClientID, "macbook")
        try expectEqual(pairing.authorizedClientCount, 1)
    }
}
