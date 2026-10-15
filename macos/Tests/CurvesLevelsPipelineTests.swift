import CoreImage
import Foundation

final class CurvesLevelsPipelineTests {
    func testLUTBytesMatchFrozenOriginal() throws {
        for (index, fixture) in CurvesLevelsFixtures.exactnessCases().enumerated() {
            let actual = CurvesLevelsPipeline.curvesData(curves: fixture.curves, levels: fixture.levels)
            let expected = CurvesLevelsReference.curvesData(curves: fixture.curves, levels: fixture.levels)
            try expectTrue(actual == expected, "LUT bytes differ for fixture \(index)")
        }
    }

    func testLevelsSamplesPreserveDoubleResults() throws {
        let inputs = (0...32).map { Double($0) / 32 } + [-10, 10, -.infinity, .infinity, .nan]
        for fixture in CurvesLevelsFixtures.exactnessCases() {
            for channel in fixture.levels.channels.values {
                for input in inputs {
                    let actual = CurvesLevelsPipeline.applyLevels(input, channel)
                    let expected = CurvesLevelsReference.applyLevels(input, channel)
                    try expectTrue(actual.bitPattern == expected.bitPattern || (actual.isNaN && expected.isNaN),
                                   "Levels Double result differs")
                }
            }
        }
    }

    func testInactiveSectionsReturnOriginalImage() throws {
        let image = CIImage(color: .red).cropped(to: CGRect(x: 3, y: 5, width: 16, height: 12))
        var fixture = CurvesLevelsFixtures.benchmarkCases()[2].1
        fixture.curves.sectionEnabled = false
        fixture.levels.sectionEnabled = false
        try expectTrue(CurvesLevelsPipeline.apply(image, curves: fixture.curves, levels: fixture.levels) === image)
        try expectTrue(CurvesLevelsPipeline.apply(image, curves: .init(), levels: .init()) === image)
    }

    func testRenderedPixelsMatchFrozenOriginal() throws {
        // Asymmetric RGB/alpha gradient and nonzero extent catch channel/geometry changes.
        let width = 31, height = 19
        var input = [UInt8](repeating: 0, count: width * height * 4)
        for y in 0..<height {
            for x in 0..<width {
                let offset = (y * width + x) * 4
                let alpha = UInt8(80 + (x * 7 + y * 13) % 176)
                input[offset] = UInt8(x * 7 % Int(alpha))
                input[offset + 1] = UInt8(y * 11 % Int(alpha))
                input[offset + 2] = UInt8((x * 3 + y * 5) % Int(alpha))
                input[offset + 3] = alpha
            }
        }
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
        let image = CIImage(bitmapData: Data(input), bytesPerRow: width * 4,
                            size: CGSize(width: width, height: height), format: .RGBA8,
                            colorSpace: colorSpace).transformed(by: CGAffineTransform(translationX: 3, y: 5))
        let context = CIContext(options: nil)
        for fixture in CurvesLevelsFixtures.benchmarkCases().map(\.1) {
            let actual = CurvesLevelsPipeline.apply(image, curves: fixture.curves, levels: fixture.levels)
            let expected = CurvesLevelsReference.apply(image, curves: fixture.curves, levels: fixture.levels)
            try expectEqual(actual.extent, expected.extent)
            var actualPixels = [UInt8](repeating: 0, count: input.count)
            var expectedPixels = actualPixels
            context.render(actual, toBitmap: &actualPixels, rowBytes: width * 4, bounds: actual.extent,
                           format: .RGBA8, colorSpace: colorSpace)
            context.render(expected, toBitmap: &expectedPixels, rowBytes: width * 4, bounds: expected.extent,
                           format: .RGBA8, colorSpace: colorSpace)
            try expectTrue(actualPixels == expectedPixels, "Rendered RGBA bytes differ")
        }
    }

    func testConcurrentLUTConstructionMatchesOriginal() throws {
        let fixtures = CurvesLevelsFixtures.exactnessCases()
        let failures = Failures()
        DispatchQueue.concurrentPerform(iterations: 128) { index in
            let fixture = fixtures[index % fixtures.count]
            if CurvesLevelsPipeline.curvesData(curves: fixture.curves, levels: fixture.levels)
                != CurvesLevelsReference.curvesData(curves: fixture.curves, levels: fixture.levels) {
                failures.record()
            }
        }
        try expectEqual(failures.count, 0)
    }

    private final class Failures: @unchecked Sendable {
        private let lock = NSLock()
        private var storage = 0
        var count: Int { lock.lock(); defer { lock.unlock() }; return storage }
        func record() { lock.lock(); defer { lock.unlock() }; storage += 1 }
    }
}
