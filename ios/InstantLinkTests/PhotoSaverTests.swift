import UniformTypeIdentifiers
import XCTest

@testable import InstantLink

final class PhotoSaverTests: XCTestCase {
    func testSonyHIFMapsToHEIF() {
        // Sony writes HEIF stills as .HIF, which UTType alone does not map;
        // without this the Photos save rejects every camera HEIF (observed
        // in the 2026-07-15 field test as an endless download/no-ack loop).
        XCTAssertEqual(PhotoSaver.inferredType(forFileName: "DSC01261.HIF"), .heif)
        XCTAssertEqual(PhotoSaver.inferredType(forFileName: "dsc01261.hif"), .heif)
    }

    func testCommonExtensionsResolveToImageTypes() {
        XCTAssertEqual(PhotoSaver.inferredType(forFileName: "IMG_0001.jpg"), .jpeg)
        XCTAssertEqual(PhotoSaver.inferredType(forFileName: "IMG_0001.jpeg"), .jpeg)
        XCTAssertEqual(PhotoSaver.inferredType(forFileName: "shot.heic"), .heic)
        XCTAssertEqual(PhotoSaver.inferredType(forFileName: "frame.png"), .png)
    }

    func testSonyRawResolvesToARawImageType() {
        let type = PhotoSaver.inferredType(forFileName: "DSC01261.ARW")
        XCTAssertNotNil(type)
        XCTAssertTrue(type!.conforms(to: .image) || type! == .rawImage)
    }

    func testUnknownOrMissingExtensionReturnsNil() {
        XCTAssertNil(PhotoSaver.inferredType(forFileName: "mystery.xyz123"))
        XCTAssertNil(PhotoSaver.inferredType(forFileName: "no-extension"))
    }
}
