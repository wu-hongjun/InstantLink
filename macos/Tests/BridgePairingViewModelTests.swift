import Foundation

final class BridgePairingViewModelTests {
    func testCodeValidationRejectsNonDigits() throws {
        let sanitized = BridgePairingView.sanitize(code: "12ab34", max: 6)
        try expectEqual(sanitized, "1234")
        try expectFalse(BridgePairingView.validate(code: "12ab34", expected: 6))
    }

    func testCodeValidationRequiresSixDigits() throws {
        try expectTrue(BridgePairingView.validate(code: "123456", expected: 6))
        try expectFalse(BridgePairingView.validate(code: "1234", expected: 6))
        try expectFalse(BridgePairingView.validate(code: "1234567", expected: 6))
    }

    func testSanitizeTruncatesToMaximum() throws {
        let sanitized = BridgePairingView.sanitize(code: "1234567890", max: 6)
        try expectEqual(sanitized, "123456")
    }
}
