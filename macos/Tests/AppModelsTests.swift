import Foundation

final class AppModelsTests {
    func setUp() {
        resetStoredNewPhotoDefaults()
    }

    func tearDown() {
        resetStoredNewPhotoDefaults()
    }

    func testPrinterProfileParsesSerialNumberFromInstaxIdentifier() throws {
        try expectEqual(PrinterProfile.parseSerialNumber(from: "INSTAX-52006924 (IOS)"), "52006924")
        try expectEqual(PrinterProfile.parseSerialNumber(from: "52006924"), "52006924")
        try expectNil(PrinterProfile.parseSerialNumber(from: "INSTAX-ABCDEF"))
    }

    func testPrinterModelCatalogReturnsExpectedAspectRatioAndTag() throws {
        try expectEqual(PrinterModelCatalog.aspectRatio(for: "Instax Square Link"), 1.0)
        try expectEqual(PrinterModelCatalog.aspectRatio(for: "Instax Mini Link 3"), 600.0 / 800.0)
        try expectEqual(PrinterModelCatalog.aspectRatio(for: "Instax Wide Link"), 1260.0 / 840.0)
        try expectNil(PrinterModelCatalog.aspectRatio(for: "Unknown"))

        try expectEqual(PrinterModelCatalog.filmFormatTag(for: "Instax Square Link"), "Sqre")
        try expectEqual(PrinterModelCatalog.filmFormatTag(for: "Instax Mini Link 3"), "Mini")
        try expectEqual(PrinterModelCatalog.filmFormatTag(for: "Instax Wide Link"), "Wide")
        try expectNil(PrinterModelCatalog.filmFormatTag(for: nil))
    }

    func testNewPhotoDefaultsSanitizedKeepsOnlyFirstTimestampOverlay() throws {
        let timestampA = makeTimestampOverlay("contax")
        let timestampB = makeTimestampOverlay("classic")
        let defaults = NewPhotoDefaults(
            fitMode: "contain",
            rotationAngle: 90,
            isHorizontallyFlipped: true,
            overlays: [makeTextOverlay("ignored"), timestampA, timestampB],
            filmOrientation: "vertical"
        )

        let sanitized = defaults.sanitized

        try expectEqual(sanitized.fitMode, "contain")
        try expectEqual(sanitized.overlays.count, 1)
        try expectEqual(sanitized.overlays.first?.content, timestampA.content)
    }
}
