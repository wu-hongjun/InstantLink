import XCTest
@testable import InstantLink

final class PairingInfoTests: XCTestCase {
    private let token = "0123456789abcdef0123456789ABCDEF"

    // MARK: - Accepted payloads

    func testParsesFullHotspotURL() throws {
        let info = try PairingInfo.parse(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&port=8721"
                + "&token=\(token)&ssid=InstantLink-A1B2&psk=12345678"
        )
        XCTAssertEqual(info.version, 1)
        XCTAssertEqual(info.deviceID, "IB-A1B2")
        XCTAssertEqual(info.host, "192.168.8.1")
        XCTAssertEqual(info.port, 8721)
        XCTAssertEqual(info.token, token)
        XCTAssertEqual(info.ssid, "InstantLink-A1B2")
        XCTAssertEqual(info.psk, "12345678")
        XCTAssertTrue(info.needsHotspotJoin)
    }

    func testParsesSameWiFiVariantWithoutSSID() throws {
        let info = try PairingInfo.parse(
            "instantlink://pair?v=1&device=IB-A1B2&host=10.0.1.17&port=8721&token=\(token)"
        )
        XCTAssertNil(info.ssid)
        XCTAssertNil(info.psk)
        XCTAssertFalse(info.needsHotspotJoin)
        XCTAssertEqual(info.host, "10.0.1.17")
    }

    func testDefaultsPortWhenAbsent() throws {
        let info = try PairingInfo.parse(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)"
        )
        XCTAssertEqual(info.port, PairingInfo.defaultPort)
    }

    func testDropsPSKWhenSSIDAbsent() throws {
        // A psk without an ssid is meaningless; Same Wi-Fi mode wins.
        let info = try PairingInfo.parse(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)&psk=12345678"
        )
        XCTAssertNil(info.ssid)
        XCTAssertNil(info.psk)
        XCTAssertFalse(info.needsHotspotJoin)
    }

    func testURLEncodedValuesRoundTrip() throws {
        var components = URLComponents()
        components.scheme = "instantlink"
        components.host = "pair"
        components.queryItems = [
            URLQueryItem(name: "v", value: "1"),
            URLQueryItem(name: "device", value: "IB-A1B2"),
            URLQueryItem(name: "host", value: "192.168.8.1"),
            URLQueryItem(name: "port", value: "8721"),
            URLQueryItem(name: "token", value: token),
            URLQueryItem(name: "ssid", value: "My Bridge #2 & Co"),
            URLQueryItem(name: "psk", value: "87654321"),
        ]
        let encoded = try XCTUnwrap(components.string)

        let info = try PairingInfo.parse(encoded)
        XCTAssertEqual(info.ssid, "My Bridge #2 & Co")
        XCTAssertEqual(info.psk, "87654321")
    }

    // MARK: - Rejected payloads

    func testRejectsWrongScheme() {
        assertParseError(
            "https://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)",
            .notAPairingURL
        )
    }

    func testRejectsWrongHost() {
        assertParseError(
            "instantlink://print?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)",
            .notAPairingURL
        )
    }

    func testRejectsNonURLGarbage() {
        assertParseError("definitely not a pairing link", .notAPairingURL)
    }

    func testRejectsUnsupportedVersion() {
        assertParseError(
            "instantlink://pair?v=2&device=IB-A1B2&host=192.168.8.1&token=\(token)",
            .unsupportedVersion(2)
        )
    }

    func testRejectsMissingVersion() {
        assertParseError(
            "instantlink://pair?device=IB-A1B2&host=192.168.8.1&token=\(token)",
            .missingField("v")
        )
    }

    func testRejectsMissingDevice() {
        assertParseError(
            "instantlink://pair?v=1&host=192.168.8.1&token=\(token)",
            .missingField("device")
        )
    }

    func testRejectsMissingHost() {
        assertParseError(
            "instantlink://pair?v=1&device=IB-A1B2&token=\(token)",
            .missingField("host")
        )
    }

    func testRejectsMissingToken() {
        assertParseError(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1",
            .missingField("token")
        )
    }

    func testRejectsMalformedToken() {
        assertParseError(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=not-hex-at-all",
            .invalidToken
        )
    }

    func testRejectsShortPSK() {
        assertParseError(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)"
                + "&ssid=InstantLink-A1B2&psk=1234",
            .invalidPSK
        )
    }

    func testRejectsNonNumericPSK() {
        assertParseError(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)"
                + "&ssid=InstantLink-A1B2&psk=abcdefgh",
            .invalidPSK
        )
    }

    func testRejectsMissingPSKWhenSSIDPresent() {
        assertParseError(
            "instantlink://pair?v=1&device=IB-A1B2&host=192.168.8.1&token=\(token)"
                + "&ssid=InstantLink-A1B2",
            .invalidPSK
        )
    }

    // MARK: - Helpers

    private func assertParseError(
        _ payload: String,
        _ expected: PairingInfo.ParseError,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertThrowsError(try PairingInfo.parse(payload), file: file, line: line) { error in
            XCTAssertEqual(error as? PairingInfo.ParseError, expected, file: file, line: line)
        }
    }
}
