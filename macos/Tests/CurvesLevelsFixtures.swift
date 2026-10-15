import CoreGraphics
import Foundation

/// Deterministic cases shared by the exactness tests and audit benchmark.
enum CurvesLevelsFixtures {
    typealias Fixture = (curves: AdjustmentState.Curves, levels: AdjustmentState.Levels)

    static func benchmarkCases() -> [(String, Fixture)] {
        let curves = AdjustmentState.Curves(
            master: [CGPoint(x: 0, y: 0), CGPoint(x: 0.3, y: 0.2), CGPoint(x: 0.7, y: 0.8), CGPoint(x: 1, y: 1)],
            red: [CGPoint(x: 0, y: 0.05), CGPoint(x: 0.5, y: 0.6), CGPoint(x: 1, y: 0.95)]
        )
        var levels = AdjustmentState.Levels()
        levels.channels[.luminance] = .init(blackIn: 0.03, shadows: 0.2, gamma: 1.2,
                                          highlights: 0.8, whiteIn: 0.97, blackOut: 0.02, whiteOut: 0.98)
        levels.channels[.red]?.gamma = 0.8
        levels.channels[.rgb]?.gamma = 1.1
        return [
            ("levels", (.init(), levels)),
            ("curves", (curves, .init())),
            ("combined", (curves, levels)),
            ("neutral", (.init(), .init())),
        ]
    }

    static func exactnessCases() -> [Fixture] {
        var result = benchmarkCases().map(\.1)
        var random: UInt64 = 0x20261015
        func next() -> Double {
            random = random &* 6364136223846793005 &+ 1442695040888963407
            return Double(random >> 11) / Double(UInt64(1) << 53)
        }
        for i in 0..<256 {
            func points() -> [CGPoint] {
                (0..<5).map { _ in CGPoint(x: next() * 1.4 - 0.2, y: next() * 1.4 - 0.2) }
            }
            var curves = AdjustmentState.Curves(master: points(), red: points(), green: points(), blue: points())
            curves.sectionEnabled = i % 5 != 0
            var levels = AdjustmentState.Levels()
            for channel in AdjustmentState.Levels.Channel.allCases {
                levels.channels[channel] = .init(
                    blackIn: next() * 1.4 - 0.2, shadows: next(), gamma: next() * 11 - 0.5,
                    highlights: next(), whiteIn: next() * 1.4 - 0.2,
                    blackOut: next() * 1.4 - 0.2, whiteOut: next() * 1.4 - 0.2
                )
            }
            if i % 7 == 0 { levels.channels.removeValue(forKey: .red) }
            if i % 11 == 0 { levels.channels.removeAll() }
            levels.sectionEnabled = i % 3 != 0
            result.append((curves, levels))
        }
        // Preserve existing clamp/non-finite behavior as well as normal sliders.
        let keyPaths: [WritableKeyPath<AdjustmentState.Levels.ChannelLevels, Double>] = [
            \.blackIn, \.shadows, \.gamma, \.highlights, \.whiteIn, \.blackOut, \.whiteOut,
        ]
        for keyPath in keyPaths {
            for value in [Double.nan, .infinity, -.infinity, -0.0, -10, 10] {
                var channel = AdjustmentState.Levels.ChannelLevels()
                channel[keyPath: keyPath] = value
                var levels = AdjustmentState.Levels()
                levels.channels[.rgb] = channel
                result.append((.init(), levels))
            }
        }
        let curveCases: [[CGPoint]] = [
            [], [.init(x: 0.5, y: 0.7)],
            [.init(x: 1, y: 0), .init(x: 0, y: 1), .init(x: 0, y: 0.5)],
        ]
        for points in curveCases {
            result.append((.init(master: points), .init()))
        }
        return result
    }
}
