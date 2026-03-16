import AppKit
import Foundation

enum AppRelauncher {
    static func relaunchCurrentApp() {}
}

struct MacTestFailure: Error, CustomStringConvertible {
    let file: String
    let line: UInt
    let message: String

    var description: String {
        "\(file):\(line): \(message)"
    }
}

func expectTrue(
    _ expression: @autoclosure () -> Bool,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) throws {
    if !expression() {
        throw MacTestFailure(
            file: "\(file)",
            line: line,
            message: message().isEmpty ? "Expected condition to be true" : message()
        )
    }
}

func expectFalse(
    _ expression: @autoclosure () -> Bool,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) throws {
    if expression() {
        throw MacTestFailure(
            file: "\(file)",
            line: line,
            message: message().isEmpty ? "Expected condition to be false" : message()
        )
    }
}

func expectNil<T>(
    _ expression: @autoclosure () -> T?,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) throws {
    if expression() != nil {
        throw MacTestFailure(
            file: "\(file)",
            line: line,
            message: message().isEmpty ? "Expected value to be nil" : message()
        )
    }
}

func expectEqual<T: Equatable>(
    _ lhs: @autoclosure () -> T,
    _ rhs: @autoclosure () -> T,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) throws {
    let lhsValue = lhs()
    let rhsValue = rhs()
    if lhsValue != rhsValue {
        let defaultMessage = "Expected \(lhsValue) to equal \(rhsValue)"
        throw MacTestFailure(
            file: "\(file)",
            line: line,
            message: message().isEmpty ? defaultMessage : message()
        )
    }
}

func makeTestImage(size: CGSize = CGSize(width: 8, height: 8)) -> NSImage {
    let image = NSImage(size: size)
    image.lockFocus()
    NSColor.white.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: size)).fill()
    image.unlockFocus()
    return image
}

func makeTestURL(_ name: String) -> URL {
    URL(fileURLWithPath: "/tmp/\(name)")
}

func makeTextOverlay(_ text: String = "Test") -> OverlayItem {
    OverlayItem(content: .text(TextOverlayData(text: text)))
}

func makeTimestampOverlay(_ presetKey: String = "contax") -> OverlayItem {
    OverlayItem(content: .timestamp(TimestampOverlayData(presetKey: presetKey)))
}

func makeQueueImportItem(
    name: String,
    imageDate: Date? = nil,
    imageLocation: ImageLocationMetadata? = nil
) -> QueueImportItem {
    QueueImportItem(
        url: makeTestURL(name),
        image: makeTestImage(),
        imageDate: imageDate,
        imageLocation: imageLocation
    )
}

@MainActor
func waitUntil(
    timeout: TimeInterval = 1.0,
    pollInterval: UInt64 = 20_000_000,
    _ condition: @escaping @MainActor () -> Bool
) async -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if condition() { return true }
        try? await Task.sleep(nanoseconds: pollInterval)
    }
    return false
}

func resetStoredNewPhotoDefaults() {
    UserDefaults.standard.removeObject(forKey: NewPhotoDefaults.storageKey)
}
